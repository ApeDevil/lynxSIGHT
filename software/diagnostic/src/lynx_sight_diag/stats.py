"""Rolling timing statistics: frame rate, interval jitter, estimated drops, latencies."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (q in 0..100); NaN for empty input."""
    if not values:
        return math.nan
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def estimate_dropped(interval_ms: float, nominal_ms: float) -> int:
    """Frames presumably missed in a gap: 0 for intervals under 1.5x the nominal period."""
    if nominal_ms <= 0 or interval_ms < 1.5 * nominal_ms:
        return 0
    return max(0, round(interval_ms / nominal_ms) - 1)


@dataclass
class Summary:
    count: int
    mean: float
    p50: float
    p95: float
    max: float

    @classmethod
    def of(cls, values: Iterable[float]) -> Summary:
        data = [v for v in values if v is not None and not math.isnan(v)]
        if not data:
            return cls(0, math.nan, math.nan, math.nan, math.nan)
        return cls(
            len(data), sum(data) / len(data), percentile(data, 50), percentile(data, 95), max(data)
        )

    def as_dict(self, digits: int = 3) -> dict:
        def r(v: float):
            return None if math.isnan(v) else round(v, digits)

        return {
            "count": self.count,
            "mean": r(self.mean),
            "p50": r(self.p50),
            "p95": r(self.p95),
            "max": r(self.max),
        }


class RateMeter:
    """Frame-rate and drop estimation over a sliding window of frame timestamps.

    Drops are *estimated* from gaps in the timestamps (the driver's own sequence counter is not
    exposed through OpenCV), using the median interval as the nominal period, so they include
    frames lost anywhere between sensor and application.
    """

    def __init__(self, window: int = 240):
        self._stamps: deque[float] = deque(maxlen=window)
        self._intervals: deque[float] = deque(maxlen=window)
        self.total_frames = 0
        self.total_dropped = 0

    def reset(self) -> None:
        self._stamps.clear()
        self._intervals.clear()

    def add(self, t_ms: float) -> tuple[float | None, int]:
        """Registers a frame timestamp (ms). Returns (interval_ms, estimated frames dropped)."""
        interval = None
        dropped = 0
        if self._stamps:
            interval = t_ms - self._stamps[-1]
            if len(self._intervals) >= 10:
                dropped = estimate_dropped(interval, self.nominal_interval_ms)
            self._intervals.append(interval)
        self._stamps.append(t_ms)
        self.total_frames += 1
        self.total_dropped += dropped
        return interval, dropped

    @property
    def nominal_interval_ms(self) -> float:
        return percentile(list(self._intervals), 50) if self._intervals else math.nan

    @property
    def fps(self) -> float:
        if len(self._stamps) < 2:
            return math.nan
        span = self._stamps[-1] - self._stamps[0]
        return (len(self._stamps) - 1) * 1000.0 / span if span > 0 else math.nan

    def interval_summary(self) -> Summary:
        return Summary.of(self._intervals)
