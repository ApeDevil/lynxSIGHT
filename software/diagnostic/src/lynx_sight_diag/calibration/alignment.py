"""Aligning what was presented with what the eyes did.

Input: a target plan, the `Presentation` the UI reported (what was drawn when, on
CLOCK_MONOTONIC), and the feature samples of that time. Output: `Observation`s, each a sample
paired with the target the user is taken to have looked at, plus a `CollectionSummary`.

* **Stationary:** a target counts only after `settle_ms` (saccade, settling) and only while the
  eyes hold still: samples far from the per-target median, relative to its spread, are
  ``unstable``.
* **Smooth pursuit:** the user does not look at the exact target centre at every instant. The
  delay between drawing and eye features (display, eye and tracking latency together) is
  estimated by searching the lag that best explains the features with a smooth (affine) map;
  stretches where that map fails (look-aways, catch-up saccades) are ``not_following``. The
  map (the model's own polynomial of the iris feature plus linear head terms, fitted per
  camera and per presentation) is only a following detector, not the gaze model.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from .. import features as feat
from ..features import FeatureSample
from . import poly_features, quality

MAX_LAG_MS = 400.0
LAG_STEP_MS = 5.0


@dataclass(frozen=True)
class Observation:
    sample: FeatureSample
    target: tuple[float, float]
    target_index: int | None
    plan_id: str
    purpose: str
    method: str


@dataclass
class Collection:
    plan: dict
    observations: list[Observation]
    summary: dict
    lag_ms: float | None = None
    reasons: list[str | None] = field(default_factory=list)


class Timeline:
    """The presented target as a function of time, from the reported frames."""

    def __init__(self, presentation: dict):
        frames = sorted(presentation["frames"], key=lambda f: f["t_ns"])
        self.t = np.array([f["t_ns"] for f in frames], np.int64)
        self.xy = np.array([[f["position"]["x"], f["position"]["y"]] for f in frames], float)
        self.index = [f.get("target_index") for f in frames]
        self.spans = [(s["start_ns"], s["end_ns"]) for s in presentation["spans"]]
        # Onset of each frame's target: the first frame of its uninterrupted run.
        self.onset = np.empty(len(frames), np.int64)
        for i in range(len(frames)):
            same = i > 0 and self.index[i] == self.index[i - 1] and self.index[i] is not None
            self.onset[i] = self.onset[i - 1] if same else self.t[i]

    def in_span(self, t_ns: int) -> tuple[int, int] | None:
        return next(((a, b) for a, b in self.spans if a <= t_ns <= b), None)

    def frame_at(self, t_ns: int) -> int | None:
        i = bisect_right(self.t, t_ns) - 1
        return i if i >= 0 else None

    def interpolate(self, t_ns: np.ndarray) -> np.ndarray:
        return np.column_stack(
            [np.interp(t_ns, self.t, self.xy[:, 0]), np.interp(t_ns, self.t, self.xy[:, 1])]
        )


HEAD_TERMS = ("x", "y", "yaw_deg", "pitch_deg")


def detector_features(sample: FeatureSample, offsets) -> list[float] | None:
    """Offset-corrected mean iris feature plus whatever head terms the sample has, for the
    following detector. Head movement shifts the iris for the same target, so it must be
    explained too."""
    c = feat.combined_iris(sample, offsets)
    if c is None:
        return None
    head = sample.head
    terms = [getattr(head, t) if head else None for t in HEAD_TERMS]
    return [*c, *(v if v is not None else 0.0 for v in terms)]


def _summary(plan, total, reasons, **extra) -> dict:
    counts = quality.count(reasons)
    out = {
        "plan_id": plan["plan_id"],
        "purpose": plan["purpose"],
        "samples_total": total,
        "samples_accepted": sum(r is None for r in reasons),
        "rejected": counts,
        "targets_usable": None,
        "targets_total": None,
        "estimated_lag_ms": {"status": "unavailable", "reason": "stationary plan"},
        "following_fraction": {"status": "unavailable", "reason": "stationary plan"},
        "warnings": [],
    }
    out.update(extra)
    return out


def align_stationary(
    plan: dict,
    presentation: dict,
    samples: Sequence[FeatureSample],
    policy: quality.QualityPolicy = quality.DEFAULT_POLICY,
    neutral_openness: float | None = None,
    min_samples: int = 5,
    stability_k: float = 3.5,
    stability_floor: float = 0.004,
) -> Collection:
    body = plan["body"]
    timeline = Timeline(presentation)
    settle_ns = int(body["settle_ms"] * 1e6)
    reasons = quality.classify(samples, policy, neutral_openness)
    frame_of: list[int | None] = [None] * len(samples)
    for i, s in enumerate(samples):
        span = timeline.in_span(s.t_ns)
        f = timeline.frame_at(s.t_ns)
        if span is None or f is None or timeline.index[f] is None:
            reasons[i] = quality.OUTSIDE
            continue
        frame_of[i] = f
        if reasons[i] is None and s.t_ns - max(int(timeline.onset[f]), span[0]) < settle_ns:
            reasons[i] = quality.SETTLING
    # Stability per (target, camera, eye): robust z-score against the group median.
    groups: dict[tuple, list[tuple[int, tuple[float, float]]]] = defaultdict(list)
    for i, s in enumerate(samples):
        if reasons[i] is None:
            for e in s.tracked_eyes:
                groups[(timeline.index[frame_of[i]], s.camera_id, e.eye)].append((i, e.iris))
    for members in groups.values():
        values = np.array([v for _, v in members])
        med = np.median(values, axis=0)
        mad = np.maximum(np.median(np.abs(values - med), axis=0) * 1.4826, stability_floor)
        for (i, _), v in zip(members, values, strict=True):
            if np.any(np.abs(v - med) > stability_k * mad):
                reasons[i] = quality.UNSTABLE
    per_target: dict[int, int] = defaultdict(int)
    for i in range(len(samples)):
        if reasons[i] is None:
            per_target[timeline.index[frame_of[i]]] += 1
    usable = {t for t, n in per_target.items() if n >= min_samples}
    observations = []
    for i, s in enumerate(samples):
        if reasons[i] is None and timeline.index[frame_of[i]] not in usable:
            reasons[i] = quality.UNSTABLE  # too few steady samples left for this target
        if reasons[i] is None:
            f = frame_of[i]
            observations.append(
                Observation(s, tuple(timeline.xy[f]), timeline.index[f], plan["plan_id"],
                            plan["purpose"], "stationary")
            )  # fmt: skip
    n_targets = len(body["targets"])
    warnings = []
    if len(usable) < n_targets:
        warnings.append(
            f"{n_targets - len(usable)} of {n_targets} targets had too few steady samples"
        )
    summary = _summary(
        plan, len(samples), reasons, targets_usable=len(usable), targets_total=n_targets,
        warnings=warnings,
    )  # fmt: skip
    return Collection(plan, observations, summary, None, reasons)


def _design(features: np.ndarray) -> np.ndarray:
    uv = features[:, :2]
    uv = (uv - uv.mean(axis=0)) / np.maximum(uv.std(axis=0), 1e-9)
    head = features[:, 2:]
    head = (head - head.mean(axis=0)) / np.maximum(head.std(axis=0), 1e-9)
    return np.column_stack([poly_features(uv), head])


def _smooth_residuals(features: np.ndarray, targets: np.ndarray, trims: int = 4) -> np.ndarray:
    """Residuals of a trimmed least-squares fit: samples far off the first fits (look-aways)
    are left out of the next, so they cannot bend the map toward themselves."""
    design = _design(features)
    keep = np.ones(len(design), bool)
    for _ in range(trims + 1):
        coef = np.linalg.lstsq(design[keep], targets[keep], rcond=None)[0]
        residual = np.hypot(*(design @ coef - targets).T)
        keep = residual <= 2.5 * np.median(residual)
    return residual


def _smoothed(times: np.ndarray, feats: np.ndarray, window: int = 7) -> np.ndarray:
    """Centred moving average over `window` samples (input sorted by time, one camera).
    Centred, so it adds no delay; it removes the frame-to-frame noise that would otherwise
    hide the small residual changes the lag search looks for."""
    if len(feats) < window:
        return feats
    kernel = np.ones(window) / window
    out = feats.copy()
    half = window // 2
    for j in range(feats.shape[1]):
        out[half:-half, j] = np.convolve(feats[:, j], kernel, mode="valid")
    return out


def estimate_lag(
    times: np.ndarray, cams: np.ndarray, feats: np.ndarray, timeline: Timeline
) -> tuple[float, float]:
    """(lag_ms, inlier RMS residual) of the smooth map over all cameras, minimized over the
    lag. Inliers (within 3x the median residual), because look-aways must not decide it."""
    smooth = {c: _smoothed(times[cams == c], feats[cams == c]) for c in np.unique(cams)}
    best = (0.0, float("inf"))
    for lag in np.arange(0.0, MAX_LAG_MS + 1e-9, LAG_STEP_MS):
        targets = timeline.interpolate(times - int(lag * 1e6))
        res = np.concatenate(
            [_smooth_residuals(smooth[c], targets[cams == c]) for c in np.unique(cams)]
        )
        inliers = res[res <= 3 * np.median(res)]
        score = float(np.sqrt(np.mean(inliers**2)))
        if score < best[1]:
            best = (float(lag), score)
    return best


def align_pursuit(
    plan: dict,
    presentation: dict,
    samples: Sequence[FeatureSample],
    policy: quality.QualityPolicy = quality.DEFAULT_POLICY,
    neutral_openness: float | None = None,
    bin_ms: float = 250.0,
    iterations: int = 3,
) -> Collection:
    body = plan["body"]
    timeline = Timeline(presentation)
    reasons = quality.classify(samples, policy, neutral_openness)
    starts = [a for a, _ in timeline.spans]
    motion_start = (min(starts) if starts else 0) + int(body["lead_in_ms"] * 1e6)
    for i, s in enumerate(samples):
        if timeline.in_span(s.t_ns) is None:
            reasons[i] = quality.OUTSIDE
        elif reasons[i] is None and s.t_ns < motion_start:
            reasons[i] = quality.SETTLING
    candidates = [i for i, r in enumerate(reasons) if r is None]
    lag_ms = None
    following = None
    warnings: list[str] = []
    if len(candidates) < 30:
        warnings.append("too few usable samples to detect pursuit")
        for i in candidates:
            reasons[i] = quality.NOT_FOLLOWING
        candidates = []
    keep = np.array(candidates, int)
    times = np.array([samples[i].t_ns for i in keep], np.int64)
    cams = np.array([samples[i].camera_id for i in keep])
    offsets = {
        c: feat.eye_offsets([samples[i] for i in keep if samples[i].camera_id == c])
        for c in set(cams)
    }
    feats = np.array(
        [detector_features(samples[i], offsets[samples[i].camera_id]) for i in keep], float
    )
    feats = feats.reshape(len(keep), 2 + len(HEAD_TERMS))
    following_mask = np.ones(len(keep), bool)
    bins = ((times - motion_start) // int(bin_ms * 1e6)) if len(keep) else times
    for _ in range(iterations if len(keep) else 0):
        sel = following_mask
        if sel.sum() < 30:
            break
        lag_ms, _ = estimate_lag(times[sel], cams[sel], feats[sel], timeline)
        targets = timeline.interpolate(times - int(lag_ms * 1e6))
        residual = np.zeros(len(keep))
        for c in np.unique(cams):
            m = cams == c
            design = _design(feats[m])
            coef = np.linalg.lstsq(design[sel[m]], targets[m][sel[m]], rcond=None)[0]
            residual[m] = np.hypot(*(design @ coef - targets[m]).T)
        typical = float(np.median(residual[sel]))
        sample_limit = max(4 * typical, 0.06)
        bin_limit = max(3 * typical, 0.04)
        new_mask = residual <= sample_limit
        for b in np.unique(bins):
            m = bins == b
            if np.median(residual[m]) > bin_limit:
                new_mask[m] = False
        if np.array_equal(new_mask, following_mask):
            break
        following_mask = new_mask
    observations = []
    if lag_ms is not None:
        targets = timeline.interpolate(times - int(lag_ms * 1e6))
        for k, i in enumerate(keep):
            if following_mask[k]:
                observations.append(
                    Observation(samples[i], (float(targets[k, 0]), float(targets[k, 1])), None,
                                plan["plan_id"], plan["purpose"], "pursuit")
                )  # fmt: skip
            else:
                reasons[i] = quality.NOT_FOLLOWING
        bins_total = len(np.unique(bins))
        bins_following = len(np.unique(bins[following_mask]))
        following = bins_following / bins_total if bins_total else None
        if following is not None and following < 0.5:
            warnings.append("the eyes followed the target less than half of the time")
    summary = _summary(
        plan, len(samples), reasons,
        estimated_lag_ms=_metric(lag_ms, "too few samples to estimate"),
        following_fraction=_metric(following, "too few samples to estimate"),
        warnings=warnings,
    )  # fmt: skip
    return Collection(plan, observations, summary, lag_ms, reasons)


def _metric(value: float | None, reason: str) -> dict:
    if value is None:
        return {"status": "unavailable", "reason": reason}
    return {"status": "available", "value": float(value)}


def align(plan, presentation, samples, policy=quality.DEFAULT_POLICY, neutral_openness=None):
    method = plan["body"]["method"]
    if method == "stationary":
        return align_stationary(plan, presentation, samples, policy, neutral_openness)
    return align_pursuit(plan, presentation, samples, policy, neutral_openness)
