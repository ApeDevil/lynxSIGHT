"""Minimal V4L2 ioctl bindings: device capabilities, formats, frame sizes/intervals and controls.

Only the handful of read-mostly ioctls the diagnostic needs are bound, using the struct layouts
of <linux/videodev2.h>. Packing and unpacking are pure functions so they are testable without a
video device; the `query_*`/`*_control` functions perform the actual ioctls on an open fd.
"""

from __future__ import annotations

import errno
import fcntl
import os
import struct
from dataclasses import dataclass
from fractions import Fraction

# --- ioctl request numbers (asm-generic/ioctl.h encoding) -------------------------------------

_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("V") << 8) | nr


_CAPABILITY = struct.Struct("=16s32s32sIII12x")  # struct v4l2_capability (104 bytes)
_FMTDESC = struct.Struct("=III32sII12x")  # struct v4l2_fmtdesc (64 bytes)
_FRMSIZE = struct.Struct("=III6I8x")  # struct v4l2_frmsizeenum (44 bytes)
_FRMIVAL = struct.Struct("=IIIII6I8x")  # struct v4l2_frmivalenum (52 bytes)
_QUERYCTRL = struct.Struct("=II32siiiiI8x")  # struct v4l2_queryctrl (68 bytes)
_QUERYMENU = struct.Struct("=II32s4x")  # struct v4l2_querymenu (44 bytes), name variant
_CONTROL = struct.Struct("=Ii")  # struct v4l2_control (8 bytes)
_REQBUFS = struct.Struct("=IIIIB3x")  # struct v4l2_requestbuffers (20 bytes)

VIDIOC_QUERYCAP = _ioc(_IOC_READ, 0, _CAPABILITY.size)
VIDIOC_ENUM_FMT = _ioc(_IOC_READ | _IOC_WRITE, 2, _FMTDESC.size)
VIDIOC_REQBUFS = _ioc(_IOC_READ | _IOC_WRITE, 8, _REQBUFS.size)
VIDIOC_G_CTRL = _ioc(_IOC_READ | _IOC_WRITE, 27, _CONTROL.size)
VIDIOC_S_CTRL = _ioc(_IOC_READ | _IOC_WRITE, 28, _CONTROL.size)
VIDIOC_QUERYCTRL = _ioc(_IOC_READ | _IOC_WRITE, 36, _QUERYCTRL.size)
VIDIOC_QUERYMENU = _ioc(_IOC_READ | _IOC_WRITE, 37, _QUERYMENU.size)
VIDIOC_ENUM_FRAMESIZES = _ioc(_IOC_READ | _IOC_WRITE, 74, _FRMSIZE.size)
VIDIOC_ENUM_FRAMEINTERVALS = _ioc(_IOC_READ | _IOC_WRITE, 75, _FRMIVAL.size)

# --- constants ---------------------------------------------------------------------------------

V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_VIDEO_CAPTURE_MPLANE = 0x00001000
V4L2_CAP_META_CAPTURE = 0x00800000
V4L2_CAP_STREAMING = 0x04000000
V4L2_CAP_DEVICE_CAPS = 0x80000000

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1

V4L2_FRMSIZE_TYPE_DISCRETE = 1
V4L2_FRMIVAL_TYPE_DISCRETE = 1

V4L2_CTRL_FLAG_DISABLED = 0x0001
V4L2_CTRL_FLAG_NEXT_CTRL = 0x80000000
V4L2_CTRL_TYPE_MENU = 3
V4L2_CTRL_TYPE_CTRL_CLASS = 6

CTRL_TYPE_NAMES = {1: "int", 2: "bool", 3: "menu", 4: "button", 5: "int64", 9: "intmenu"}


def fourcc_to_str(code: int) -> str:
    return code.to_bytes(4, "little").decode("ascii", errors="replace")


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def control_key(name: str) -> str:
    """Normalise a V4L2 control name the way v4l2-ctl does: 'Exposure Time, Absolute' ->
    'exposure_time_absolute'."""
    out = []
    for ch in name.lower():
        out.append(ch if ch.isalnum() else "_")
    key = "".join(out)
    while "__" in key:
        key = key.replace("__", "_")
    return key.strip("_")


# --- data --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Capability:
    driver: str
    card: str
    bus_info: str
    capabilities: int
    device_caps: int

    @property
    def node_caps(self) -> int:
        """Capabilities of this particular node (device_caps), falling back to the
        whole-device capabilities on very old drivers."""
        if self.capabilities & V4L2_CAP_DEVICE_CAPS:
            return self.device_caps
        return self.capabilities

    @property
    def is_video_capture(self) -> bool:
        return bool(self.node_caps & (V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_VIDEO_CAPTURE_MPLANE))

    @property
    def is_metadata(self) -> bool:
        return bool(self.node_caps & V4L2_CAP_META_CAPTURE) and not self.is_video_capture


@dataclass(frozen=True)
class FrameMode:
    """One capture mode a device advertises: pixel format, size and a frame rate."""

    fourcc: str
    width: int
    height: int
    fps: float

    def __str__(self) -> str:
        return f"{self.fourcc} {self.width}x{self.height}@{self.fps:g}"


@dataclass(frozen=True)
class ControlInfo:
    id: int
    key: str
    name: str
    type: str
    minimum: int
    maximum: int
    step: int
    default: int
    flags: int
    menu: dict[int, str]


# --- pure (un)packing --------------------------------------------------------------------------


def unpack_capability(buf: bytes) -> Capability:
    driver, card, bus, _version, caps, dcaps = _CAPABILITY.unpack(buf)
    return Capability(_cstr(driver), _cstr(card), _cstr(bus), caps, dcaps)


def unpack_fmtdesc(buf: bytes) -> tuple[str, str]:
    """Returns (fourcc, description)."""
    _index, _type, _flags, desc, pixfmt, _mbus = _FMTDESC.unpack(buf)
    return fourcc_to_str(pixfmt), _cstr(desc)


def unpack_frmsize(buf: bytes) -> tuple[int, tuple[int, ...]]:
    """Returns (type, union words). For discrete sizes the first two words are width, height."""
    _index, _pixfmt, kind, *words = _FRMSIZE.unpack(buf)
    return kind, tuple(words)


def unpack_frmival(buf: bytes) -> tuple[int, tuple[int, ...]]:
    """Returns (type, union words). For discrete intervals the first two words are the
    interval numerator and denominator (seconds per frame)."""
    _index, _pixfmt, _w, _h, kind, *words = _FRMIVAL.unpack(buf)
    return kind, tuple(words)


def interval_to_fps(numerator: int, denominator: int) -> float:
    if numerator == 0:
        return 0.0
    return float(Fraction(denominator, numerator))


# --- ioctls ------------------------------------------------------------------------------------


def open_device(path: str) -> int:
    """Opens a V4L2 node without blocking. Raises OSError (EACCES, ENOENT, ...)."""
    return os.open(path, os.O_RDWR | os.O_NONBLOCK)


def query_capability(fd: int) -> Capability:
    buf = bytearray(_CAPABILITY.size)
    fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
    return unpack_capability(bytes(buf))


def _enumerate(fd: int, request: int, pack) -> list[bytes]:
    out = []
    index = 0
    while True:
        buf = bytearray(pack(index))
        try:
            fcntl.ioctl(fd, request, buf)
        except OSError as exc:
            if exc.errno == errno.EINVAL:
                return out
            raise
        out.append(bytes(buf))
        index += 1
        if index > 4096:  # defensive: a broken driver must not hang discovery
            return out


def query_formats(fd: int) -> list[tuple[str, str, int]]:
    """Returns [(fourcc, description, raw pixelformat code)] for VIDEO_CAPTURE buffers."""
    raw = _enumerate(
        fd,
        VIDIOC_ENUM_FMT,
        lambda i: _FMTDESC.pack(i, V4L2_BUF_TYPE_VIDEO_CAPTURE, 0, b"", 0, 0),
    )
    out = []
    for buf in raw:
        fourcc, desc = unpack_fmtdesc(buf)
        out.append((fourcc, desc, _FMTDESC.unpack(buf)[4]))
    return out


def query_modes(fd: int) -> list[FrameMode]:
    """All discrete (fourcc, size, fps) combinations the node advertises. Stepwise/continuous
    ranges are reported only by their minimum and maximum, which UVC devices rarely use."""
    modes: list[FrameMode] = []
    for fourcc, _desc, code in query_formats(fd):
        sizes = _enumerate(
            fd, VIDIOC_ENUM_FRAMESIZES, lambda i, c=code: _FRMSIZE.pack(i, c, 0, *[0] * 6)
        )
        for sbuf in sizes:
            kind, words = unpack_frmsize(sbuf)
            if kind == V4L2_FRMSIZE_TYPE_DISCRETE:
                dims = [(words[0], words[1])]
            else:  # stepwise/continuous: min_w, max_w, step_w, min_h, max_h, step_h
                dims = [(words[0], words[3]), (words[1], words[4])]
            for w, h in dims:
                ivals = _enumerate(
                    fd,
                    VIDIOC_ENUM_FRAMEINTERVALS,
                    lambda i, c=code, w=w, h=h: _FRMIVAL.pack(i, c, w, h, 0, *[0] * 6),
                )
                for ibuf in ivals:
                    ikind, iw = unpack_frmival(ibuf)
                    fractions = (
                        [(iw[0], iw[1])]
                        if ikind == V4L2_FRMIVAL_TYPE_DISCRETE
                        else [(iw[0], iw[1]), (iw[2], iw[3])]
                    )
                    for num, den in fractions:
                        modes.append(FrameMode(fourcc, w, h, round(interval_to_fps(num, den), 3)))
    return sorted(set(modes), key=lambda m: (m.fourcc, -m.width * m.height, -m.fps))


def query_controls(fd: int) -> dict[str, ControlInfo]:
    """Enumerates user/camera controls (exposure, gain, ...) keyed by normalised name."""
    controls: dict[str, ControlInfo] = {}
    next_id = V4L2_CTRL_FLAG_NEXT_CTRL
    for _ in range(1024):
        buf = bytearray(_QUERYCTRL.pack(next_id, 0, b"", 0, 0, 0, 0, 0))
        try:
            fcntl.ioctl(fd, VIDIOC_QUERYCTRL, buf)
        except OSError as exc:
            if exc.errno == errno.EINVAL:
                break
            raise
        cid, ctype, name, lo, hi, step, default, flags = _QUERYCTRL.unpack(bytes(buf))
        next_id = cid | V4L2_CTRL_FLAG_NEXT_CTRL
        if ctype == V4L2_CTRL_TYPE_CTRL_CLASS or flags & V4L2_CTRL_FLAG_DISABLED:
            continue
        menu = _query_menu(fd, cid, lo, hi) if ctype == V4L2_CTRL_TYPE_MENU else {}
        text = _cstr(name)
        key = control_key(text)
        controls[key] = ControlInfo(
            cid,
            key,
            text,
            CTRL_TYPE_NAMES.get(ctype, str(ctype)),
            lo,
            hi,
            step,
            default,
            flags,
            menu,
        )
    return controls


def _query_menu(fd: int, cid: int, lo: int, hi: int) -> dict[int, str]:
    items = {}
    for index in range(max(lo, 0), min(hi, 64) + 1):
        buf = bytearray(_QUERYMENU.pack(cid, index, b""))
        try:
            fcntl.ioctl(fd, VIDIOC_QUERYMENU, buf)
        except OSError:
            continue
        items[index] = _cstr(_QUERYMENU.unpack(bytes(buf))[2])
    return items


def get_control(fd: int, cid: int) -> int:
    buf = bytearray(_CONTROL.pack(cid, 0))
    fcntl.ioctl(fd, VIDIOC_G_CTRL, buf)
    return _CONTROL.unpack(bytes(buf))[1]


def set_control(fd: int, cid: int, value: int) -> None:
    fcntl.ioctl(fd, VIDIOC_S_CTRL, bytearray(_CONTROL.pack(cid, int(value))))


def is_streaming_elsewhere(fd: int) -> bool:
    """True if another file handle owns the capture queue (i.e. some process is streaming).

    REQBUFS with count=0 releases nothing we own and returns EBUSY when the queue belongs to
    another handle, both for the vb2 helpers and the UVC driver's privilege model.
    """
    buf = bytearray(_REQBUFS.pack(0, V4L2_BUF_TYPE_VIDEO_CAPTURE, V4L2_MEMORY_MMAP, 0, 0))
    try:
        fcntl.ioctl(fd, VIDIOC_REQBUFS, buf)
    except OSError as exc:
        if exc.errno == errno.EBUSY:
            return True
        raise
    return False
