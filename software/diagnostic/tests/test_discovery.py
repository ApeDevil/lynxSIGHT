import os
from pathlib import Path

from lynx_sight_diag import discovery, v4l2

CAPTURE = v4l2.Capability(
    "uvcvideo",
    "Arducam OV9281 USB Camera",
    "usb-1",
    v4l2.V4L2_CAP_DEVICE_CAPS,
    v4l2.V4L2_CAP_VIDEO_CAPTURE | v4l2.V4L2_CAP_STREAMING,
)
META = v4l2.Capability(
    "uvcvideo",
    "Arducam OV9281 USB Camera",
    "usb-1",
    v4l2.V4L2_CAP_DEVICE_CAPS,
    v4l2.V4L2_CAP_META_CAPTURE,
)
MODES = [v4l2.FrameMode("MJPG", 1280, 800, 120.0), v4l2.FrameMode("MJPG", 640, 400, 120.0)]


def build_tree(root: Path, cameras):
    """cameras: list of (usb port, serial, [(videoN, index)]) -> fake sysfs/dev/proc trees."""
    sysfs, dev, proc = root / "sys/class/video4linux", root / "dev", root / "proc"
    devices = root / "sys/devices/pci0000:00/0000:00:14.0/usb1"
    for d in (sysfs, dev / "v4l/by-id", dev / "v4l/by-path", proc):
        d.mkdir(parents=True)
    for port, serial, nodes in cameras:
        usb = devices / port
        iface = usb / f"{port}:1.0"
        iface.mkdir(parents=True)
        for name, value in (
            ("idVendor", "0c45"),
            ("idProduct", "6366"),
            ("product", "Arducam OV9281 USB Camera"),
            ("manufacturer", "Arducam"),
            ("speed", "480"),
            ("serial", serial),
        ):
            if value is not None:
                (usb / name).write_text(value + "\n")
        for video, index in nodes:
            entry = sysfs / video
            entry.mkdir()
            (entry / "name").write_text("Arducam OV9281 USB Camera\n")
            (entry / "index").write_text(f"{index}\n")
            os.symlink(iface, entry / "device")
            (dev / video).touch()
            os.symlink(
                f"../../{video}",
                dev / "v4l/by-path" / f"pci-0000:00:14.0-usb-0:{port[2:]}:1.0-video-index{index}",
            )
            # Identical serials collide in by-id: udev keeps only one link per name.
            link = dev / "v4l/by-id" / f"usb-Arducam_{serial}-video-index{index}"
            if not link.exists():
                os.symlink(f"../../{video}", link)
    return sysfs, dev, proc


def fake_prober(path):
    index = int(path.rsplit("video", 1)[1])
    if index == 4:
        return discovery.NodeProbe(error="permission denied (is your user in the 'video' group?)")
    if index % 2 == 0:
        return discovery.NodeProbe(capability=CAPTURE, modes=MODES, streaming_elsewhere=index == 2)
    return discovery.NodeProbe(capability=META)


def test_groups_nodes_per_usb_device_and_prefers_by_path(tmp_path):
    sysfs, dev, proc = build_tree(
        tmp_path,
        [
            ("1-1", "SN0001", [("video0", 0), ("video1", 1)]),
            ("1-2", "SN0001", [("video2", 0), ("video3", 1)]),
        ],
    )
    cams = discovery.discover(sysfs, dev, proc, prober=fake_prober)
    assert len(cams) == 2
    first, second = cams
    assert [n.kind for n in first.nodes] == ["capture", "metadata"]
    assert first.capture_node.path.endswith("video0")
    assert first.stable_path.endswith("usb-0:1:1.0-video-index0") and "by-path" in first.stable_path
    assert second.stable_path.endswith("usb-0:2:1.0-video-index0")
    assert first.is_candidate and first.usb.bus_port == "1-1" and first.usb.serial == "SN0001"
    assert first.status == "available"
    assert second.status.startswith("busy")
    report = discovery.format_report(cams)
    assert "share a USB serial" in report
    assert "MJPG 1280x800: 120 fps" in report


def test_reports_permission_errors_and_finds_configured_device(tmp_path):
    sysfs, dev, proc = build_tree(tmp_path, [("1-3", None, [("video4", 0), ("video5", 1)])])
    cams = discovery.discover(sysfs, dev, proc, prober=fake_prober)
    assert len(cams) == 1
    camera = cams[0]
    assert camera.capture_node.kind == "capture?"  # inferred from the sysfs index without ioctl
    assert "permission denied" in camera.status
    link = camera.capture_node.by_path[0]
    assert discovery.find_camera(cams, link) is camera
    assert discovery.find_camera(cams, str(dev / "video4")) is camera
    assert discovery.find_camera(cams, "/dev/video99") is None
    assert camera.to_dict()["stable_path"] == link


def test_lists_processes_holding_a_node(tmp_path):
    sysfs, dev, proc = build_tree(tmp_path, [("1-1", "A", [("video0", 0), ("video1", 1)])])
    (proc / "4242/fd").mkdir(parents=True)
    (proc / "4242/comm").write_text("cheese\n")
    os.symlink(dev / "video0", proc / "4242/fd/7")
    cams = discovery.discover(
        sysfs, dev, proc, prober=lambda p: discovery.NodeProbe(capability=CAPTURE)
    )
    assert cams[0].nodes[0].holders == ["4242:cheese"]
    assert "cheese" in cams[0].status


def test_no_sysfs_means_no_cameras(tmp_path):
    assert discovery.discover(tmp_path / "missing", tmp_path, tmp_path) == []
    assert "No V4L2 video devices" in discovery.format_report([])
