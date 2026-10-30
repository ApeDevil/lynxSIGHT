"""Image-quality metrics: exposure, clipping and focus.

`sharpness` (variance of the Laplacian over the central region) is a relative focus measure:
turn the M12 lens until it peaks for the scene at the working distance. Its absolute value
depends on scene content and noise, so only compare readings of the same scene.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..frames import Frame


@dataclass(frozen=True)
class Quality:
    mean: float
    std: float
    p01: float
    p99: float
    saturated_pct: float  # pixels at >= 250
    dark_pct: float  # pixels at <= 5
    sharpness: float


def measure(image: np.ndarray, centre_fraction: float = 0.5) -> Quality:
    # Statistics on a 4x subsample: plenty for histograms and ~16x cheaper.
    sample = image[::4, ::4]
    p01, p99 = np.percentile(sample, (1, 99))
    h, w = image.shape
    ch, cw = int(h * centre_fraction), int(w * centre_fraction)
    centre = image[(h - ch) // 2 : (h + ch) // 2, (w - cw) // 2 : (w + cw) // 2]
    sharpness = float(cv2.Laplacian(centre, cv2.CV_32F).var())
    return Quality(
        mean=float(sample.mean()),
        std=float(sample.std()),
        p01=float(p01),
        p99=float(p99),
        saturated_pct=float((sample >= 250).mean() * 100),
        dark_pct=float((sample <= 5).mean() * 100),
        sharpness=sharpness,
    )


class QualityProcessor:
    name = "quality"
    upstream = None

    def process(self, frame: Frame, upstream=None) -> Quality:
        return measure(frame.image)
