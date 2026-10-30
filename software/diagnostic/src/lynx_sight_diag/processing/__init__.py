"""Processing framework: many independent functions sharing each captured frame.

A `Processor` is a plain object with a `process()` method. Each (camera, processor) pair runs in
its own `ProcessorRunner` thread that:

* takes frames from the camera's `FrameSlot` (or, for a downstream processor such as `eyes`,
  results of its upstream processor, which carry the frame they were computed on),
* processes only the newest input and skips the rest, at most `max_hz` times per second,
* records latency (capture -> result) and compute time,
* catches every exception, reports it, backs off, and keeps going.

So a slow or crashing function never stalls capture or any other function. Latest results are
published on a `ResultBoard` for the UI and the recorder.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..frames import Frame, FrameSlot
from ..stats import Summary


@dataclass(frozen=True)
class Result:
    processor: str
    camera_id: str
    frame: Frame
    t_done_ns: int
    compute_ms: float
    data: Any = None  # processor-specific payload (a dataclass); None on error
    error: str | None = None

    @property
    def latency_ms(self) -> float:
        """Capture-to-result latency: from the host receiving the frame to the result."""
        return (self.t_done_ns - self.frame.t_capture_ns) / 1e6

    @property
    def ok(self) -> bool:
        return self.error is None


class Processor(Protocol):
    name: str
    # None: consume raw frames. Otherwise the name of the processor whose results trigger this
    # one; `upstream` is then that result (same camera, same frame).
    upstream: str | None

    def process(self, frame: Frame, upstream: Result | None) -> Any: ...


class ProcessorUnavailable(RuntimeError):
    """Raised by a processor that cannot run at all (e.g. a missing model or package)."""


class ResultBoard:
    """Latest result per (camera, processor), with wake-ups for downstream processors."""

    def __init__(self):
        self._cond = threading.Condition()
        self._latest: dict[tuple[str, str], Result] = {}
        self._tokens: dict[tuple[str, str], int] = {}
        self.listeners: list[Callable[[Result], None]] = []

    def publish(self, result: Result) -> None:
        key = (result.camera_id, result.processor)
        with self._cond:
            self._latest[key] = result
            self._tokens[key] = self._tokens.get(key, 0) + 1
            self._cond.notify_all()
        for listener in list(self.listeners):
            try:
                listener(result)
            except Exception:  # noqa: BLE001 - recording/UI hooks must not break processing
                pass

    def latest(self, camera_id: str, processor: str) -> Result | None:
        with self._cond:
            return self._latest.get((camera_id, processor))

    def snapshot(self) -> dict[tuple[str, str], Result]:
        with self._cond:
            return dict(self._latest)

    def wait_newer(self, camera_id: str, processor: str, after_token: int, timeout: float):
        key = (camera_id, processor)
        with self._cond:
            ready = self._cond.wait_for(lambda: self._tokens.get(key, 0) != after_token, timeout)
            if not ready:
                return None
            return self._latest[key], self._tokens[key]


@dataclass
class RunnerStats:
    processed: int = 0
    skipped: int = 0  # inputs that arrived but were superseded before processing
    errors: int = 0
    consecutive_errors: int = 0
    last_error: str | None = None
    unavailable: str | None = None
    latency_ms: deque = field(default_factory=lambda: deque(maxlen=200))
    compute_ms: deque = field(default_factory=lambda: deque(maxlen=200))

    def latency_summary(self) -> Summary:
        return Summary.of(self.latency_ms)

    def compute_summary(self) -> Summary:
        return Summary.of(self.compute_ms)


class ProcessorRunner:
    MAX_BACKOFF_S = 5.0

    def __init__(
        self,
        processor: Processor,
        camera_id: str,
        slot: FrameSlot,
        board: ResultBoard,
        max_hz: float | None = None,
    ):
        self.processor = processor
        self.camera_id = camera_id
        self.slot = slot
        self.board = board
        self.min_period_s = 1.0 / max_hz if max_hz else 0.0
        self.stats = RunnerStats()
        self.enabled = True
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def name(self) -> str:
        return self.processor.name

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"proc-{self.name}-{self.camera_id}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        self._thread = None

    def _next_input(self, token: int) -> tuple[Frame, Result | None, int, int] | None:
        """Returns (frame, upstream result, new token, inputs skipped) or None on timeout."""
        upstream = self.processor.upstream
        if upstream is None:
            got = self.slot.wait_newer(token, timeout=0.2)
            if got is None:
                return None
            frame, new_token = got
            return frame, None, new_token, max(0, new_token - token - 1) if token else 0
        got = self.board.wait_newer(self.camera_id, upstream, token, timeout=0.2)
        if got is None:
            return None
        result, new_token = got
        if not result.ok:
            return None if new_token == token else (result.frame, None, new_token, -1)
        return result.frame, result, new_token, max(0, new_token - token - 1) if token else 0

    def _run(self) -> None:
        token = 0
        next_allowed = 0.0
        while not self._stop.is_set():
            if not self.enabled:
                self._stop.wait(0.1)
                continue
            got = self._next_input(token)
            if got is None:
                continue
            frame, upstream, token, skipped = got
            if skipped < 0:  # upstream failed on this frame: nothing to do
                continue
            self.stats.skipped += skipped
            now = time.monotonic()
            if now < next_allowed:
                self.stats.skipped += 1
                self._stop.wait(next_allowed - now)
                continue
            next_allowed = now + self.min_period_s
            self._process_one(frame, upstream)
            if self.stats.unavailable:
                return

    def _process_one(self, frame: Frame, upstream: Result | None) -> None:
        t0 = time.monotonic_ns()
        try:
            data = self.processor.process(frame, upstream)
            error = None
        except ProcessorUnavailable as exc:
            self.stats.unavailable = str(exc)
            data, error = None, f"unavailable: {exc}"
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            data = None
            error = f"{type(exc).__name__}: {exc}"
            self.stats.last_error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        t1 = time.monotonic_ns()
        result = Result(self.name, self.camera_id, frame, t1, (t1 - t0) / 1e6, data, error)
        if error is None:
            self.stats.processed += 1
            self.stats.consecutive_errors = 0
            self.stats.latency_ms.append(result.latency_ms)
            self.stats.compute_ms.append(result.compute_ms)
        else:
            self.stats.errors += 1
            self.stats.consecutive_errors += 1
        self.board.publish(result)
        if self.stats.consecutive_errors > 1 and not self.stats.unavailable:
            backoff = min(self.MAX_BACKOFF_S, 0.05 * 2 ** min(self.stats.consecutive_errors, 10))
            self._stop.wait(backoff)
