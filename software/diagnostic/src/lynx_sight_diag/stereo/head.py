"""Head pose and 3-D eye observations from MediaPipe landmarks seen by both cameras.

MediaPipe numbers its 478 landmarks identically in every image, so the same index in the two
cameras is a stereo correspondence. Triangulating a set of points that move little with
expression (eye corners, nose bridge and ridge, forehead midline) gives the face's 3-D shape in
the rig frame. The user's own shape, taken once while they face the rig (`FaceTemplate`), is the
reference: each later frame's head pose is the rigid transform that best maps the template onto
the frame's points (Kabsch). So the pose is metric and needs no generic face model, but it
assumes the user's head frame is parallel to the rig when the template was taken; a constant
offset from that is absorbed by the gaze fit.

Per eye this module reports where the eye is (the eye-corner midpoint, rig mm) and where its
iris sits in head coordinates (`iris-in-head/v1`): the iris centre relative to that midpoint in
units of the 3-D corner distance, along head X (to the user's right) and head Y (up). The eye
corners move with the head but not with gaze, so this follows the eye's rotation in the head,
independently of where the head is.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..features import _MP_EYES
from .rig import StereoRig

IRIS_IN_HEAD = "iris-in-head/v1"
EYE_LABELS = ("user_left", "user_right")  # anatomical, as cam_left / cam_right

# Landmarks used for the head pose: eye corners, nose bridge and ridge, forehead midline.
# Lips, jaw and brows are left out because they move with expression.
POSE_LANDMARKS = (33, 133, 362, 263, 168, 6, 197, 195, 5, 4, 10, 151, 9, 8, 107, 336)
EYE_LANDMARKS = tuple(i for spec in _MP_EYES for i in (*spec["corners"], spec["iris"]))
USED_LANDMARKS = tuple(sorted(set(POSE_LANDMARKS) | set(EYE_LANDMARKS)))
MAX_REPROJECTION_PX = 6.0  # a point whose two rays miss each other by more is not used


def kabsch(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rotation R and translation t minimising |R src + t - dst| (rows are points)."""
    cs, cd = src.mean(axis=0), dst.mean(axis=0)
    U, _, Vt = np.linalg.svd((src - cs).T @ (dst - cd))
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(Vt.T @ U.T))])
    R = Vt.T @ D @ U.T
    return R, cd - R @ cs


@dataclass(frozen=True)
class FacePoints:
    """Triangulated landmarks of one stereo pair."""

    t_ns: int
    skew_ms: float  # capture-time difference of the two images
    points: dict[int, np.ndarray]  # landmark index -> rig mm, only well-triangulated ones

    def array(self, indices) -> tuple[np.ndarray, list[int]]:
        found = [i for i in indices if i in self.points]
        return np.array([self.points[i] for i in found]).reshape(-1, 3), found


def triangulate_face(
    rig: StereoRig, left_px: np.ndarray, right_px: np.ndarray, t_ns: int = 0, skew_ms: float = 0.0
) -> FacePoints:
    """`left_px`/`right_px`: (478, 2) MediaPipe landmarks in full-resolution pixels."""
    idx = list(USED_LANDMARKS)
    pts, err = rig.triangulate(np.asarray(left_px)[idx], np.asarray(right_px)[idx])
    ok = (err < MAX_REPROJECTION_PX) & (pts[:, 2] > 100)  # in front of the rig
    return FacePoints(t_ns, skew_ms, {i: p for i, p, g in zip(idx, pts, ok, strict=True) if g})


@dataclass(frozen=True)
class FaceTemplate:
    """The user's face shape in head coordinates (origin: eye-corner midpoint, axes: rig axes
    at the time the template was taken)."""

    points: dict[int, np.ndarray]

    @classmethod
    def from_faces(cls, faces: list[FacePoints], min_faces: int = 5) -> FaceTemplate:
        """Median shape over frames of a still, front-facing head, each aligned to the first."""
        faces = [f for f in faces if all(i in f.points for i in POSE_LANDMARKS[:4])]
        if len(faces) < min_faces:
            raise ValueError(
                f"need {min_faces} faces with both eyes triangulated, got {len(faces)}"
            )
        common = [i for i in POSE_LANDMARKS if all(i in f.points for f in faces)]
        ref, _ = faces[0].array(common)
        aligned = []
        for f in faces:
            pts, _ = f.array(common)
            R, t = kabsch(pts, ref)
            aligned.append(pts @ R.T + t)
        shape = np.median(np.stack(aligned), axis=0)
        origin = shape[[common.index(i) for i in POSE_LANDMARKS[:4]]].mean(axis=0)
        return cls({i: p - origin for i, p in zip(common, shape, strict=True)})

    def to_dict(self) -> dict:
        return {str(i): [round(float(v), 3) for v in p] for i, p in self.points.items()}

    @classmethod
    def from_dict(cls, data: dict) -> FaceTemplate:
        return cls({int(i): np.array(p, float) for i, p in data.items()})


@dataclass(frozen=True)
class HeadPose:
    R: np.ndarray  # rig_from_head rotation
    t: np.ndarray  # head origin (eye-corner midpoint) in rig mm
    residual_mm: float  # RMS fit residual of the pose landmarks
    n_points: int

    def to_head(self, points_rig: np.ndarray) -> np.ndarray:
        return (np.atleast_2d(points_rig) - self.t) @ self.R

    def angles_deg(self) -> tuple[float, float, float]:
        """(yaw, pitch, roll) with R = Ry(yaw) Rx(pitch) Rz(roll) about the rig axes. Positive
        yaw turns the face to the user's left, positive pitch tilts it up."""
        R = self.R
        yaw = np.degrees(np.arctan2(R[0, 2], R[2, 2]))
        pitch = np.degrees(np.arcsin(np.clip(-R[1, 2], -1, 1)))
        roll = np.degrees(np.arctan2(R[1, 0], R[1, 1]))
        return float(yaw), float(pitch), float(roll)


def head_pose(face: FacePoints, template: FaceTemplate, min_points: int = 6) -> HeadPose | None:
    common = [i for i in template.points if i in face.points]
    if len(common) < min_points:
        return None
    src = np.array([template.points[i] for i in common])
    dst = np.array([face.points[i] for i in common])
    R, t = kabsch(src, dst)
    res = np.linalg.norm(src @ R.T + t - dst, axis=1)
    # One robust pass: drop points far off the rigid fit (a mis-tracked landmark).
    keep = res <= max(3 * float(np.median(res)), 2.0)
    if keep.sum() >= min_points and not keep.all():
        R, t = kabsch(src[keep], dst[keep])
        res = np.linalg.norm(src[keep] @ R.T + t - dst[keep], axis=1)
    return HeadPose(R, t, float(np.sqrt(np.mean(res**2))), int(len(res)))


@dataclass(frozen=True)
class EyeObservation:
    label: str  # "user_left" | "user_right"
    centre_rig: np.ndarray  # eye-corner midpoint, mm
    iris_in_head: np.ndarray  # (2,) feature, see module docstring
    width_mm: float  # 3-D corner distance


@dataclass(frozen=True)
class GazeObservation:
    t_ns: int
    skew_ms: float
    head: HeadPose
    eyes: dict[str, EyeObservation]


def observe(face: FacePoints, template: FaceTemplate) -> GazeObservation | None:
    pose = head_pose(face, template)
    if pose is None:
        return None
    eyes = {}
    for spec in _MP_EYES:
        a, b, iris = spec["corners"][0], spec["corners"][1], spec["iris"]
        if not all(i in face.points for i in (a, b, iris)):
            continue
        ha, hb, hi = pose.to_head(np.array([face.points[a], face.points[b], face.points[iris]]))
        width = float(np.linalg.norm(hb - ha))
        if width < 10:  # mm; a real eye is ~25-35 mm corner to corner
            continue
        mid_h = (ha + hb) / 2
        label = "user_right" if mid_h[0] > 0 else "user_left"
        eyes[label] = EyeObservation(
            label,
            (face.points[a] + face.points[b]) / 2,
            ((hi - mid_h) / width)[:2],
            width,
        )
    return GazeObservation(face.t_ns, face.skew_ms, pose, eyes) if eyes else None


def pair_by_time(
    left: list[tuple[int, np.ndarray]], right: list[tuple[int, np.ndarray]], max_skew_ms: float
) -> list[tuple[int, float, np.ndarray, np.ndarray]]:
    """Pairs per-camera (t_ns, landmarks) by nearest capture time, each used at most once.
    Returns (mean t_ns, skew_ms, left landmarks, right landmarks)."""
    right_sorted = sorted(right, key=lambda r: r[0])
    times = np.array([r[0] for r in right_sorted], np.int64)
    used: set[int] = set()
    pairs = []
    for t, pts in sorted(left, key=lambda r: r[0]):
        if not len(times):
            break
        k = int(np.searchsorted(times, t))
        best = None
        for j in (k - 1, k):
            if 0 <= j < len(times) and j not in used:
                d = abs(int(times[j]) - t)
                if best is None or d < best[0]:
                    best = (d, j)
        if best is not None and best[0] <= max_skew_ms * 1e6:
            used.add(best[1])
            tr, pr = right_sorted[best[1]]
            pairs.append(((t + tr) // 2, best[0] / 1e6, pts, pr))
    return pairs
