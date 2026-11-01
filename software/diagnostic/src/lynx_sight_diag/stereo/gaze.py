"""Head-pose-compensated gaze: a ray from each eye, turned with the head, hitting the screen.

Model ``head-ray/v1``. Per eye, the iris-in-head feature (head.py) maps to the gaze direction in
head coordinates as two angles (yaw, pitch) by a fitted polynomial. That direction is turned by
the measured head rotation and cast from the measured eye position onto the screen plane. Only
the polynomial is fitted, so a head movement changes the prediction through geometry instead of
having to be learned: a model fitted with the head in one place is meant to hold when it moves.

Fitting is linear: for a calibration target S on screen, the wanted direction in head coordinates
is R^T (S - E) / |S - E| (E: eye position, R: head rotation), and its angles are regressed on the
feature. The polynomial also absorbs the constant offset between the eye's optical and visual
axis (kappa, ~5 degrees) and the eye-corner midpoint not being the eye's rotation centre.

The screen plane comes from `ScreenPlane`; the prediction is only as good as that pose, which is
assumed from the rig's position on the monitor until it is measured.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .head import EYE_LABELS, IRIS_IN_HEAD, FaceTemplate, GazeObservation

MODEL = "head-ray/v1"
SCHEMA = "lynx-sight/gaze-model/v1"


@dataclass(frozen=True)
class ScreenPlane:
    """The active area of a display in the rig frame. Origin: its top-left corner as the user
    sees it; x_axis to the right, y_axis down (unit vectors, rig coordinates)."""

    origin_mm: np.ndarray
    x_axis: np.ndarray
    y_axis: np.ndarray
    size_mm: tuple[float, float]
    size_px: tuple[int, int]
    provenance: str = "assumed"

    @classmethod
    def below_rig(
        cls, size_mm, size_px, above_mm: float = 15.0, behind_mm: float = 10.0
    ) -> ScreenPlane:
        """A screen centred under the rig, its top edge `above_mm` below the rig origin and its
        surface `behind_mm` behind it (the rig sits on the monitor's top edge, facing the user).
        Same starting estimate as geometry::screen_pose_below_rig in the desktop app."""
        w, _ = size_mm
        return cls(
            np.array([-w / 2, -above_mm, -behind_mm]),
            np.array([1.0, 0, 0]),
            np.array([0, -1.0, 0]),
            tuple(size_mm),
            tuple(size_px),
        )

    @property
    def mm_per_px(self) -> tuple[float, float]:
        return self.size_mm[0] / self.size_px[0], self.size_mm[1] / self.size_px[1]

    @property
    def normal(self) -> np.ndarray:
        return np.cross(self.x_axis, self.y_axis)

    def to_rig(self, px: np.ndarray) -> np.ndarray:
        """(N, 2) screen pixels -> (N, 3) rig mm."""
        px = np.atleast_2d(np.asarray(px, float))
        sx, sy = self.mm_per_px
        return (
            self.origin_mm
            + np.outer(px[:, 0] * sx, self.x_axis)
            + np.outer(px[:, 1] * sy, self.y_axis)
        )

    def intersect(self, origins: np.ndarray, directions: np.ndarray) -> np.ndarray:
        """Rays (N, 3) -> (N, 2) screen pixels; NaN where a ray misses the plane."""
        o, d = np.atleast_2d(origins), np.atleast_2d(directions)
        n = self.normal
        denom = d @ n
        with np.errstate(divide="ignore", invalid="ignore"):
            s = ((self.origin_mm - o) @ n) / denom
        hit = o + d * s[:, None]
        rel = hit - self.origin_mm
        sx, sy = self.mm_per_px
        px = np.column_stack([rel @ self.x_axis / sx, rel @ self.y_axis / sy])
        px[(s <= 0) | ~np.isfinite(s)] = np.nan
        return px

    def to_dict(self) -> dict:
        return {
            "origin_mm": self.origin_mm.tolist(),
            "x_axis": self.x_axis.tolist(),
            "y_axis": self.y_axis.tolist(),
            "size_mm": list(self.size_mm),
            "size_px": list(self.size_px),
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ScreenPlane:
        return cls(
            np.array(d["origin_mm"], float),
            np.array(d["x_axis"], float),
            np.array(d["y_axis"], float),
            tuple(d["size_mm"]),
            tuple(d["size_px"]),
            d.get("provenance", "assumed"),
        )


def angles_of(directions: np.ndarray) -> np.ndarray:
    """Head-frame unit directions (gaze is -Z) -> (N, 2) yaw (toward +X) and pitch (up), rad."""
    d = np.atleast_2d(directions)
    return np.column_stack(
        [np.arctan2(d[:, 0], -d[:, 2]), np.arctan2(d[:, 1], np.hypot(d[:, 0], d[:, 2]))]
    )


def direction_of(angles: np.ndarray) -> np.ndarray:
    a = np.atleast_2d(angles)
    yaw, pitch = a[:, 0], a[:, 1]
    return np.column_stack(
        [np.sin(yaw) * np.cos(pitch), np.sin(pitch), -np.cos(yaw) * np.cos(pitch)]
    )


def design(features: np.ndarray, degree: int) -> np.ndarray:
    f = np.atleast_2d(features)
    x, y = f[:, 0], f[:, 1]
    cols = [np.ones_like(x), x, y]
    if degree >= 2:
        cols += [x * y, x * x, y * y]
    return np.column_stack(cols)


@dataclass
class HeadRayModel:
    screen: ScreenPlane
    template: FaceTemplate
    degree: int
    coefficients: dict[str, np.ndarray]  # eye label -> (n_terms, 2)
    feature_scale: float = 1.0  # features are divided by it before the polynomial (conditioning)

    @classmethod
    def fit(
        cls,
        observations: list[GazeObservation],
        targets_px: np.ndarray,
        screen: ScreenPlane,
        template: FaceTemplate,
        degree: int = 1,
        ridge: float = 1e-4,
    ) -> HeadRayModel:
        targets_rig = screen.to_rig(np.asarray(targets_px, float))
        scale = 0.1  # typical feature magnitude, keeps ridge meaningful for both degrees
        coefficients = {}
        for label in EYE_LABELS:
            rows, wanted = [], []
            for obs, target in zip(observations, targets_rig, strict=True):
                eye = obs.eyes.get(label)
                if eye is None:
                    continue
                d_rig = target - eye.centre_rig
                d_head = obs.head.R.T @ (d_rig / np.linalg.norm(d_rig))
                rows.append(eye.iris_in_head / scale)
                wanted.append(angles_of(d_head)[0])
            n_terms = design(np.zeros((1, 2)), degree).shape[1]
            if len(rows) < n_terms * 2:
                continue
            A = design(np.array(rows), degree)
            reg = ridge * len(rows) * np.eye(n_terms)
            reg[0, 0] = 0
            coefficients[label] = np.linalg.solve(A.T @ A + reg, A.T @ np.array(wanted))
        if not coefficients:
            raise ValueError("no eye has enough observations to fit")
        return cls(screen, template, degree, coefficients, scale)

    def predict_eyes(self, obs: GazeObservation) -> dict[str, np.ndarray]:
        out = {}
        for label, coef in self.coefficients.items():
            eye = obs.eyes.get(label)
            if eye is None:
                continue
            angles = design(eye.iris_in_head / self.feature_scale, self.degree) @ coef
            d_rig = obs.head.R @ direction_of(angles)[0]
            px = self.screen.intersect(eye.centre_rig, d_rig)[0]
            if np.all(np.isfinite(px)):
                out[label] = px
        return out

    def predict(self, obs: GazeObservation) -> np.ndarray | None:
        """Screen pixels: the mean of the eyes' points; None without a usable eye."""
        eyes = self.predict_eyes(obs)
        return np.mean(list(eyes.values()), axis=0) if eyes else None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "model": MODEL,
            "feature_set": IRIS_IN_HEAD,
            "degree": self.degree,
            "feature_scale": self.feature_scale,
            "coefficients": {k: v.tolist() for k, v in self.coefficients.items()},
            "screen": self.screen.to_dict(),
            "template_mm": self.template.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> HeadRayModel:
        if d.get("schema") != SCHEMA or d.get("model") != MODEL:
            raise ValueError(f"not a {MODEL} model")
        return cls(
            ScreenPlane.from_dict(d["screen"]),
            FaceTemplate.from_dict(d["template_mm"]),
            int(d["degree"]),
            {k: np.array(v, float) for k, v in d["coefficients"].items()},
            float(d.get("feature_scale", 1.0)),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> HeadRayModel:
        return cls.from_dict(json.loads(Path(path).read_text()))


def angular_error_deg(
    screen: ScreenPlane, eye_rig: np.ndarray, predicted_px: np.ndarray, target_px: np.ndarray
) -> float:
    """Visual angle between eye->prediction and eye->target."""
    a = screen.to_rig(predicted_px)[0] - eye_rig
    b = screen.to_rig(target_px)[0] - eye_rig
    cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))
