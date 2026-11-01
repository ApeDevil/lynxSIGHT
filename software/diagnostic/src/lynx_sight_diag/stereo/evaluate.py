"""Offline evaluation of gaze models on a recorded calibration run.

`sight-diag calibrate --head-positions centre,left,...` stores every MediaPipe landmark result
(`landmarks.npz`) with the target and head position it belongs to. This module replays that
recording: it pairs the two cameras' results by capture time, triangulates, builds the user's face
template from the first head position, fits on one head position and tests on the others. Two
models are compared on exactly the same data:

* ``head-ray/v1`` (gaze.py): stereo, head-pose compensated;
* ``iris-in-eye/v1`` per camera, both eyes combined, linear and quadratic: the 2-D approach on
  main, uncompensated.

Errors are per target: the median prediction over the target's samples against the target.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import features
from .gaze import HeadRayModel, ScreenPlane, angular_error_deg, design
from .head import FaceTemplate, observe, pair_by_time, triangulate_face
from .rig import CAMERA_IDS, StereoRig

LANDMARKS_FILE = "landmarks.npz"


@dataclass
class Recording:
    """MediaPipe results of a calibration run, one row per (camera, result)."""

    t_ns: np.ndarray  # (N,) int64
    camera: np.ndarray  # (N,) index into CAMERA_IDS
    target: np.ndarray  # (N,) index into targets_px
    position: np.ndarray  # (N,) index into positions
    points: np.ndarray  # (N, 478, 2) float32, full-resolution pixels
    targets_px: np.ndarray  # (T, 2)
    positions: list[str]
    image_size: tuple[int, int]

    def save(self, directory: Path) -> Path:
        path = Path(directory) / LANDMARKS_FILE
        np.savez_compressed(
            path,
            t_ns=self.t_ns,
            camera=self.camera,
            target=self.target,
            position=self.position,
            points=self.points,
            targets_px=self.targets_px,
            positions=np.array(self.positions),
            image_size=np.array(self.image_size),
            camera_ids=np.array(CAMERA_IDS),
        )
        return path

    @classmethod
    def load(cls, directory: Path) -> Recording:
        path = Path(directory)
        path = path / LANDMARKS_FILE if path.is_dir() else path
        with np.load(path) as d:
            return cls(
                d["t_ns"],
                d["camera"],
                d["target"],
                d["position"],
                d["points"],
                d["targets_px"],
                [str(p) for p in d["positions"]],
                tuple(int(v) for v in d["image_size"]),
            )

    def rows(self, camera: int, target: int, position: int) -> np.ndarray:
        return np.flatnonzero(
            (self.camera == camera) & (self.target == target) & (self.position == position)
        )


def _stereo_observations(rec: Recording, rig: StereoRig, max_skew_ms: float):
    """{(position, target): [FacePoints]} from time-paired results."""
    faces = {}
    for p in range(len(rec.positions)):
        for t in range(len(rec.targets_px)):
            left = [(int(rec.t_ns[i]), rec.points[i]) for i in rec.rows(0, t, p)]
            right = [(int(rec.t_ns[i]), rec.points[i]) for i in rec.rows(1, t, p)]
            faces[(p, t)] = [
                triangulate_face(rig, pl, pr, tn, skew)
                for tn, skew, pl, pr in pair_by_time(left, right, max_skew_ms)
            ]
    return faces


def _errors(per_target_pred: dict, rec: Recording, screen: ScreenPlane, eye_rig) -> dict:
    errs = [np.linalg.norm(pred - rec.targets_px[t]) for t, pred in per_target_pred.items()]
    if not errs:
        return {"targets": 0}
    sx, sy = screen.mm_per_px
    mm = [
        np.linalg.norm((pred - rec.targets_px[t]) * (sx, sy)) for t, pred in per_target_pred.items()
    ]
    out = {
        "targets": len(errs),
        "median_px": round(float(np.median(errs)), 1),
        "p90_px": round(float(np.percentile(errs, 90)), 1),
        "median_mm": round(float(np.median(mm)), 1),
    }
    if eye_rig is not None:
        deg = [
            angular_error_deg(screen, eye_rig, pred[None], rec.targets_px[t][None])
            for t, pred in per_target_pred.items()
        ]
        out["median_deg"] = round(float(np.median(deg)), 2)
    return out


def evaluate(
    rec: Recording,
    rig: StereoRig,
    screen: ScreenPlane,
    train_position: int = 0,
    max_skew_ms: float = 20.0,
    degrees: tuple[int, ...] = (1, 2),
) -> tuple[dict, dict[int, HeadRayModel]]:
    """Returns (report, fitted head-ray models by degree)."""
    if rig.left.image_size != rec.image_size:
        rig = rig.scaled_to(rec.image_size)
    faces = _stereo_observations(rec, rig, max_skew_ms)
    report: dict = {
        "positions": rec.positions,
        "train_position": rec.positions[train_position],
        "targets": len(rec.targets_px),
        "screen": screen.to_dict(),
        "stereo_pairs": {
            rec.positions[p]: sum(len(faces[(p, t)]) for t in range(len(rec.targets_px)))
            for p in range(len(rec.positions))
        },
        "models": {},
    }
    train_faces = [f for t in range(len(rec.targets_px)) for f in faces[(train_position, t)]]
    try:
        template = FaceTemplate.from_faces(train_faces)
    except ValueError as exc:
        report["error"] = f"no face template: {exc}"
        return report, {}

    obs = {
        key: [o for f in fs if (o := observe(f, template)) is not None] for key, fs in faces.items()
    }
    eye_rig = None
    train_obs = [(o, t) for t in range(len(rec.targets_px)) for o in obs[(train_position, t)]]
    if train_obs:
        eye_rig = np.median([o.head.t for o, _ in train_obs], axis=0)
        report["eye_position_rig_mm"] = [round(float(v), 1) for v in eye_rig]
        report["head_fit_residual_mm"] = round(
            float(np.median([o.head.residual_mm for o, _ in train_obs])), 2
        )
        report["pair_skew_ms_median"] = round(
            float(np.median([abs(o.skew_ms) for o, _ in train_obs])), 1
        )

    head_angles = {}
    for p, name in enumerate(rec.positions):
        poses = [o.head for t in range(len(rec.targets_px)) for o in obs[(p, t)]]
        if poses:
            head_angles[name] = {
                "position_mm": [
                    round(float(v), 1) for v in np.median([h.t for h in poses], axis=0)
                ],
                "yaw_pitch_roll_deg": [
                    round(float(v), 1) for v in np.median([h.angles_deg() for h in poses], axis=0)
                ],
            }
    report["head"] = head_angles

    models = {}
    for degree in degrees:
        key = f"head-ray/v1 degree {degree}"
        try:
            model = HeadRayModel.fit(
                [o for o, _ in train_obs],
                np.array([rec.targets_px[t] for _, t in train_obs]),
                screen,
                template,
                degree,
            )
        except ValueError as exc:
            report["models"][key] = {"error": str(exc)}
            continue
        models[degree] = model
        result = {}
        for p, name in enumerate(rec.positions):
            per_target = {}
            for t in range(len(rec.targets_px)):
                preds = [q for o in obs[(p, t)] if (q := model.predict(o)) is not None]
                if preds:
                    per_target[t] = np.median(preds, axis=0)
            result[name] = _errors(per_target, rec, screen, eye_rig)
        result["loo_train"] = _loo_head_ray(train_obs, rec, screen, template, degree, eye_rig)
        report["models"][key] = result

    for c, cid in enumerate(CAMERA_IDS):
        report["models"][f"iris-in-eye/v1 {cid} (uncompensated)"] = _evaluate_2d(
            rec, c, cid, train_position, screen, eye_rig
        )
    return report, models


def _loo_head_ray(train_obs, rec, screen, template, degree, eye_rig) -> dict:
    """Leave one target out, within the training head position."""
    per_target = {}
    targets = sorted({t for _, t in train_obs})
    for held in targets:
        fit_on = [(o, t) for o, t in train_obs if t != held]
        try:
            m = HeadRayModel.fit(
                [o for o, _ in fit_on],
                np.array([rec.targets_px[t] for _, t in fit_on]),
                screen,
                template,
                degree,
            )
        except ValueError:
            continue
        preds = [q for o, t in train_obs if t == held and (q := m.predict(o)) is not None]
        if preds:
            per_target[held] = np.median(preds, axis=0)
    return _errors(per_target, rec, screen, eye_rig)


def _iris_2d(rec: Recording, rows: np.ndarray, cid: str):
    samples = [
        features.from_landmarks(int(rec.t_ns[i]), cid, rec.points[i], rec.image_size, None)
        for i in rows
    ]
    return samples


def _evaluate_2d(rec, camera, cid, train_position, screen, eye_rig) -> dict:
    all_samples = {
        (p, t): _iris_2d(rec, rec.rows(camera, t, p), cid)
        for p in range(len(rec.positions))
        for t in range(len(rec.targets_px))
    }
    train = [s for t in range(len(rec.targets_px)) for s in all_samples[(train_position, t)]]
    offsets = features.eye_offsets(train)

    def target_medians(p):
        out = {}
        for t in range(len(rec.targets_px)):
            vals = [v for s in all_samples[(p, t)] if (v := features.combined_iris(s, offsets))]
            if len(vals) >= 3:
                out[t] = np.median(vals, axis=0)
        return out

    train_med = target_medians(train_position)
    if len(train_med) < 6:
        return {"error": "fewer than 6 targets with iris data"}
    keys = sorted(train_med)
    X = np.array([train_med[t] for t in keys])
    Y = rec.targets_px[keys]
    result = {}
    for degree in (1, 2):
        A = design(X, degree)
        coef = np.linalg.lstsq(A, Y, rcond=None)[0]
        loo = []
        for i in range(len(keys)):
            keep = np.arange(len(keys)) != i
            c = np.linalg.lstsq(A[keep], Y[keep], rcond=None)[0]
            loo.append(np.linalg.norm(A[i] @ c - Y[i]))
        entry = {"loo_train": {"median_px": round(float(np.median(loo)), 1)}}
        for p, name in enumerate(rec.positions):
            med = target_medians(p)
            pred = {t: (design(v[None], degree) @ coef)[0] for t, v in med.items()}
            entry[name] = _errors(pred, rec, screen, eye_rig)
        result[f"degree {degree}"] = entry
    return result


def write_report(report: dict, directory: Path) -> Path:
    path = Path(directory) / "gaze_evaluation.json"
    path.write_text(json.dumps(report, indent=2))
    return path
