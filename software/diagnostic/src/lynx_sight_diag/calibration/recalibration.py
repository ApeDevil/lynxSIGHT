"""Quick recalibration, model comparison and (interface-level) incremental correction.

* **Quick recalibration** keeps the per-camera fits of an existing model and fits only a global
  affine correction of its output to a few new targets, regularised toward "no change" so a
  handful of noisy samples cannot distort an already good model. With fewer than three distinct
  targets only an offset is fitted.
* **Comparison** decides on the *same* fresh validation data, paired per target, whether a
  candidate is better, equivalent or worse than the current model. A candidate never replaces
  the current model unless it is better; the desktop core enforces that and keeps both.
* **Incremental correction** proposes a bounded offset from trusted observations (explicit
  confirmations or validation targets, never arbitrary clicks). It is not wired to any
  automatic trigger yet; its proposal goes through the same comparison.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .alignment import Collection, Observation
from .model import GazeModel, ModelError
from .validation import evaluate, per_target_errors, predictions

MIN_COMPARE_TARGETS = 3
RELATIVE_MARGIN = 0.10  # differences below 10 % of the current error count as equivalent
MIN_IMPROVED_SHARE = 0.6


def fit_correction(
    model: GazeModel, observations: Sequence[Observation], regularisation: float = 0.05
) -> GazeModel:
    pred, targets, used, _ = predictions(model, observations)
    distinct = {(round(t[0], 3), round(t[1], 3)) for t in targets}
    if len(used) < 10 or not distinct:
        raise ModelError(f"{len(used)} predictable samples; need at least 10 for a correction")
    if len(distinct) < 3:
        offset = np.median(targets - pred, axis=0)
        affine = np.array([[1.0, 0.0, offset[0]], [0.0, 1.0, offset[1]]])
        note = f"quick offset {offset[0]:+.4f},{offset[1]:+.4f} from {len(distinct)} targets"
        return model.with_correction(affine, note)
    # min |[P 1] X - T|^2 + lam * n * |X - I|^2, X the 3x2 transposed affine.
    design = np.column_stack([pred, np.ones(len(pred))])
    lam = regularisation * len(pred)
    identity = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
    a = design.T @ design + lam * np.eye(3)
    b = design.T @ targets + lam * identity
    x = np.linalg.solve(a, b)
    affine = x.T
    note = f"quick affine from {len(distinct)} targets, {len(used)} samples"
    return model.with_correction(affine, note)


def compare(
    current: GazeModel, candidate: GazeModel, collections: Sequence[Collection], scale: dict
) -> dict:
    """A `ModelComparison` on the same validation collections."""
    cur_report = evaluate(current, collections, scale)
    cand_report = evaluate(candidate, collections, scale)
    cur = per_target_errors(current, collections, scale)
    cand = per_target_errors(candidate, collections, scale)
    shared = sorted(set(cur) & set(cand), key=str)
    result = {"current": cur_report, "candidate": cand_report}
    if len(shared) < MIN_COMPARE_TARGETS:
        return {
            **result,
            "verdict": "inconclusive",
            "reason": f"{len(shared)} validation targets usable by both models; "
            f"need {MIN_COMPARE_TARGETS}",
        }
    c = np.array([cur[k] for k in shared])
    n = np.array([cand[k] for k in shared])
    gain = float(np.mean(c - n))
    margin = RELATIVE_MARGIN * float(np.mean(c))
    improved = float(np.mean(n < c))
    text = (
        f"mean per-target median error {np.mean(c):.1f} px → {np.mean(n):.1f} px over "
        f"{len(shared)} targets, {improved:.0%} improved"
    )
    if gain > margin and improved >= MIN_IMPROVED_SHARE:
        verdict = "better"
    elif gain < -margin:
        verdict = "worse"
    else:
        verdict = "equivalent"
    return {**result, "verdict": verdict, "reason": text}


def propose_offset(
    model: GazeModel,
    observations: Sequence[Observation],
    min_observations: int = 5,
    max_offset: float = 0.05,
    max_spread: float = 0.03,
) -> tuple[GazeModel | None, int, str]:
    """A bounded offset correction from trusted observations, or None with the reason."""
    pred, targets, used, _ = predictions(model, observations)
    if len(used) < min_observations:
        return None, len(used), f"{len(used)} usable trusted observations; need {min_observations}"
    residual = targets - pred
    offset = np.median(residual, axis=0)
    # Drift moves every target alike: compare the per-target offsets, not single samples
    # (which also carry tracking noise).
    keys = [(round(t[0], 4), round(t[1], 4)) for t in targets]
    per_target = np.array(
        [np.median(residual[[k == key for k in keys]], axis=0) for key in dict.fromkeys(keys)]
    )
    spread = float(np.median(np.hypot(*(per_target - offset).T)))
    if float(np.hypot(*offset)) > max_offset:
        return (
            None,
            len(used),
            (f"drift {np.hypot(*offset):.3f} exceeds {max_offset}; recalibrate instead"),
        )
    if spread > max_spread:
        return None, len(used), f"observations disagree (spread {spread:.3f}); not a drift"
    affine = np.array([[1.0, 0.0, offset[0]], [0.0, 1.0, offset[1]]])
    candidate = model.with_correction(affine, f"incremental offset from {len(used)} observations")
    return candidate, len(used), f"offset {offset[0]:+.4f},{offset[1]:+.4f}"
