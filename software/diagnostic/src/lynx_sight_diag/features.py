"""Per-frame gaze features: what calibration and the face baseline consume.

One `FeatureSample` per processed camera frame. Two feature definitions exist; a gaze model is
fitted on exactly one of them (`GazeModel.feature_set`):

* ``iris-in-eye/v1`` (preferred, needs the MediaPipe landmarks): the iris centre relative to the
  midpoint of the two eye corners, in units of the corner distance, along the corner axis (u)
  and perpendicular to it, downwards (v). The corners do not move with gaze, so this follows the
  eye's rotation, and dividing by the eye width removes the distance.
* ``pupil-offset/v1`` (fallback without MediaPipe): the dark-pupil position relative to YuNet's
  eye landmark divided by the inter-eye distance (`processing/eyes.py`). The YuNet eye landmark
  partly follows the iris, so this signal is weaker.

All values are image measurements. Head pose angles come from MediaPipe and are uncalibrated.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

IRIS_IN_EYE = "iris-in-eye/v1"
PUPIL_OFFSET = "pupil-offset/v1"
FEATURE_SETS = (IRIS_IN_EYE, PUPIL_OFFSET)
EYES = ("image_left", "image_right")

# MediaPipe Face Landmarker (478 points) indices per anatomical eye: corners, lids, iris.
# The subject's right eye appears on the image left; labels are assigned by image position.
_MP_EYES = (
    {"corners": (33, 133), "lids": (159, 145), "iris": 468},
    {"corners": (362, 263), "lids": (386, 374), "iris": 473},
)


@dataclass(frozen=True)
class EyeFeature:
    eye: str  # "image_left" | "image_right"
    iris: tuple[float, float] | None  # gaze feature (u, v); None when not found
    openness: float | None  # lid opening / eye width; None when not measurable
    confidence: float  # 0..1


@dataclass(frozen=True)
class HeadState:
    x: float  # face centre / image width, 0..1
    y: float  # face centre / image height
    scale_px: float  # inter-eye distance in pixels (shrinks with distance)
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None


@dataclass(frozen=True)
class FeatureSample:
    t_ns: int  # capture time, CLOCK_MONOTONIC
    camera_id: str
    face_confidence: float | None  # None: no face
    eyes: tuple[EyeFeature, ...]
    head: HeadState | None

    def eye(self, label: str) -> EyeFeature | None:
        return next((e for e in self.eyes if e.eye == label), None)

    @property
    def tracked_eyes(self) -> tuple[EyeFeature, ...]:
        return tuple(e for e in self.eyes if e.iris is not None)


def iris_in_eye(
    corner_a: np.ndarray, corner_b: np.ndarray, iris: np.ndarray
) -> tuple[tuple[float, float], float]:
    """(u, v) of the iris relative to the corners, and the eye width in pixels."""
    a, b = (corner_a, corner_b) if corner_a[0] <= corner_b[0] else (corner_b, corner_a)
    axis = b - a
    width = float(np.hypot(*axis))
    if width <= 1e-6:
        raise ValueError("degenerate eye corners")
    e = axis / width
    n = np.array([-e[1], e[0]])  # perpendicular, pointing down in the image
    d = iris - (a + b) / 2
    return (float(d @ e) / width, float(d @ n) / width), width


def from_landmarks(
    t_ns: int,
    camera_id: str,
    points: np.ndarray,
    image_size: tuple[int, int],
    head_pose_deg: tuple[float, float, float] | None,
    face_confidence: float = 1.0,
) -> FeatureSample:
    """Features from a 478-point MediaPipe mesh in full-resolution pixels."""
    width, height = image_size
    eyes = []
    centres = []
    for spec in _MP_EYES:
        ca, cb = points[spec["corners"][0]], points[spec["corners"][1]]
        centres.append((ca + cb) / 2)
        try:
            (u, v), eye_width = iris_in_eye(ca, cb, points[spec["iris"]])
        except (ValueError, IndexError):
            eyes.append((None, None))
            continue
        up, low = points[spec["lids"][0]], points[spec["lids"][1]]
        eyes.append(((u, v), float(np.hypot(*(low - up))) / eye_width))
    order = sorted(range(2), key=lambda i: centres[i][0])
    features = tuple(
        EyeFeature(label, eyes[i][0], eyes[i][1], face_confidence)
        for label, i in zip(EYES, order, strict=True)
    )
    lo, hi = points[:468].min(axis=0), points[:468].max(axis=0)
    scale = float(np.hypot(*(centres[order[1]] - centres[order[0]])))
    yaw, pitch, roll = head_pose_deg if head_pose_deg else (None, None, None)
    head = HeadState(
        float((lo[0] + hi[0]) / 2 / width), float((lo[1] + hi[1]) / 2 / height), scale,
        yaw, pitch, roll,
    )  # fmt: skip
    return FeatureSample(t_ns, camera_id, face_confidence, features, head)


def from_eyes(t_ns: int, camera_id: str, eyes) -> FeatureSample:
    """Fallback features from the YuNet-based `eyes` result (`processing.eyes.Eyes`)."""
    if eyes is None:
        return FeatureSample(t_ns, camera_id, None, (), None)
    by_label = {r.label: r for r in eyes.regions}
    features = []
    for label in EYES:
        region = by_label.get(label)
        if region is None:
            features.append(EyeFeature(label, None, None, 0.0))
            continue
        conf = region.pupil.confidence if region.pupil else 0.0
        features.append(EyeFeature(label, region.pupil_offset, None, float(conf)))
    roll = eyes.roll_deg
    head = HeadState(
        eyes.face_centre_norm[0], eyes.face_centre_norm[1], eyes.eye_distance_px, None, None, roll
    )
    return FeatureSample(t_ns, camera_id, eyes.face_score, tuple(features), head)


def no_face(t_ns: int, camera_id: str) -> FeatureSample:
    return FeatureSample(t_ns, camera_id, None, (), None)


def finite(*values: float | None) -> bool:
    return all(v is not None and math.isfinite(v) for v in values)


def eye_offsets(samples: Sequence[FeatureSample]) -> dict[str, tuple[float, float]]:
    """Per eye, its median difference from the two-eye mean, over samples with both eyes.
    Subtracting it lets one eye stand in for both when the other is lost."""
    diffs: dict[str, list] = defaultdict(list)
    seen: set[str] = set()
    for s in samples:
        tracked = s.tracked_eyes
        seen.update(e.eye for e in tracked)
        if len(tracked) == 2:
            mu = np.mean([e.iris for e in tracked], axis=0)
            for e in tracked:
                diffs[e.eye].append(np.asarray(e.iris) - mu)
    return {
        eye: tuple(float(v) for v in np.median(diffs[eye], axis=0)) if diffs[eye] else (0.0, 0.0)
        for eye in EYES
        if eye in seen
    }


def combined_iris(
    sample: FeatureSample, offsets: dict[str, tuple[float, float]]
) -> tuple[float, float] | None:
    """The eyes' mean iris feature, each corrected by its offset; None without a usable eye."""
    tracked = [e for e in sample.tracked_eyes if e.eye in offsets]
    if not tracked:
        return None
    u = float(np.mean([e.iris[0] - offsets[e.eye][0] for e in tracked]))
    v = float(np.mean([e.iris[1] - offsets[e.eye][1] for e in tracked]))
    return u, v
