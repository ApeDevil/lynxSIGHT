"""Sample-level quality filtering shared by every calibration method.

A sample is rejected when it has no usable eye (``missing``), only low-confidence eyes
(``low_confidence``) or a closed eye (``blink``). Blinks are padded in time: the lids move for
about 100 ms around the closed frames and drag the iris estimate with them. Which samples are
*unstable* or *not following* depends on the method and is decided in `alignment.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..features import FeatureSample

MISSING = "missing"
LOW_CONFIDENCE = "low_confidence"
BLINK = "blink"
UNSTABLE = "unstable"
NOT_FOLLOWING = "not_following"
SETTLING = "settling"
OUTSIDE = "outside_presentation"
REASONS = (MISSING, LOW_CONFIDENCE, BLINK, UNSTABLE, NOT_FOLLOWING, SETTLING, OUTSIDE)


@dataclass(frozen=True)
class QualityPolicy:
    min_confidence: float = 0.5
    # A lid opening below this fraction of the neutral opening counts as closed. Without a
    # baseline, `blink_openness_abs` is used instead.
    blink_fraction: float = 0.5
    blink_openness_abs: float = 0.12
    blink_pad_ms: float = 100.0


DEFAULT_POLICY = QualityPolicy()


def classify(
    samples: Sequence[FeatureSample],
    policy: QualityPolicy = DEFAULT_POLICY,
    neutral_openness: float | None = None,
) -> list[str | None]:
    """A rejection reason (or None for usable) per sample, in input order."""
    threshold = (
        neutral_openness * policy.blink_fraction if neutral_openness else policy.blink_openness_abs
    )
    reasons: list[str | None] = []
    closed_times: dict[str, list[int]] = {}
    for s in samples:
        tracked = s.tracked_eyes
        if s.face_confidence is None or not tracked:
            reasons.append(MISSING)
        elif any(e.openness is not None and e.openness < threshold for e in s.eyes):
            reasons.append(BLINK)
            closed_times.setdefault(s.camera_id, []).append(s.t_ns)
        elif max(e.confidence for e in tracked) < policy.min_confidence:
            reasons.append(LOW_CONFIDENCE)
        else:
            reasons.append(None)
    pad = int(policy.blink_pad_ms * 1e6)
    for i, s in enumerate(samples):
        if reasons[i] is None:
            if any(abs(s.t_ns - t) <= pad for t in closed_times.get(s.camera_id, ())):
                reasons[i] = BLINK
    return reasons


def count(reasons: Sequence[str | None]) -> dict[str, int]:
    out = dict.fromkeys(REASONS, 0)
    for r in reasons:
        if r is not None:
            out[r] += 1
    return out
