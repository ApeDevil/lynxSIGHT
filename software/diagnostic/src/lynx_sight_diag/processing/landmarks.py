"""Optional dense face landmarks with MediaPipe Face Landmarker (478 points incl. iris).

Install with `uv sync --extra landmarks` and fetch the model with
`sight-diag models fetch face_landmarker`. Head-pose angles come from MediaPipe's facial
transformation matrix, which assumes its own canonical face and a nominal camera; without camera
calibration they are indicative only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .. import models
from ..frames import Frame
from . import ProcessorUnavailable

IRIS_CENTRES = (468, 473)  # indices of the two iris-centre landmarks in the 478-point mesh


@dataclass(frozen=True)
class Landmarks:
    points: np.ndarray  # (478, 2) float32, full-resolution pixels
    iris_centres: list[tuple[float, float]]
    head_pose_deg: tuple[float, float, float] | None  # yaw, pitch, roll; uncalibrated


def euler_from_matrix(matrix: np.ndarray) -> tuple[float, float, float]:
    """Yaw (about Y), pitch (about X), roll (about Z) in degrees from a 3x3/4x4 rotation."""
    r = np.asarray(matrix)[:3, :3]
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, -float(r[2, 0])))))
    pitch = math.degrees(math.atan2(float(r[2, 1]), float(r[2, 2])))
    roll = math.degrees(math.atan2(float(r[1, 0]), float(r[0, 0])))
    return yaw, pitch, roll


class LandmarksProcessor:
    name = "landmarks"
    upstream = None

    def __init__(self):
        self._landmarker = None
        self._mp = None

    def _ensure(self):
        if self._landmarker is not None:
            return self._landmarker
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision
        except ImportError as exc:
            raise ProcessorUnavailable(
                "mediapipe not installed; `uv sync --extra landmarks`"
            ) from exc
        path = models.locate("face_landmarker")
        if path is None:
            raise ProcessorUnavailable(
                "model missing; run `sight-diag models fetch face_landmarker`"
            )
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            num_faces=1,
            output_facial_transformation_matrixes=True,
        )
        self._mp = mp
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        return self._landmarker

    def process(self, frame: Frame, upstream=None) -> Landmarks | None:
        landmarker = self._ensure()
        rgb = cv2.cvtColor(frame.image, cv2.COLOR_GRAY2RGB)
        result = landmarker.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        if not result.face_landmarks:
            return None
        pts = np.array(
            [(p.x * frame.width, p.y * frame.height) for p in result.face_landmarks[0]], np.float32
        )
        iris = [tuple(map(float, pts[i])) for i in IRIS_CENTRES if i < len(pts)]
        pose = None
        if result.facial_transformation_matrixes:
            pose = euler_from_matrix(np.array(result.facial_transformation_matrixes[0]))
        return Landmarks(pts, iris, pose)

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
