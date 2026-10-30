"""Frame sources: real V4L2 cameras, a synthetic generator and recorded-data replay.

Every source delivers 2-D uint8 images (the OV9281 is monochrome) plus an optional driver
timestamp, and exposes its controls through the same `Controls` interface, so the rest of the
application cannot tell them apart. The synthetic source exists to exercise the software without
hardware; it says nothing about how the real cameras behave.
"""

from __future__ import annotations

import csv
import errno
import math
import os
import threading
import time
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from . import v4l2
from .config import CaptureSettings

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".pgm")


class CameraError(RuntimeError):
    """A camera could not be opened or stopped delivering frames."""


class EndOfStream(CameraError):
    pass


class Controls(Protocol):
    def available(self) -> dict[str, v4l2.ControlInfo]: ...
    def get(self, key: str) -> int | None: ...
    def set(self, key: str, value: int) -> int: ...


class FrameSource(Protocol):
    description: str
    negotiated: str  # what the device actually delivers after opening
    controls: Controls | None

    def open(self) -> None: ...
    def read(self) -> tuple[np.ndarray, float | None]: ...
    def close(self) -> None: ...


def to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.shape[2] == 1:
        return image[:, :, 0]
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


# --- controls ----------------------------------------------------------------------------------

# Applied first: manual exposure values are ignored while auto exposure is on.
_CONTROL_ORDER = ("auto_exposure", "exposure_auto", "exposure_dynamic_framerate")


def ordered_controls(values: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(values.items(), key=lambda kv: (kv[0] not in _CONTROL_ORDER, kv[0]))


class V4L2Controls:
    """Reads and writes controls through a separate file handle on the same device node.

    V4L2 allows several handles; controls are per device, so this works while OpenCV streams.
    """

    def __init__(self, device: str):
        self._fd = v4l2.open_device(device)
        self._info = v4l2.query_controls(self._fd)
        self._lock = threading.Lock()

    def available(self) -> dict[str, v4l2.ControlInfo]:
        return dict(self._info)

    def get(self, key: str) -> int | None:
        info = self._info.get(key)
        if info is None:
            return None
        with self._lock:
            try:
                return v4l2.get_control(self._fd, info.id)
            except OSError:
                return None

    def set(self, key: str, value: int) -> int:
        info = self._info.get(key)
        if info is None:
            raise KeyError(
                f"control {key!r} not supported; available: {', '.join(sorted(self._info))}"
            )
        value = int(min(max(value, info.minimum), info.maximum))
        with self._lock:
            v4l2.set_control(self._fd, info.id, value)
            try:
                return v4l2.get_control(self._fd, info.id)
            except OSError:
                return value

    def close(self) -> None:
        os.close(self._fd)


class SimulatedControls:
    """Exposure/gain controls for the synthetic source, shaped like the UVC ones."""

    def __init__(self):
        self._info = {
            "auto_exposure": v4l2.ControlInfo(
                1,
                "auto_exposure",
                "Auto Exposure",
                "menu",
                1,
                3,
                1,
                3,
                0,
                {1: "Manual Mode", 3: "Aperture Priority Mode"},
            ),
            "exposure_time_absolute": v4l2.ControlInfo(
                2,
                "exposure_time_absolute",
                "Exposure Time, Absolute",
                "int",
                1,
                5000,
                1,
                150,
                0,
                {},
            ),
            "gain": v4l2.ControlInfo(3, "gain", "Gain", "int", 0, 100, 1, 0, 0, {}),
        }
        self.values = {k: c.default for k, c in self._info.items()}

    def available(self) -> dict[str, v4l2.ControlInfo]:
        return dict(self._info)

    def get(self, key: str) -> int | None:
        return self.values.get(key)

    def set(self, key: str, value: int) -> int:
        info = self._info[key]
        self.values[key] = int(min(max(value, info.minimum), info.maximum))
        return self.values[key]

    @property
    def brightness_factor(self) -> float:
        if self.values["auto_exposure"] != 1:
            return 1.0
        return (self.values["exposure_time_absolute"] / 150.0) * (1 + self.values["gain"] / 25.0)


# --- V4L2 camera -------------------------------------------------------------------------------


def diagnose_open_failure(device: str) -> str:
    """Explains why OpenCV could not open `device`, which OpenCV itself does not report."""
    if not os.path.exists(device):
        return f"{device} does not exist (unplugged, or a different USB port for a by-path link?)"
    try:
        fd = v4l2.open_device(device)
    except OSError as exc:
        if exc.errno == errno.EACCES:
            return (
                f"{device}: permission denied; add your user to the 'video' group and log in again"
            )
        return f"{device}: {os.strerror(exc.errno or 0)}"
    try:
        cap = v4l2.query_capability(fd)
        if not cap.is_video_capture:
            return f"{device} is not a video-capture node (metadata node?); pick the capture node"
        if v4l2.is_streaming_elsewhere(fd):
            return f"{device} is busy: another process is streaming from it"
    except OSError as exc:
        return f"{device}: ioctl failed ({os.strerror(exc.errno or 0)})"
    finally:
        os.close(fd)
    return f"{device}: OpenCV could not open it (unsupported format?)"


class V4L2Source:
    def __init__(self, device: str, settings: CaptureSettings):
        self.device = device
        self.settings = settings
        self.description = device
        self.negotiated = "-"
        self.controls: V4L2Controls | None = None
        self.control_errors: dict[str, str] = {}
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            raise CameraError(diagnose_open_failure(self.device))
        s = self.settings
        # Order matters for the V4L2 backend: format first, then size, then rate.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*s.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, s.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, s.height)
        cap.set(cv2.CAP_PROP_FPS, s.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, s.buffer_size)
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        self.negotiated = (
            f"{v4l2.fourcc_to_str(fourcc) if fourcc else '?'} "
            f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
            f"@{cap.get(cv2.CAP_PROP_FPS):g}"
        )
        self._cap = cap
        try:
            self.controls = V4L2Controls(self.device)
        except OSError as exc:
            self.controls = None
            self.control_errors["*"] = os.strerror(exc.errno or 0)
        if self.controls:
            for key, value in ordered_controls(s.controls):
                try:
                    self.controls.set(key, value)
                except (KeyError, OSError) as exc:
                    self.control_errors[key] = str(exc)

    def read(self) -> tuple[np.ndarray, float | None]:
        if self._cap is None:
            raise CameraError("not open")
        ok, image = self._cap.read()
        if not ok or image is None:
            raise CameraError(f"{self.device}: no frame (disconnected or stalled)")
        t_device = self._cap.get(cv2.CAP_PROP_POS_MSEC)
        return to_gray(image), (t_device if t_device > 0 else None)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self.controls is not None:
            self.controls.close()
            self.controls = None


# --- synthetic ---------------------------------------------------------------------------------


class SyntheticSource:
    """Deterministic moving test pattern at a paced frame rate.

    The pattern (gradient, focus target, two dark discs moving like pupils) exercises capture,
    timing, image-quality metrics, recording and the UI. It contains no face, so face and eye
    pipelines correctly report "no face" on it.
    `drop_every` skips that many-th frame to test drop estimation.
    """

    def __init__(
        self, camera_id: str, settings: CaptureSettings, drop_every: int = 0, paced: bool = True
    ):
        self.camera_id = camera_id
        self.settings = settings
        self.description = f"synthetic:{camera_id}"
        self.negotiated = "-"
        self.controls = SimulatedControls()
        for key, value in ordered_controls(settings.controls):
            if key in self.controls.available():
                self.controls.set(key, value)
        self.drop_every = drop_every
        self.paced = paced
        self._n = 0
        self._t0 = 0.0
        self._base: np.ndarray | None = None

    def open(self) -> None:
        w, h = self.settings.width, self.settings.height
        self.negotiated = f"SYNTH {w}x{h}@{self.settings.fps:g}"
        y, x = np.mgrid[0:h, 0:w]
        base = (60 + 80 * x / max(w - 1, 1) + 40 * y / max(h - 1, 1)).astype(np.float32)
        # Siemens-star style focus target in the corner: a sharpness reference for the metrics.
        cy, cx, r = h // 5, w // 6, min(w, h) // 8
        ang = np.arctan2(y - cy, x - cx)
        star = (np.hypot(y - cy, x - cx) < r) & (np.sin(ang * 18) > 0)
        base[star] = 20
        self._base = base
        self._n = 0
        self._t0 = time.monotonic()

    def read(self) -> tuple[np.ndarray, float | None]:
        if self._base is None:
            raise CameraError("not open")
        period = 1.0 / self.settings.fps
        self._n += 1
        if self.drop_every and self._n % self.drop_every == 0:
            self._n += 1
        due = self._t0 + self._n * period
        if self.paced:
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        img = self._base * self.controls.brightness_factor
        h, w = img.shape
        phase = self._n * period
        offset = 10 if self.camera_id == "cam_right" else -10  # crude parallax between cameras
        for k, ex in enumerate((0.4, 0.6)):
            cx = int(w * ex + offset + 15 * math.sin(phase * 1.3))
            cy = int(h * 0.45 + 8 * math.cos(phase * 0.9))
            cv2.ellipse(img, (cx, cy), (w // 18, h // 30), 0, 0, 360, 200, -1)
            cv2.circle(img, (cx + int(6 * math.sin(phase * 2 + k)), cy), h // 60, 25, -1)
        img = np.clip(img, 0, 255).astype(np.uint8)
        cv2.putText(
            img, f"{self.camera_id} #{self._n}", (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 255, 2
        )
        return img, due * 1000.0

    def close(self) -> None:
        self._base = None


# --- replay ------------------------------------------------------------------------------------


class ReplaySource:
    """Replays a recording made by `sight-diag record --raw` (video + timestamps CSV), any video
    file, or a directory of still images. With `paced`, the original timing is reproduced."""

    def __init__(self, path: str, paced: bool = True, loop: bool = False, fps: float = 30.0):
        self.path = Path(path)
        self.description = f"replay:{self.path.name}"
        self.negotiated = "-"
        self.controls = None
        self.paced = paced
        self.loop = loop
        self.fps = fps
        self._cap: cv2.VideoCapture | None = None
        self._images: list[Path] = []
        self._stamps: list[float] = []
        self._i = 0
        self._last_rel_ms = 0.0
        self._due: float | None = None  # monotonic time the next frame is due (pacing)

    def open(self) -> None:
        self._i = 0
        if self.path.is_dir():
            self._images = sorted(
                p for p in self.path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES
            )
            if not self._images:
                raise CameraError(f"{self.path}: no images")
            first = cv2.imread(str(self._images[0]), cv2.IMREAD_GRAYSCALE)
            self.negotiated = f"IMAGES {first.shape[1]}x{first.shape[0]} x{len(self._images)}"
            return
        if not self.path.exists():
            raise CameraError(f"{self.path}: not found")
        self._cap = cv2.VideoCapture(str(self.path))
        if not self._cap.isOpened():
            raise CameraError(f"{self.path}: cannot decode")
        self.fps = self._cap.get(cv2.CAP_PROP_FPS) or self.fps
        stamps = self.path.with_suffix(".timestamps.csv")
        if stamps.exists():
            with stamps.open() as fh:
                self._stamps = [int(row["t_capture_ns"]) / 1e6 for row in csv.DictReader(fh)]
        self.negotiated = (
            f"FILE {int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
            f"{int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}@{self.fps:g}"
        )

    def _recorded_ms(self, i: int) -> float:
        if i < len(self._stamps):
            return self._stamps[i] - self._stamps[0]
        return i * 1000.0 / self.fps

    def read(self) -> tuple[np.ndarray, float | None]:
        if self._images:
            if self._i >= len(self._images):
                if not self.loop:
                    raise EndOfStream("end of images")
                self.open()
            image = cv2.imread(str(self._images[self._i]), cv2.IMREAD_GRAYSCALE)
        else:
            if self._cap is None:
                raise CameraError("not open")
            ok, image = self._cap.read()
            if not ok:
                if not self.loop:
                    raise EndOfStream("end of recording")
                self._cap.release()
                self.open()
                ok, image = self._cap.read()
                if not ok:
                    raise EndOfStream("empty recording")
        rel_ms = self._recorded_ms(self._i)
        if self._i > 0:
            step_ms = rel_ms - self._last_rel_ms
        else:  # first frame, or the first again after looping
            step_ms = 0.0 if self._due is None else 1000.0 / self.fps
        self._last_rel_ms = rel_ms
        self._i += 1
        self._due = (self._due or time.monotonic()) + step_ms / 1000.0
        if self.paced:
            delay = self._due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        return to_gray(image), None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._images = []
        self._due = None


def make_source(camera_id: str, device: str, settings: CaptureSettings) -> FrameSource:
    """`synthetic` -> generator; an existing file/directory -> replay (a directory of stills
    loops, so it can be inspected live); anything else -> V4L2."""
    if device == "synthetic":
        return SyntheticSource(camera_id, settings)
    if not device.startswith("/dev/") and os.path.exists(device):
        return ReplaySource(device, loop=os.path.isdir(device), fps=settings.fps)
    return V4L2Source(device, settings)
