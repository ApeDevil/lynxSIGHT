"""Preliminary screen-target calibration (experimental).

The user looks at a sequence of on-screen targets while pupil offsets (pupil position relative to
the eye landmark, divided by the inter-eye distance; see processing/eyes.py) are collected from
every camera and eye. A second-order polynomial regression maps the averaged offsets to screen
pixels, and leave-one-out cross-validation reports how well that generalises.

This is a feasibility experiment for the data the cameras deliver. It uses no camera calibration,
no eye model and no head-pose compensation, so the error it reports is not a gaze accuracy and
should only be compared between runs of the same setup.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def grid_targets(
    cols: int, rows: int, width: int, height: int, margin: float = 0.1
) -> list[tuple[int, int]]:
    """Target centres in screen pixels, row by row, inset by `margin` of the screen size."""
    xs = np.linspace(margin * width, (1 - margin) * width, cols) if cols > 1 else [width / 2]
    ys = np.linspace(margin * height, (1 - margin) * height, rows) if rows > 1 else [height / 2]
    return [(round(x), round(y)) for y in ys for x in xs]


def poly_features(offsets: np.ndarray) -> np.ndarray:
    """[1, x, y, xy, x^2, y^2] per row of (x, y) offsets."""
    x, y = offsets[:, 0], offsets[:, 1]
    return np.column_stack([np.ones_like(x), x, y, x * y, x * x, y * y])


@dataclass
class Fit:
    coefficients: np.ndarray  # (6, 2)
    train_rmse_px: float
    loo_rmse_px: float | None  # leave-one-out over targets; None with too few targets
    n_targets: int

    def predict(self, offsets: np.ndarray) -> np.ndarray:
        return poly_features(np.atleast_2d(offsets)) @ self.coefficients


def _lstsq(features: np.ndarray, targets: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(features, targets, rcond=None)[0]


def fit(offsets: np.ndarray, screen: np.ndarray) -> Fit:
    """Fits per-target mean offsets (N, 2) to screen positions (N, 2). Needs N >= 6."""
    offsets, screen = np.asarray(offsets, float), np.asarray(screen, float)
    n = len(offsets)
    if n < 6:
        raise ValueError(f"need at least 6 targets with data, got {n}")
    feats = poly_features(offsets)
    coef = _lstsq(feats, screen)
    train = float(np.sqrt(np.mean(np.sum((feats @ coef - screen) ** 2, axis=1))))
    loo = None
    if n >= 7:
        errs = []
        for i in range(n):
            keep = np.arange(n) != i
            c = _lstsq(feats[keep], screen[keep])
            errs.append(float(np.sum((feats[i] @ c - screen[i]) ** 2)))
        loo = math.sqrt(sum(errs) / n)
    return Fit(coef, train, loo, n)


def mean_offset(
    samples: list[tuple[float, float]], min_samples: int = 5
) -> tuple[float, float] | None:
    """Robust (median) offset of one target's samples; None with too few samples."""
    if len(samples) < min_samples:
        return None
    arr = np.asarray(samples, float)
    return float(np.median(arr[:, 0])), float(np.median(arr[:, 1]))
