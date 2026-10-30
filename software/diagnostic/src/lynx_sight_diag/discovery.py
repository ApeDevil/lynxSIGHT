"""Camera discovery: which /dev/video* nodes are real cameras, what they can do, who holds them.

A UVC camera such as the Arducam B0332 usually exposes two nodes: a video-capture node and a
metadata node. Nodes are grouped into one `PhysicalCamera` by their USB device, and each camera
gets the most stable identifier available:

* ``/dev/v4l/by-path/...`` follows the USB port. Two identical cameras without unique serial
  numbers can only be told apart this way, so it is the preferred ID for the stereo pair.
* ``/dev/v4l/by-id/...`` follows the USB serial number; it collides when both units report the
  same (or no) serial.
* ``/dev/videoN`` changes with plug order and is a last resort.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import v4l2


@dataclass
class NodeProbe:
    """What opening a node told us. `error` is set instead of the other fields on failure."""

    capability: v4l2.Capability | None = None
    modes: list[v4l2.FrameMode] = field(default_factory=list)
    controls: dict[str, v4l2.ControlInfo] = field(default_factory=dict)
    streaming_elsewhere: bool | None = None
    error: str | None = None


@dataclass
class VideoNode:
    path: str  # /dev/videoN
    name: str  # sysfs name (card)
    index: int  # sysfs index: 0 = primary node of the interface, 1+ = metadata etc.
    by_id: list[str]
    by_path: list[str]
    probe: NodeProbe
    holders: list[str]  # "pid:comm" of processes having the node open (own processes only)

    @property
    def kind(self) -> str:
        cap = self.probe.capability
        if cap is None:
            # Without ioctl access fall back on the UVC convention: index 0 is the capture node.
            return "capture?" if self.index == 0 else "other?"
        if cap.is_video_capture:
            return "capture"
        if cap.is_metadata:
            return "metadata"
        return "other"


@dataclass
class UsbInfo:
    sysfs_path: str
    vendor_id: str | None
    product_id: str | None
    manufacturer: str | None
    product: str | None
    serial: str | None
    bus_port: str | None  # devpath like "1-2.3"
    speed_mbps: str | None


@dataclass
class PhysicalCamera:
    name: str
    usb: UsbInfo | None
    nodes: list[VideoNode]

    @property
    def capture_node(self) -> VideoNode | None:
        for node in self.nodes:
            if node.kind in ("capture", "capture?"):
                return node
        return None

    @property
    def stable_path(self) -> str | None:
        """Preferred device path for configs: by-path, then by-id, then /dev/videoN."""
        node = self.capture_node
        if node is None:
            return None
        if node.by_path:
            return node.by_path[0]
        if node.by_id:
            return node.by_id[0]
        return node.path

    @property
    def status(self) -> str:
        node = self.capture_node
        if node is None:
            return "no capture node"
        if node.probe.error:
            return node.probe.error
        if node.probe.streaming_elsewhere or node.holders:
            who = ", ".join(node.holders) or "another process"
            return f"busy (in use by {who})" if node.probe.streaming_elsewhere else f"open by {who}"
        return "available"

    @property
    def is_candidate(self) -> bool:
        """Looks like one of our OV9281 cameras (name match; unverified on real units)."""
        text = " ".join(filter(None, [self.name, self.usb and self.usb.product])).lower()
        return any(token in text for token in ("arducam", "ov9281", "b0332"))

    def to_dict(self) -> dict:
        out = asdict(self)
        out["stable_path"] = self.stable_path
        out["status"] = self.status
        out["is_candidate"] = self.is_candidate
        for node, raw in zip(self.nodes, out["nodes"], strict=True):
            raw["kind"] = node.kind
            raw["probe"]["modes"] = [str(m) for m in node.probe.modes]
            raw["probe"]["controls"] = {
                k: {"min": c.minimum, "max": c.maximum, "default": c.default, "menu": c.menu}
                for k, c in node.probe.controls.items()
            }
        return out


Prober = Callable[[str], NodeProbe]


def probe_node(path: str) -> NodeProbe:
    """Opens a node and queries capabilities, modes and controls via V4L2 ioctls."""
    try:
        fd = v4l2.open_device(path)
    except OSError as exc:
        if exc.errno == errno.EACCES:
            return NodeProbe(error="permission denied (is your user in the 'video' group?)")
        if exc.errno == errno.EBUSY:
            return NodeProbe(error="busy (exclusive open by another process)")
        return NodeProbe(error=f"cannot open: {os.strerror(exc.errno or 0)}")
    try:
        cap = v4l2.query_capability(fd)
        probe = NodeProbe(capability=cap)
        if cap.is_video_capture:
            probe.modes = v4l2.query_modes(fd)
            probe.controls = v4l2.query_controls(fd)
            try:
                probe.streaming_elsewhere = v4l2.is_streaming_elsewhere(fd)
            except OSError:
                probe.streaming_elsewhere = None
        return probe
    except OSError as exc:
        return NodeProbe(error=f"ioctl failed: {os.strerror(exc.errno or 0)}")
    finally:
        os.close(fd)


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _symlink_map(directory: Path) -> dict[str, list[str]]:
    """Maps resolved /dev/videoN -> list of symlinks in `directory`."""
    out: dict[str, list[str]] = {}
    if not directory.is_dir():
        return out
    for link in sorted(directory.iterdir()):
        try:
            target = os.path.realpath(link)
        except OSError:
            continue
        out.setdefault(os.path.basename(target), []).append(str(link))
    return out


def _holders(dev_name: str, proc_root: Path) -> list[str]:
    holders = []
    try:
        pids = [p for p in proc_root.iterdir() if p.name.isdigit()]
    except OSError:
        return holders
    for pid in pids:
        fd_dir = pid / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue  # other users' processes are not readable; that's fine
        for fd in fds:
            try:
                if os.path.basename(os.readlink(fd)) == dev_name and "video" in dev_name:
                    comm = _read(pid / "comm") or "?"
                    holders.append(f"{pid.name}:{comm}")
                    break
            except OSError:
                continue
    return holders


def _usb_info(video_sysfs: Path) -> UsbInfo | None:
    """Walks up from /sys/class/video4linux/videoN/device (a USB interface) to the USB device."""
    device = video_sysfs / "device"
    try:
        current = Path(os.path.realpath(device))
    except OSError:
        return None
    for candidate in (current, *current.parents):
        if (candidate / "idVendor").exists():
            return UsbInfo(
                sysfs_path=str(candidate),
                vendor_id=_read(candidate / "idVendor"),
                product_id=_read(candidate / "idProduct"),
                manufacturer=_read(candidate / "manufacturer"),
                product=_read(candidate / "product"),
                serial=_read(candidate / "serial"),
                bus_port=candidate.name,
                speed_mbps=_read(candidate / "speed"),
            )
        if candidate == candidate.parent or candidate.name == "devices":
            break
    return None


def discover(
    sysfs_root: str | Path = "/sys/class/video4linux",
    dev_root: str | Path = "/dev",
    proc_root: str | Path = "/proc",
    prober: Prober = probe_node,
) -> list[PhysicalCamera]:
    """Enumerates video nodes and groups them into physical cameras."""
    sysfs_root, dev_root, proc_root = Path(sysfs_root), Path(dev_root), Path(proc_root)
    if not sysfs_root.is_dir():
        return []
    by_id = _symlink_map(dev_root / "v4l" / "by-id")
    by_path = _symlink_map(dev_root / "v4l" / "by-path")

    groups: dict[str, PhysicalCamera] = {}
    entries = sorted(
        (p for p in sysfs_root.iterdir() if p.name.startswith("video")),
        key=lambda p: int(p.name[5:]) if p.name[5:].isdigit() else 1 << 30,
    )
    for entry in entries:
        dev_path = str(dev_root / entry.name)
        index_text = _read(entry / "index")
        node = VideoNode(
            path=dev_path,
            name=_read(entry / "name") or entry.name,
            index=int(index_text) if index_text and index_text.isdigit() else 0,
            by_id=by_id.get(entry.name, []),
            by_path=by_path.get(entry.name, []),
            probe=prober(dev_path),
            holders=_holders(entry.name, proc_root),
        )
        usb = _usb_info(entry)
        key = usb.sysfs_path if usb else dev_path
        camera = groups.get(key)
        if camera is None:
            name = (usb.product if usb and usb.product else None) or node.name
            camera = groups[key] = PhysicalCamera(name=name, usb=usb, nodes=[])
        camera.nodes.append(node)
    return list(groups.values())


def find_camera(cameras: list[PhysicalCamera], device: str) -> PhysicalCamera | None:
    """Finds the camera a configured device path (stable link or /dev/videoN) refers to."""
    target = os.path.basename(os.path.realpath(device))
    for camera in cameras:
        for node in camera.nodes:
            if os.path.basename(node.path) == target or device in node.by_id + node.by_path:
                return camera
    return None


def format_report(cameras: list[PhysicalCamera], show_modes: bool = True) -> str:
    """Human-readable discovery report for `sight-diag list`."""
    if not cameras:
        return "No V4L2 video devices found (is the camera plugged in? see `ls /dev/video*`)."
    lines = []
    for number, camera in enumerate(cameras, 1):
        mark = "  <- Arducam/OV9281 candidate" if camera.is_candidate else ""
        lines.append(f"[{number}] {camera.name}{mark}")
        if camera.usb:
            u = camera.usb
            lines.append(
                f"    USB {u.vendor_id}:{u.product_id}  port {u.bus_port}  "
                f"serial {u.serial or '(none)'}  speed {u.speed_mbps or '?'} Mb/s"
            )
        lines.append(f"    status: {camera.status}")
        lines.append(f"    config device: {camera.stable_path or '-'}")
        for node in camera.nodes:
            lines.append(f"    {node.path}  [{node.kind}]")
            for link in node.by_path + node.by_id:
                lines.append(f"        {link}")
            if node.probe.error:
                lines.append(f"        error: {node.probe.error}")
        node = camera.capture_node
        if show_modes and node and node.probe.modes:
            lines.append("    modes:")
            for fourcc in sorted({m.fourcc for m in node.probe.modes}):
                by_size: dict[tuple[int, int], list[float]] = {}
                for m in node.probe.modes:
                    if m.fourcc == fourcc:
                        by_size.setdefault((m.width, m.height), []).append(m.fps)
                for (w, h), rates in sorted(by_size.items(), key=lambda kv: -kv[0][0] * kv[0][1]):
                    fps = ", ".join(f"{r:g}" for r in sorted(rates, reverse=True))
                    lines.append(f"      {fourcc} {w}x{h}: {fps} fps")
        if node and node.probe.controls:
            names = ", ".join(sorted(node.probe.controls))
            lines.append(f"    controls: {names}")
    serials = [c.usb.serial for c in cameras if c.usb and c.is_candidate]
    if len(serials) >= 2 and len(set(serials)) < len(serials):
        lines.append(
            "\nNote: candidate cameras share a USB serial; use the /dev/v4l/by-path device "
            "(tied to the USB port) and keep each camera in the same port."
        )
    return "\n".join(lines)
