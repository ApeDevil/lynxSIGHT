"""Dark-pupil localisation in an eye region (no active illumination).

Approach: the pupil is a dark, compact, round blob near the centre of the eye region. Blur,
threshold relative to the region's own darkest and median levels, score every plausibly sized
blob by darkness contrast, circularity and distance from the centre (eyelashes and brows are
dark but elongated or off-centre), and take the best blob's intensity-weighted centroid.
Confidence combines darkness contrast against the surrounding ring and circularity, halved for
blobs cut by the region border; it is a heuristic, not a probability.

Without a controlled IR light source the pupil/iris contrast depends on room lighting and iris
colour, which is why this is "basic pupil localisation if image quality permits".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Pupil:
    x: float  # in the coordinates of the region passed in
    y: float
    radius: float
    confidence: float  # 0..1 heuristic
    contrast: float  # (ring mean - pupil mean) / 255
    circularity: float


def _candidate(roi, smooth, blob, area, threshold, median):
    """Measures one dark blob; returns (score, Pupil) or None if implausible."""
    h, w = roi.shape[:2]
    weights = blob * np.clip(threshold - smooth.astype(np.float32), 0, None)
    total = float(weights.sum())
    if total <= 0:
        return None
    ys, xs = np.indices(blob.shape)
    cx = float((weights * xs).sum() / total)
    cy = float((weights * ys).sum() / total)
    radius = math.sqrt(area / math.pi)

    contours, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    perimeter = max(cv2.arcLength(contours[0], True), 1e-6)
    circularity = min(1.0, 4 * math.pi * area / perimeter**2)

    ring = np.zeros_like(blob)
    cv2.circle(ring, (round(cx), round(cy)), max(2, round(radius * 1.8)), 1, -1)
    ring[blob > 0] = 0
    inner_mean = float(roi[blob > 0].mean())
    ring_mean = float(roi[ring > 0].mean()) if ring.any() else median
    contrast = (ring_mean - inner_mean) / 255.0

    x, y, bw, bh = cv2.boundingRect(blob)
    touches_border = x == 0 or y == 0 or x + bw >= w or y + bh >= h
    confidence = min(1.0, max(0.0, contrast * 4)) * circularity * (0.5 if touches_border else 1.0)
    # The eye region is centred on the eye landmark, so prefer blobs near the centre.
    centre_prior = math.exp(-(((cx - w / 2) / (0.35 * w)) ** 2 + ((cy - h / 2) / (0.35 * h)) ** 2))
    pupil = Pupil(cx, cy, radius, round(confidence, 3), round(contrast, 3), round(circularity, 3))
    return confidence * centre_prior, pupil


def locate_pupil(
    roi: np.ndarray,
    min_radius_frac: float = 0.03,
    max_radius_frac: float = 0.3,
    min_contrast: float = 12.0,
) -> Pupil | None:
    h, w = roi.shape[:2]
    if min(h, w) < 12:
        return None
    smooth = cv2.GaussianBlur(roi, (0, 0), max(1.0, w / 60))
    darkest = float(smooth.min())
    median = float(np.median(smooth))
    if median - darkest < min_contrast:
        return None

    threshold = darkest + 0.4 * (median - darkest)
    mask = (smooth <= threshold).astype(np.uint8)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = None
    for label in range(1, count):
        area = float(stats[label, cv2.CC_STAT_AREA])
        radius = math.sqrt(area / math.pi)
        if not (min_radius_frac * w <= radius <= max_radius_frac * w):
            continue
        found = _candidate(roi, smooth, (labels == label).astype(np.uint8), area, threshold, median)
        if found and (best is None or found[0] > best[0]):
            best = found
    return best[1] if best else None
