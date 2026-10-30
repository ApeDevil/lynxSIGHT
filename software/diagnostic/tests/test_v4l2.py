import struct

from lynx_sight_diag import v4l2


def test_ioctl_numbers_match_linux_headers():
    # Values from <linux/videodev2.h> on x86_64/aarch64.
    assert v4l2.VIDIOC_QUERYCAP == 0x80685600
    assert v4l2.VIDIOC_ENUM_FMT == 0xC0405602
    assert v4l2.VIDIOC_REQBUFS == 0xC0145608
    assert v4l2.VIDIOC_G_CTRL == 0xC008561B
    assert v4l2.VIDIOC_S_CTRL == 0xC008561C
    assert v4l2.VIDIOC_QUERYCTRL == 0xC0445624
    assert v4l2.VIDIOC_QUERYMENU == 0xC02C5625
    assert v4l2.VIDIOC_ENUM_FRAMESIZES == 0xC02C564A
    assert v4l2.VIDIOC_ENUM_FRAMEINTERVALS == 0xC034564B


def _capability(device_caps):
    caps = (
        device_caps
        | v4l2.V4L2_CAP_DEVICE_CAPS
        | v4l2.V4L2_CAP_META_CAPTURE
        | v4l2.V4L2_CAP_VIDEO_CAPTURE
    )
    return struct.pack(
        "=16s32s32sIII12x",
        b"uvcvideo",
        b"Arducam OV9281 USB Camera",
        b"usb-0000:00:14.0-1",
        0x60800,
        caps,
        device_caps,
    )


def test_capture_and_metadata_nodes_are_distinguished():
    capture = v4l2.unpack_capability(
        _capability(v4l2.V4L2_CAP_VIDEO_CAPTURE | v4l2.V4L2_CAP_STREAMING)
    )
    meta = v4l2.unpack_capability(_capability(v4l2.V4L2_CAP_META_CAPTURE | v4l2.V4L2_CAP_STREAMING))
    assert capture.driver == "uvcvideo" and capture.card.startswith("Arducam")
    assert capture.is_video_capture and not capture.is_metadata
    assert meta.is_metadata and not meta.is_video_capture


def test_fmtdesc_and_intervals_decode():
    buf = struct.pack("=III32sII12x", 0, 1, 1, b"Motion-JPEG", int.from_bytes(b"MJPG", "little"), 0)
    assert v4l2.unpack_fmtdesc(buf) == ("MJPG", "Motion-JPEG")
    ival = struct.pack("=IIIII6I8x", 0, 0, 1280, 800, 1, 1, 120, 0, 0, 0, 0)
    kind, words = v4l2.unpack_frmival(ival)
    assert kind == v4l2.V4L2_FRMIVAL_TYPE_DISCRETE
    assert v4l2.interval_to_fps(words[0], words[1]) == 120.0
    assert v4l2.interval_to_fps(1001, 30000) == 29.97002997002997
    assert v4l2.interval_to_fps(0, 0) == 0.0


def test_control_names_normalise_like_v4l2_ctl():
    assert v4l2.control_key("Exposure Time, Absolute") == "exposure_time_absolute"
    assert v4l2.control_key("Auto Exposure") == "auto_exposure"
    assert v4l2.control_key("White Balance Temperature, Auto") == "white_balance_temperature_auto"
