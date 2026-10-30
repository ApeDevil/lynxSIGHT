"""Frames and the per-camera latest-frame slot that fans one capture out to many consumers.

A captured frame is stored once and shared by reference: its pixel array is made read-only so a
processing function cannot corrupt what another one sees. Consumers never queue frames; each asks
for "the newest frame after the one I last saw", so a slow consumer skips frames instead of
accumulating latency, and never slows down capture or other consumers.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Frame:
    camera_id: str
    seq: int  # per-capture-session counter of delivered frames, starting at 1
    t_capture_ns: int  # host time.monotonic_ns() when the frame was handed over by the driver
    t_device_ms: float | None  # driver buffer timestamp (CLOCK_MONOTONIC for UVC), if known
    image: np.ndarray  # 2-D uint8 (the OV9281 is monochrome), read-only
    source_format: str  # what the device delivered, e.g. "MJPG 1280x800"

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    @property
    def width(self) -> int:
        return int(self.image.shape[1])


def freeze(image: np.ndarray) -> np.ndarray:
    image.flags.writeable = False
    return image


class FrameSlot:
    """Holds the newest frame of one camera and wakes waiting consumers."""

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self._cond = threading.Condition()
        self._frame: Frame | None = None
        self._published = 0

    def publish(self, frame: Frame) -> None:
        with self._cond:
            self._frame = frame
            self._published += 1
            self._cond.notify_all()

    def latest(self) -> Frame | None:
        with self._cond:
            return self._frame

    @property
    def published(self) -> int:
        return self._published

    def wait_newer(self, after_token: int, timeout: float) -> tuple[Frame, int] | None:
        """Waits for a frame published after `after_token` and returns (newest frame, its token),
        or None on timeout. Tokens count publications, unlike `Frame.seq` which restarts when a
        camera reconnects; start with token 0."""
        with self._cond:
            ready = self._cond.wait_for(
                lambda: self._published != after_token and self._frame is not None, timeout
            )
            if not ready:
                return None
            assert self._frame is not None
            return self._frame, self._published
