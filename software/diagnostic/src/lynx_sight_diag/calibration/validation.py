"""Accuracy of a gaze model against validation targets, and the training-only diagnostics.

**Calibration accuracy** needs targets the model was not fitted on (`Purpose: validation`).
Errors are computed per accepted validation sample (one camera frame each), between the
model's estimate and the target, and summarised as median, RMS, 90th percentile and signed
bias, in display pixels always, in millimetres when the physical display size is known, and
in degrees of visual angle when the eye position relative to the display is known too
(`MetricScale`). Without independent data the report says so instead of offering a number.

The leave-one-target-out RMS over the fit targets is kept as a *training* diagnostic: it tells
whether the model generalises between fit points, not how accurate gaze is.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

import numpy as np

from . import quality
from .alignment import Collection, Observation
from .model import GazeModel, ModelError, fit

REGION_COLS = REGION_ROWS = 3


def metric(value: float | None, reason: str = "") -> dict:
    if value is None or not math.isfinite(value):
        return {"status": "unavailable", "reason": reason or "not computable"}
    return {"status": "available", "value": float(value)}


class Errors:
    """Per-sample errors of predictions against targets in every unit the scale supports."""

    def __init__(self, predicted: np.ndarray, targets: np.ndarray, scale: dict):
        self.targets = targets
        d = predicted - targets  # normalized, + right / down
        w, h = scale["width_px"], scale["height_px"]
        self.dx = {"px": d[:, 0] * w}
        self.dy = {"px": d[:, 1] * h}
        self.dist = {"px": np.hypot(self.dx["px"], self.dy["px"])}
        self.missing = {}
        wmm, hmm = scale.get("width_mm"), scale.get("height_mm")
        if wmm and hmm:
            self.dx["mm"], self.dy["mm"] = d[:, 0] * wmm, d[:, 1] * hmm
            self.dist["mm"] = np.hypot(self.dx["mm"], self.dy["mm"])
            eye = scale.get("eye_position_mm")
            if eye is not None:
                eye = np.asarray(eye, float)
                t_mm = np.column_stack([targets[:, 0] * wmm, targets[:, 1] * hmm, np.zeros(len(d))])
                p_mm = np.column_stack(
                    [predicted[:, 0] * wmm, predicted[:, 1] * hmm, np.zeros(len(d))]
                )
                a, b = t_mm - eye, p_mm - eye
                cos = np.sum(a * b, axis=1) / (
                    np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
                )
                self.dist["deg"] = np.degrees(np.arccos(np.clip(cos, -1, 1)))
                depth = -eye[2]  # the eye is in front of the screen: negative z
                hx = np.degrees(np.arctan2(p_mm[:, 0] - eye[0], depth)
                                - np.arctan2(t_mm[:, 0] - eye[0], depth))  # fmt: skip
                hy = np.degrees(np.arctan2(p_mm[:, 1] - eye[1], depth)
                                - np.arctan2(t_mm[:, 1] - eye[1], depth))  # fmt: skip
                self.dx["deg"], self.dy["deg"] = hx, hy
            else:
                self.missing["deg"] = "eye position relative to the display unknown"
        else:
            self.missing["mm"] = "physical display size unknown"
            self.missing["deg"] = "physical display size unknown"

    def stat(self, kind: str, fn) -> dict:
        out = {}
        for unit in ("px", "mm", "deg"):
            if unit in self.missing:
                out[unit] = metric(None, self.missing[unit])
            else:
                source = {"bias_x": self.dx, "bias_y": self.dy}.get(kind, self.dist)[unit]
                out[unit] = metric(fn(source) if len(source) else None, "no samples")
        return out


def _accuracy(errors: Errors) -> dict:
    return {
        "median": errors.stat("dist", np.median),
        "rms": errors.stat("dist", lambda v: float(np.sqrt(np.mean(v**2)))),
        "p90": errors.stat("dist", lambda v: float(np.percentile(v, 90))),
        "bias_x": errors.stat("bias_x", np.mean),
        "bias_y": errors.stat("bias_y", np.mean),
    }


def predictions(model: GazeModel, observations: Sequence[Observation]):
    """(predicted, targets, used observations, observations the model could not predict)."""
    pred, targets, used, unpredictable = [], [], [], 0
    for o in observations:
        p = model.predict(o.sample)
        if p is None:
            unpredictable += 1
            continue
        pred.append(p)
        targets.append(o.target)
        used.append(o)
    return (
        np.array(pred, float).reshape(-1, 2),
        np.array(targets, float).reshape(-1, 2),
        used,
        unpredictable,
    )


def evaluate(
    model: GazeModel,
    collections: Sequence[Collection],
    scale: dict,
    latency_ms: float | None = None,
) -> dict:
    """A `ValidationReport` of `model` on the validation collections."""
    observations = [o for c in collections for o in c.observations]
    reasons = [r for c in collections for r in c.reasons]
    total = len(reasons)
    counts = quality.count(reasons)
    pred, targets, used, unpredictable = predictions(model, observations)
    counts[quality.MISSING] += unpredictable
    accepted = len(used)
    report = {
        "source": "independent" if collections else "none",
        "targets": len(
            {(o.plan_id, o.target_index if o.target_index is not None else o.target) for o in used}
        ),  # fmt: skip
        "samples": accepted,
        "accuracy": None,
        "region_cols": REGION_COLS,
        "region_rows": REGION_ROWS,
        "regions": [],
        "acceptance": {
            "total": total,
            "accepted": accepted,
            "rejected": counts,
            "acceptance_rate": metric(accepted / total if total else None, "no samples"),
        },
        "latency_ms": metric(latency_ms, "no pursuit data to estimate it"),
    }
    if not accepted:
        return report
    errors = Errors(pred, targets, scale)
    report["accuracy"] = _accuracy(errors)
    cells: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (x, y) in enumerate(targets):
        col = min(int(x * REGION_COLS), REGION_COLS - 1)
        row = min(int(y * REGION_ROWS), REGION_ROWS - 1)
        cells[(col, row)].append(i)
    for (col, row), idx in sorted(cells.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        sub = Errors(pred[idx], targets[idx], scale)
        report["regions"].append(
            {"col": col, "row": row, "samples": len(idx), "median": sub.stat("dist", np.median)}
        )
    return report


def per_target_errors(model: GazeModel, collections: Sequence[Collection], scale: dict) -> dict:
    """Median pixel error per validation target, keyed by (plan, target)."""
    groups: dict[tuple, list[float]] = defaultdict(list)
    for c in collections:
        pred, targets, used, _ = predictions(model, c.observations)
        if not used:
            continue
        err = Errors(pred, targets, scale).dist["px"]
        for o, e in zip(used, err, strict=True):
            key = (o.plan_id, o.target_index if o.target_index is not None else o.target)
            groups[key].append(float(e))
    return {k: float(np.median(v)) for k, v in groups.items()}


def training_summary(model: GazeModel, collections: Sequence[Collection], scale: dict) -> dict:
    observations = [o for c in collections for o in c.observations]
    pred, targets, used, _ = predictions(model, observations)
    train = None
    if len(used):
        train = float(np.sqrt(np.mean(Errors(pred, targets, scale).dist["px"] ** 2)))
    stationary = [o for o in observations if o.method == "stationary"]
    keys = sorted({(o.plan_id, o.target_index) for o in stationary})
    loo = None
    loo_reason = "fewer than 7 stationary fit targets"
    if len(keys) >= 7:
        errs = []
        for key in keys:
            rest = [
                o
                for o in observations
                if (o.plan_id, o.target_index) != key or o.method != "stationary"
            ]
            held = [o for o in stationary if (o.plan_id, o.target_index) == key]
            try:
                m = fit(rest, model.feature_set)
            except ModelError:
                continue
            p, t, u, _ = predictions(m, held)
            if len(u):
                errs.extend(Errors(p, t, scale).dist["px"] ** 2)
        loo = float(np.sqrt(np.mean(errs))) if errs else None
        loo_reason = "the held-out targets could not be predicted"
    return {
        "samples": len(used),
        "targets": len(keys),
        "train_rms_px": metric(train, "no predictable samples"),
        "leave_one_out_rms_px": metric(loo, loo_reason),
    }
