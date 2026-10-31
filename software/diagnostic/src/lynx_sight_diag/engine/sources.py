"""Where the engine's feature samples come from.

* `SyntheticFeatures`: the deterministic simulated user (`simulation.py`). Samples for a time
  span are generated on request from what was presented, so it works at any speed, including
  the headless runner's simulated time.
* `CameraFeatures`: the real cameras through the diagnostic `Session` (capture once per camera,
  isolated processor threads). A board listener turns each `landmarks` result (or, without
  MediaPipe, each `eyes` result) into a `FeatureSample` in a bounded per-camera buffer.
  Untested on hardware so far.

Both answer `samples(start_ns, end_ns, context)` and `tracking(now_ns)`.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from .. import features as feat
from ..features import FeatureSample
from ..simulation import SyntheticUser
from .protocol import EngineError

BUFFER_SECONDS = 180


@dataclass(frozen=True)
class Context:
    """What the user was doing in a span: looking at a presentation or a baseline stage."""

    presentation: dict | None = None
    method: str | None = None  # "stationary" | "pursuit"
    baseline_stage: str | None = None


class SyntheticFeatures:
    synthetic = True

    def __init__(self, scenario: dict, seed: int):
        self.origin_ns = time.monotonic_ns()
        self.user = SyntheticUser(scenario, seed, self.origin_ns)
        self.cameras = list(self.user.cameras)
        self.feature_set = feat.IRIS_IN_EYE
        self.pose_source = "synthetic"
        self.descriptions = {c: f"synthetic user, {scenario['fps']:g} fps" for c in self.cameras}

    def samples(self, start_ns: int, end_ns: int, context: Context) -> list[FeatureSample]:
        if context.presentation is not None:
            gaze = self.user.gaze_for_presentation(context.presentation, context.method)
            return self.user.samples(start_ns, end_ns, gaze, "calibration")
        mode = "pose_range" if context.baseline_stage == "pose_range" else "still"
        return self.user.samples(start_ns, end_ns, self.user.fixate_centre, mode)

    def recent(self, now_ns: int, window_ms: float = 250) -> list[FeatureSample]:
        start = now_ns - int(window_ms * 1e6)
        return self.user.samples(start, now_ns, self.user.fixate_centre, "calibration")

    def camera_state(self, camera_id: str, now_ns: int) -> str:
        return "disconnected" if self.user.disconnected(camera_id, now_ns) else "synthetic"

    def fps(self, camera_id: str) -> float | None:
        return self.user.s["fps"]

    def close(self) -> None:
        pass


class CameraFeatures:
    synthetic = False

    def __init__(self, experiment_config: str):
        from .. import config as config_mod
        from ..config import ProcessorConfig
        from ..session import Session

        try:
            cfg = config_mod.load(experiment_config)
        except (OSError, ValueError) as exc:
            raise EngineError("source_failed", f"experiment config: {exc}") from exc
        processing = dict(cfg.processing)
        # Calibration wants every landmark result it can get; face/eyes stay the fallback.
        processing["landmarks"] = ProcessorConfig(True, 60.0, processing["landmarks"].options)
        processing["face"] = ProcessorConfig(True, 30.0, processing["face"].options)
        processing["eyes"] = ProcessorConfig(True, None, processing["eyes"].options)
        self.session = Session(cfg, processors=processing)
        self.cameras = list(self.session.cameras)
        self.descriptions = {
            cid: cam.worker.source.description for cid, cam in self.session.cameras.items()
        }
        self._lock = threading.Lock()
        self._buffers = {c: deque(maxlen=BUFFER_SECONDS * 120) for c in self.cameras}
        self._landmarks_ok = {c: False for c in self.cameras}
        self.session.board.listeners.append(self._on_result)
        self.origin_ns = time.monotonic_ns()
        self.session.start()
        self.feature_set = feat.IRIS_IN_EYE if self._mediapipe_available() else feat.PUPIL_OFFSET
        self.pose_source = (
            "landmarks-uncalibrated" if self.feature_set == feat.IRIS_IN_EYE else "eye-line-roll"
        )

    @staticmethod
    def _mediapipe_available() -> bool:
        from .. import models

        try:
            import mediapipe  # noqa: F401
        except ImportError:
            return False
        return models.locate("face_landmarker") is not None

    def _on_result(self, result) -> None:
        frame = result.frame
        t_ns = int(frame.t_device_ms * 1e6) if frame.t_device_ms else frame.t_capture_ns
        sample = None
        if result.processor == "landmarks" and self.feature_set == feat.IRIS_IN_EYE:
            if not result.ok:
                return
            face = self.session.board.latest(result.camera_id, "face")
            score = (
                face.data.best.score if face and face.ok and face.data and face.data.best else 1.0
            )
            if result.data is None:
                sample = feat.no_face(t_ns, result.camera_id)
            else:
                sample = feat.from_landmarks(t_ns, result.camera_id, result.data.points,
                                             (frame.width, frame.height),
                                             result.data.head_pose_deg, score)  # fmt: skip
        elif result.processor == "eyes" and self.feature_set == feat.PUPIL_OFFSET:
            if result.ok:
                sample = feat.from_eyes(t_ns, result.camera_id, result.data)
        if sample is not None:
            with self._lock:
                self._buffers[result.camera_id].append(sample)

    def samples(self, start_ns: int, end_ns: int, context: Context) -> list[FeatureSample]:
        # Features lag capture by the processing time: wait (bounded) until they cover `end`.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with self._lock:
                newest = [b[-1].t_ns for b in self._buffers.values() if b]
            if newest and min(newest) >= end_ns:
                break
            time.sleep(0.02)
        with self._lock:
            out = [s for b in self._buffers.values() for s in b if start_ns <= s.t_ns <= end_ns]
        out.sort(key=lambda s: (s.t_ns, s.camera_id))
        return out

    def recent(self, now_ns: int, window_ms: float = 250) -> list[FeatureSample]:
        start = now_ns - int(window_ms * 1e6)
        with self._lock:
            return [s for b in self._buffers.values() for s in b if s.t_ns >= start]

    def camera_state(self, camera_id: str, now_ns: int) -> str:
        from ..capture import State

        state = self.session.status()[camera_id].state
        if state is State.RUNNING:
            return "streaming"
        return "starting" if state in (State.OPENING, State.STOPPED) else "disconnected"

    def fps(self, camera_id: str) -> float | None:
        fps = self.session.status()[camera_id].fps
        return fps if fps > 0 else None

    def close(self) -> None:
        self.session.stop()


# --- tracking status and guidance --------------------------------------------------------------


def _m(value, reason="not measured"):
    if value is None:
        return {"status": "unavailable", "reason": reason}
    return {"status": "available", "value": float(value)}


def tracking_status(source, now_ns: int, neutral_scale: dict[str, float] | None = None) -> dict:
    recent = source.recent(now_ns)
    cameras = []
    guidance: list[str] = []
    ready = False
    for cid in source.cameras:
        own = [s for s in recent if s.camera_id == cid]
        latest = own[-1] if own else None
        state = source.camera_state(cid, now_ns)
        eyes = []
        for label in feat.EYES:
            e = latest.eye(label) if latest else None
            if latest is None or latest.face_confidence is None:
                eye_state = "no_face"
            elif e is None or e.iris is None:
                eye_state = "occluded"
            elif e.openness is not None and e.openness < 0.12:
                eye_state = "closed"
            else:
                eye_state = "tracked"
            eyes.append({
                "eye": label, "state": eye_state,
                "openness": _m(e.openness if e else None),
                "confidence": _m(e.confidence if e and e.iris is not None else None),
            })  # fmt: skip
        head = latest.head if latest else None
        both = all(e["state"] == "tracked" for e in eyes)
        ready = ready or (both and state in ("streaming", "synthetic"))
        latency = (now_ns - latest.t_ns) / 1e6 if latest else None
        cameras.append({
            "camera_id": cid,
            "state": state,
            "fps": _m(source.fps(cid)),
            "face_detected": bool(latest and latest.face_confidence is not None),
            "face_confidence": _m(latest.face_confidence if latest else None),
            "eyes": eyes,
            "head_pose": (
                {"yaw_deg": head.yaw_deg, "pitch_deg": head.pitch_deg,
                 "roll_deg": head.roll_deg or 0.0, "calibrated": False}
                if head and head.yaw_deg is not None and head.pitch_deg is not None else None
            ),
            "interocular_px": _m(head.scale_px if head else None),
            "face_centre_norm": [head.x, head.y] if head else None,
            "pipeline_latency_ms": _m(latency, "no recent result"),
        })  # fmt: skip
        guidance.extend(_guidance(latest, eyes, (neutral_scale or {}).get(cid)))
    ordered = [g for g in dict.fromkeys(guidance) if g != "good"]
    return {"t_ns": now_ns, "cameras": cameras, "guidance": ordered or ["good"], "ready": ready}


def _guidance(latest: FeatureSample | None, eyes: list[dict], neutral_scale: float | None):
    if latest is None or latest.face_confidence is None or latest.head is None:
        return ["face_not_found"]
    h = latest.head
    out = []
    # The cameras face the user: a face on the image's left means the user sits too far to
    # their right, so they should move left.
    if h.x < 0.3:
        out.append("move_left")
    elif h.x > 0.7:
        out.append("move_right")
    if h.y < 0.25:
        out.append("move_down")
    elif h.y > 0.7:
        out.append("move_up")
    if neutral_scale:
        rel = h.scale_px / neutral_scale
        if rel < 0.8:
            out.append("move_closer")
        elif rel > 1.25:
            out.append("move_back")
    if h.yaw_deg is not None and (abs(h.yaw_deg) > 20 or abs(h.pitch_deg or 0) > 20):
        out.append("turn_toward_screen")
    if any(e["state"] == "closed" for e in eyes):
        out.append("open_eyes")
    return out or ["good"]


def mean_level(source) -> float | None:
    """Mean image level, when the source has images (not the synthetic user)."""
    if source.synthetic:
        return None
    levels = []
    for cid in source.cameras:
        q = source.session.board.latest(cid, "quality")
        if q is not None and q.ok and q.data is not None:
            levels.append(q.data.mean)
    return float(np.mean(levels)) if levels else None
