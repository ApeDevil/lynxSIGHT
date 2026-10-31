"""The gaze model: eye features (+ head position) → normalized display coordinates.

Kind ``poly2-head-linear`` (version 1), one sub-model per camera:

1. Per-eye offsets make one eye's feature stand in for both when the other is lost: an eye's
   offset is its median difference from the two-eye mean, on samples with both eyes.
2. The combined (u, v), standardized with the training mean and spread, goes through the same
   second-order polynomial as the original experiment (`calibration.poly_features`).
3. Head terms enter linearly: face position in the image and, when the landmark model gives
   them, yaw and pitch. They absorb the first-order effect of head movement; nothing more.
4. Ridge regression, each plan weighted equally so a long pursuit path does not drown the
   stationary targets.

A global affine `correction` (identity after a full calibration) is what quick recalibration
and incremental correction adjust; the per-camera fits stay untouched.

The parameters are this engine's; the desktop core stores them without interpreting them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from .. import __version__
from .. import features as feat
from ..features import FeatureSample
from . import poly_features
from .alignment import Observation

KIND = "poly2-head-linear"
KIND_VERSION = 1
HEAD_TERMS = ("x", "y", "yaw_deg", "pitch_deg")
IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))


class ModelError(ValueError):
    pass


@dataclass
class CameraModel:
    eye_offsets: dict[str, tuple[float, float]]
    feature_mean: tuple[float, float]
    feature_scale: tuple[float, float]
    head_terms: list[str]
    head_mean: list[float]
    head_scale: list[float]
    coefficients: np.ndarray  # (6 + len(head_terms), 2)

    def features(self, sample: FeatureSample) -> np.ndarray | None:
        uv = feat.combined_iris(sample, self.eye_offsets)
        if uv is None or sample.head is None:
            return None
        u, v = uv
        head = [getattr(sample.head, t) for t in self.head_terms]
        if any(h is None for h in head):
            return None
        uv = (np.array([[u, v]]) - self.feature_mean) / self.feature_scale
        h = (np.array(head, float) - self.head_mean) / self.head_scale
        return np.concatenate([poly_features(uv)[0], h])


@dataclass
class GazeModel:
    feature_set: str
    cameras: dict[str, CameraModel]
    correction: tuple[tuple[float, ...], ...] = IDENTITY
    history: list[str] = field(default_factory=list)  # how the correction came about

    def predict_raw(self, sample: FeatureSample) -> np.ndarray | None:
        model = self.cameras.get(sample.camera_id)
        if model is None:
            return None
        f = model.features(sample)
        return None if f is None else f @ model.coefficients

    def predict(self, sample: FeatureSample) -> tuple[float, float] | None:
        raw = self.predict_raw(sample)
        if raw is None:
            return None
        a = np.asarray(self.correction)
        x, y = a[:, :2] @ raw + a[:, 2]
        return float(x), float(y)

    def with_correction(self, affine: np.ndarray, note: str) -> GazeModel:
        """A copy whose correction is `affine` applied after the current one."""
        a = np.vstack([np.asarray(self.correction), [0, 0, 1]])
        b = np.vstack([np.asarray(affine), [0, 0, 1]])
        combined = (b @ a)[:2]
        return GazeModel(
            self.feature_set,
            self.cameras,
            tuple(tuple(float(v) for v in row) for row in combined),
            [*self.history, note],
        )

    # --- contract form ---------------------------------------------------------------------

    def to_contract(self) -> dict:
        return {
            "kind": KIND,
            "kind_version": KIND_VERSION,
            "feature_set": self.feature_set,
            "engine_version": __version__,
            "parameters": {
                "cameras": {
                    cid: {
                        "eye_offsets": {k: list(v) for k, v in m.eye_offsets.items()},
                        "feature_mean": list(m.feature_mean),
                        "feature_scale": list(m.feature_scale),
                        "head_terms": list(m.head_terms),
                        "head_mean": list(m.head_mean),
                        "head_scale": list(m.head_scale),
                        "coefficients": m.coefficients.tolist(),
                    }
                    for cid, m in self.cameras.items()
                },
                "correction": [list(r) for r in self.correction],
                "history": list(self.history),
            },
        }

    @classmethod
    def from_contract(cls, model: dict, feature_set: str | None = None) -> GazeModel:
        if model.get("kind") != KIND or model.get("kind_version") != KIND_VERSION:
            raise ModelError(
                f"model {model.get('kind')} v{model.get('kind_version')} is not {KIND} "
                f"v{KIND_VERSION}"
            )
        if feature_set is not None and model.get("feature_set") != feature_set:
            raise ModelError(
                f"model was fitted on {model.get('feature_set')}, the source delivers {feature_set}"
            )
        try:
            p = model["parameters"]
            cameras = {}
            for cid, m in p["cameras"].items():
                terms = list(m["head_terms"])
                if not set(terms) <= set(HEAD_TERMS):
                    raise ModelError(f"unknown head terms {terms}")
                coef = np.asarray(m["coefficients"], float)
                if coef.shape != (6 + len(terms), 2) or not np.all(np.isfinite(coef)):
                    raise ModelError(f"camera {cid}: bad coefficient shape {coef.shape}")
                cameras[cid] = CameraModel(
                    {k: (float(v[0]), float(v[1])) for k, v in m["eye_offsets"].items()},
                    tuple(map(float, m["feature_mean"])),
                    tuple(map(float, m["feature_scale"])),
                    terms,
                    [float(v) for v in m["head_mean"]],
                    [float(v) for v in m["head_scale"]],
                    coef,
                )
            correction = tuple(tuple(float(v) for v in row) for row in p["correction"])
            if np.asarray(correction).shape != (2, 3):
                raise ModelError("correction must be 2x3")
        except (KeyError, TypeError, IndexError) as exc:
            raise ModelError(f"malformed model parameters: {exc}") from exc
        if not cameras:
            raise ModelError("model has no cameras")
        return cls(model["feature_set"], cameras, correction, list(p.get("history", [])))


def fit(observations: Sequence[Observation], feature_set: str, ridge: float = 1e-3) -> GazeModel:
    """Fits one sub-model per camera. Raises `ModelError` with too little data."""
    by_camera: dict[str, list[Observation]] = defaultdict(list)
    for o in observations:
        by_camera[o.sample.camera_id].append(o)
    cameras = {}
    for cid, obs in sorted(by_camera.items()):
        samples = [o.sample for o in obs]
        offsets = feat.eye_offsets(samples)
        heads = [s.head for s in samples if s.head is not None]
        terms = [t for t in HEAD_TERMS if heads and all(getattr(h, t) is not None for h in heads)]
        partial = CameraModel(offsets, (0.0, 0.0), (1.0, 1.0), terms, [0.0] * len(terms),
                              [1.0] * len(terms), np.zeros((6 + len(terms), 2)))  # fmt: skip
        targets, plan_ids = [], []
        raw = []
        for o in obs:
            uv = feat.combined_iris(o.sample, offsets)
            if uv is None or o.sample.head is None:
                continue
            raw.append((list(uv), [getattr(o.sample.head, t) for t in terms]))
            targets.append(o.target)
            plan_ids.append(o.plan_id)
        distinct = {(round(t[0], 3), round(t[1], 3)) for t in targets}
        if len(raw) < 20 or len(distinct) < 6:
            raise ModelError(
                f"camera {cid}: {len(raw)} samples at {len(distinct)} distinct targets; "
                "need at least 20 samples at 6 targets"
            )
        uv = np.array([r[0] for r in raw], float)
        hd = np.array([r[1] for r in raw], float).reshape(len(raw), len(terms))
        partial.feature_mean = tuple(uv.mean(axis=0))
        partial.feature_scale = tuple(np.maximum(uv.std(axis=0), 1e-6))
        partial.head_mean = list(hd.mean(axis=0)) if terms else []
        partial.head_scale = list(np.maximum(hd.std(axis=0), 1e-6)) if terms else []
        uv_n = (uv - partial.feature_mean) / partial.feature_scale
        hd_n = (hd - partial.head_mean) / partial.head_scale if terms else hd
        design = np.column_stack([poly_features(uv_n), hd_n])
        counts = defaultdict(int)
        for p in plan_ids:
            counts[p] += 1
        weights = np.array([1.0 / counts[p] for p in plan_ids])
        weights *= len(weights) / weights.sum()
        w = np.sqrt(weights)[:, None]
        penalty = np.sqrt(ridge * len(raw)) * np.eye(design.shape[1])
        penalty[0, 0] = 0.0  # no shrinkage of the intercept
        a = np.vstack([design * w, penalty])
        b = np.vstack([np.asarray(targets) * w, np.zeros((design.shape[1], 2))])
        partial.coefficients = np.linalg.lstsq(a, b, rcond=None)[0]
        cameras[cid] = partial
    if not cameras:
        raise ModelError("no observations to fit")
    return GazeModel(feature_set, cameras)
