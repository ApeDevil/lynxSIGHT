"""One capture thread per camera: open, read, timestamp, publish, reconnect.

Cameras never wait for each other or for processing: each worker publishes into its own
`FrameSlot` and goes straight back to reading the next frame.
"""

from __future__ import annotations

import enum
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .frames import Frame, FrameSlot, freeze
from .sources import CameraError, EndOfStream, FrameSource
from .stats import RateMeter


class State(enum.Enum):
    STOPPED = "stopped"
    OPENING = "opening"
    RUNNING = "running"
    ERROR = "error"  # failed; retrying if auto_reconnect
    ENDED = "ended"  # replay finished


@dataclass
class FrameTiming:
    """Per-frame timing record handed to observers (e.g. the experiment recorder)."""

    camera_id: str
    seq: int
    t_capture_ns: int
    t_device_ms: float | None
    interval_ms: float | None
    est_dropped: int
    read_ms: float  # time spent inside source.read(): waiting for + decoding the frame


@dataclass
class CaptureStatus:
    camera_id: str
    state: State
    description: str
    negotiated: str
    fps: float
    frames: int
    est_dropped: int
    interval_p50_ms: float
    interval_p95_ms: float
    driver_latency_ms: float | None  # host receive time minus driver timestamp
    reconnects: int
    error: str | None


FrameObserver = Callable[[Frame, FrameTiming], None]


class CaptureWorker:
    def __init__(
        self,
        camera_id: str,
        source: FrameSource,
        slot: FrameSlot | None = None,
        auto_reconnect: bool = True,
        reconnect_delay_s: float = 1.0,
    ):
        self.camera_id = camera_id
        self.source = source
        self.slot = slot or FrameSlot(camera_id)
        self.auto_reconnect = auto_reconnect
        self.reconnect_delay_s = reconnect_delay_s
        self.meter = RateMeter()
        self.observers: list[FrameObserver] = []
        self.state = State.STOPPED
        self.error: str | None = None
        self.reconnects = 0
        self._driver_latency_ms: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seq = 0

    # -- lifecycle ------------------------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"capture-{self.camera_id}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        self._thread = None
        self.state = State.STOPPED

    def restart(self) -> None:
        """Stops, closes and reopens the device (the "reconnect" action)."""
        self.stop()
        self.reconnects += 1
        self.start()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- loop -----------------------------------------------------------------------------------

    def _open(self) -> bool:
        self.state = State.OPENING
        try:
            self.source.open()
        except CameraError as exc:
            self._fail(str(exc))
            return False
        self.meter.reset()
        self._seq = 0
        self.state = State.RUNNING
        self.error = None
        return True

    def _fail(self, message: str) -> None:
        self.state = State.ERROR
        self.error = message
        try:
            self.source.close()
        except Exception:  # noqa: BLE001 - closing a broken device must not mask the error
            pass

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if self.state is not State.RUNNING and not self._open():
                    if not self.auto_reconnect or self._stop.wait(self.reconnect_delay_s):
                        return
                    self.reconnects += 1
                    continue
                t0 = time.monotonic_ns()
                try:
                    image, t_device_ms = self.source.read()
                except EndOfStream as exc:
                    self.state = State.ENDED
                    self.error = str(exc)
                    return
                except CameraError as exc:
                    self._fail(str(exc))
                    continue
                t_capture_ns = time.monotonic_ns()
                self._deliver(freeze(image), t_capture_ns, t_device_ms, (t_capture_ns - t0) / 1e6)
        finally:
            if self.state is not State.ENDED:
                self.state = State.STOPPED if self._stop.is_set() else self.state
            try:
                self.source.close()
            except Exception:  # noqa: BLE001
                pass

    def _deliver(self, image, t_capture_ns: int, t_device_ms: float | None, read_ms: float) -> None:
        self._seq += 1
        # Prefer the driver timestamp for rate/drop statistics: it is not disturbed by
        # host scheduling. Treat it as unusable if it is not on the host's monotonic clock.
        host_ms = t_capture_ns / 1e6
        usable = t_device_ms is not None and 0 <= host_ms - t_device_ms < 10_000
        self._driver_latency_ms = host_ms - t_device_ms if usable else None
        interval, dropped = self.meter.add(t_device_ms if usable else host_ms)
        frame = Frame(
            camera_id=self.camera_id,
            seq=self._seq,
            t_capture_ns=t_capture_ns,
            t_device_ms=t_device_ms,
            image=image,
            source_format=self.source.negotiated,
        )
        self.slot.publish(frame)
        timing = FrameTiming(
            self.camera_id, self._seq, t_capture_ns, t_device_ms, interval, dropped, read_ms
        )
        for observer in list(self.observers):
            try:
                observer(frame, timing)
            except Exception:  # noqa: BLE001 - an observer must never stop capture
                pass

    def status(self) -> CaptureStatus:
        summary = self.meter.interval_summary()
        return CaptureStatus(
            camera_id=self.camera_id,
            state=self.state,
            description=self.source.description,
            negotiated=self.source.negotiated,
            fps=self.meter.fps,
            frames=self.meter.total_frames,
            est_dropped=self.meter.total_dropped,
            interval_p50_ms=summary.p50,
            interval_p95_ms=summary.p95,
            driver_latency_ms=self._driver_latency_ms,
            reconnects=self.reconnects,
            error=self.error,
        )
