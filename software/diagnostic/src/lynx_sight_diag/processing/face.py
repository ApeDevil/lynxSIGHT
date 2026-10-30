"""Face detection with OpenCV's YuNet (FaceDetectorYN): box, confidence and five landmarks.

YuNet was chosen over Haar cascades (removed from the OpenCV 5 core, no landmarks, no usable
confidence) and over writing a detector: it is small, CPU-real-time, MIT-licensed, and its eye
landmarks seed the eye regions. It was trained on RGB photographs; how well it works on the
OV9281's monochrome near-infrared images is one of the things the hardware tests measure.

Landmarks are named by *image* position (image_left = smaller x), not by the subject's anatomy,
to avoid mirror confusion.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .. import models
from ..frames import Frame
from . import ProcessorUnavailable

LANDMARK_NAMES = (
    "eye_image_left",
    "eye_image_right",
    "nose",
    "mouth_image_left",
    "mouth_image_right",
)


@dataclass(frozen=True)
class Face:
    box: tuple[float, float, float, float]  # x, y, w, h in full-resolution pixels
    score: float
    landmarks: dict[str, tuple[float, float]]

    @property
    def eye_distance_px(self) -> float:
        (ax, ay), (bx, by) = self.landmarks["eye_image_left"], self.landmarks["eye_image_right"]
        return float(np.hypot(bx - ax, by - ay))


@dataclass(frozen=True)
class Faces:
    faces: list[Face]  # sorted by score, best first

    @property
    def best(self) -> Face | None:
        return self.faces[0] if self.faces else None


def parse_yunet(rows: np.ndarray | None, scale: float) -> list[Face]:
    """Converts YuNet's Nx15 output (box, 5 landmark pairs, score) to `Face`s at full scale."""
    faces = []
    if rows is None:
        return faces
    for row in rows:
        x, y, w, h = (float(v) * scale for v in row[:4])
        pts = [(float(row[4 + 2 * i]) * scale, float(row[5 + 2 * i]) * scale) for i in range(5)]
        # YuNet order: right eye, left eye, nose, right mouth corner, left mouth corner (subject's).
        eyes = sorted([pts[0], pts[1]])
        mouth = sorted([pts[3], pts[4]])
        landmarks = dict(
            zip(LANDMARK_NAMES, (eyes[0], eyes[1], pts[2], mouth[0], mouth[1]), strict=True)
        )
        faces.append(Face((x, y, w, h), float(row[14]), landmarks))
    faces.sort(key=lambda f: f.score, reverse=True)
    return faces


class FaceProcessor:
    name = "face"
    upstream = None

    def __init__(
        self, input_width: int = 640, score_threshold: float = 0.7, nms_threshold: float = 0.3
    ):
        self.input_width = input_width
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self._detector = None
        self._size: tuple[int, int] | None = None

    def _ensure(self, size: tuple[int, int]):
        if self._detector is None:
            path = models.locate("yunet")
            if path is None:
                raise ProcessorUnavailable(
                    "YuNet model missing; run `sight-diag models fetch yunet`"
                )
            self._detector = cv2.FaceDetectorYN.create(
                str(path), "", size, self.score_threshold, self.nms_threshold, 50
            )
        if size != self._size:
            self._detector.setInputSize(size)
            self._size = size
        return self._detector

    def process(self, frame: Frame, upstream=None) -> Faces:
        h, w = frame.image.shape
        scale = max(1.0, w / self.input_width)
        small = (
            frame.image
            if scale == 1.0
            else cv2.resize(
                frame.image, (round(w / scale), round(h / scale)), interpolation=cv2.INTER_AREA
            )
        )
        detector = self._ensure((small.shape[1], small.shape[0]))
        _, rows = detector.detect(cv2.cvtColor(small, cv2.COLOR_GRAY2BGR))
        return Faces(parse_yunet(rows, scale))
