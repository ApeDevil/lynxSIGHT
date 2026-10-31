"""The guided face/eye baseline: a personal reference in image measurements.

Stages (each a time span the UI guides the user through):

1. ``detect_stable``: a face and both eyes are found steadily (most samples, low jitter).
2. ``neutral``: frontal reference while looking at the screen centre: inter-eye distance, lid
   opening and iris-in-eye position per camera and eye.
3. ``pose_range``: slow head turns and moves while looking at the centre: the observed range of
   pose and position, and the part of it in which both eyes stay tracked.

Everything is an image measurement. The physical inter-eye distance and the eyes' distance
from the rig need calibrated cameras and are reported as unavailable. Nothing here identifies
a person, and no image is kept.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

import numpy as np

from .calibration import quality
from .features import EYES, FeatureSample

STAGES = ("detect_stable", "neutral", "pose_range")


def _metric(value, reason="no samples"):
    if value is None:
        return {"status": "unavailable", "reason": reason}
    return {"status": "available", "value": float(value)}


def _range(values) -> dict | None:
    values = [v for v in values if v is not None]
    if len(values) < 3:
        return None
    lo, hi = np.percentile(values, [2, 98])  # robust to the odd outlier
    return {"min": float(lo), "max": float(hi)}


def both_eyes(sample: FeatureSample) -> bool:
    return sample.face_confidence is not None and len(sample.tracked_eyes) == 2


class BaselineBuilder:
    def __init__(self, cameras: Sequence[str], pose_source: str):
        self.cameras = list(cameras)
        self.pose_source = pose_source
        self.stages: dict[str, dict] = {}
        self.samples: dict[str, list[FeatureSample]] = {}

    def add_stage(self, stage: str, samples: Sequence[FeatureSample]) -> dict:
        if stage not in STAGES:
            raise ValueError(f"unknown baseline stage {stage!r}")
        reasons = quality.classify(samples)
        good = [s for s, r in zip(samples, reasons, strict=True) if r is None and both_eyes(s)]
        n, k = len(samples), len(good)
        ok, message = self._judge(stage, samples, good)
        result = {"stage": stage, "samples": n, "accepted": k, "ok": ok, "message": message}
        self.stages[stage] = result
        self.samples[stage] = list(samples)
        return result

    def _judge(self, stage, samples, good) -> tuple[bool, str]:
        if not samples:
            return False, "no samples in this time span"
        share = len(good) / len(samples)
        if stage == "detect_stable":
            if share < 0.8:
                return False, f"both eyes tracked in {share:.0%} of samples; need 80 %"
            jitter = self._jitter(good)
            if jitter is not None and jitter > 0.02:
                return False, f"face position jitter {jitter:.3f} (image fraction); hold still"
            return True, f"stable: both eyes tracked in {share:.0%} of samples"
        if stage == "neutral":
            if len(good) < 20:
                return False, f"{len(good)} usable neutral samples; need 20"
            return True, f"{len(good)} neutral samples"
        coverage = self._coverage(good)
        yaw = coverage.get("yaw_deg")
        if yaw is None and coverage.get("face_x_norm") is None:
            return False, "no head movement observed"
        return True, f"tracked over {share:.0%} of the movement"

    @staticmethod
    def _jitter(samples) -> float | None:
        """Largest per-camera spread of the face position (the cameras see it at different
        image positions, so they are not pooled)."""
        spreads = []
        for cid in {s.camera_id for s in samples}:
            xs = [s.head.x for s in samples if s.head and s.camera_id == cid]
            if len(xs) > 3:
                spreads.append(float(np.std(xs)))
        return max(spreads) if spreads else None

    def _coverage(self, samples) -> dict:
        heads = [s.head for s in samples if s.head is not None]
        neutral = self._neutral_scale()
        return {
            "pose_source": self.pose_source,
            "yaw_deg": _range([h.yaw_deg for h in heads]),
            "pitch_deg": _range([h.pitch_deg for h in heads]),
            "roll_deg": _range([h.roll_deg for h in heads]),
            "face_x_norm": _range([h.x for h in heads]),
            "face_y_norm": _range([h.y for h in heads]),
            "scale_rel": _range(
                [
                    s.head.scale_px / neutral[s.camera_id]
                    for s in samples
                    if s.head is not None and neutral.get(s.camera_id)
                ]  # fmt: skip
            ),
        }

    def _neutral_scale(self) -> dict[str, float]:
        out = {}
        for cid in self.cameras:
            vals = [s.head.scale_px for s in self.samples.get("neutral", ())
                    if s.camera_id == cid and s.head and both_eyes(s)]  # fmt: skip
            if vals:
                out[cid] = float(np.median(vals))
        return out

    def neutral_openness(self) -> float | None:
        vals = [e.openness for s in self.samples.get("neutral", ()) if both_eyes(s)
                for e in s.eyes if e.openness is not None]  # fmt: skip
        return float(np.median(vals)) if vals else None

    def finish(self) -> dict:
        missing = [s for s in STAGES if s not in self.stages]
        if missing:
            raise ValueError(f"baseline stages not captured: {', '.join(missing)}")
        neutral = [s for s in self.samples["neutral"] if both_eyes(s)]
        cameras = []
        for cid in self.cameras:
            own = [s for s in neutral if s.camera_id == cid]
            scale = [s.head.scale_px for s in own if s.head]
            per_eye_open = defaultdict(list)
            per_eye_iris = defaultdict(list)
            for s in own:
                for e in s.eyes:
                    if e.openness is not None:
                        per_eye_open[e.eye].append(e.openness)
                    if e.iris is not None:
                        per_eye_iris[e.eye].append(e.iris)
            q1, q3 = np.percentile(scale, [25, 75]) if scale else (None, None)
            cameras.append(
                {
                    "camera_id": cid,
                    "interocular_px": _metric(np.median(scale) if scale else None),
                    "interocular_iqr_px": _metric(q3 - q1 if scale else None),
                    "openness": [
                        {
                            "eye": eye,
                            "value": _metric(
                                np.median(per_eye_open[eye]) if per_eye_open[eye] else None,
                                "lid opening not measured by this feature set",
                            ),
                        }
                        for eye in EYES
                    ],  # fmt: skip
                    "iris_in_eye": [
                        {
                            "eye": eye,
                            "x": float(np.median([p[0] for p in per_eye_iris[eye]])),
                            "y": float(np.median([p[1] for p in per_eye_iris[eye]])),
                        }
                        for eye in EYES
                        if per_eye_iris[eye]
                    ],  # fmt: skip
                    "face_centre_norm": (
                        [
                            float(np.median([s.head.x for s in own])),
                            float(np.median([s.head.y for s in own])),
                        ]
                        if own
                        else None
                    ),  # fmt: skip
                }
            )
        observed_samples = self.samples["pose_range"]
        reliable_samples = [s for s in observed_samples if both_eyes(s)]
        has_pose = any(s.head and s.head.yaw_deg is not None for s in observed_samples)
        has_open = any(e.openness is not None for s in neutral for e in s.eyes)
        features = [
            {"feature": "eye_landmarks", "valid": bool(neutral),
             "reason": "both eyes found in the neutral pose" if neutral else "no neutral data"},
            {"feature": "iris_in_eye", "valid": any(s.tracked_eyes for s in neutral),
             "reason": "iris located in the neutral pose"},
            {"feature": "lid_opening", "valid": has_open,
             "reason": "needed for blink rejection" if has_open
             else "not measured: blinks are detected from lost eyes only"},
            {"feature": "head_pose_angles", "valid": has_pose,
             "reason": "uncalibrated landmark-model angles" if has_pose
             else "not available from this feature set"},
            {"feature": "physical_scale", "valid": False,
             "reason": "needs calibrated camera geometry"},
        ]  # fmt: skip
        return {
            "stages": [self.stages[s] for s in STAGES],
            "cameras": cameras,
            "observed": self._coverage(observed_samples),
            "reliable": self._coverage(reliable_samples),
            "features": features,
            "inferred": {
                "interocular_mm": _metric(None, "needs calibrated camera geometry"),
                "eye_distance_from_rig_mm": _metric(None, "needs calibrated camera geometry"),
            },
        }
