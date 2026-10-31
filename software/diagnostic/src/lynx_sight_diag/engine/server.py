"""Request dispatch of `sight-engine`. One `Engine` per process; state lives in memory only.

The engine keeps the collected observations of the current source between requests (plans
are referred to by id) and never writes them to disk: profiles are the desktop core's, and
recordings are an explicit `sight-diag record` action.
"""

from __future__ import annotations

import sys
import time
import traceback
from collections.abc import Callable

import numpy as np

from .. import __version__
from .. import features as feat
from ..baseline import BaselineBuilder
from ..calibration import alignment, recalibration, targets, validation
from ..calibration.alignment import Collection, Observation
from ..calibration.model import KIND, GazeModel, ModelError
from ..calibration.model import fit as fit_model
from . import protocol
from .protocol import EngineError
from .sources import CameraFeatures, Context, SyntheticFeatures, mean_level, tracking_status


def _landmarks_installed() -> bool:
    try:
        import mediapipe  # noqa: F401
    except ImportError:
        return False
    return True


class Engine:
    def __init__(self):
        self.source = None
        self._reset()

    def _reset(self):
        self.plans: dict[str, dict] = {}
        self.collections: dict[str, Collection] = {}
        self.baseline: BaselineBuilder | None = None
        self.neutral_openness: float | None = None
        self.neutral_scale: dict[str, float] = {}
        self._plan_counter = 0

    # --- dispatch ----------------------------------------------------------------------------

    def handle(self, request: dict) -> dict:
        if request.get("protocol") != protocol.PROTOCOL_VERSION:
            raise EngineError(
                "protocol_mismatch",
                f"engine speaks protocol {protocol.PROTOCOL_VERSION}, "
                f"got {request.get('protocol')}",
            )
        handler: Callable[[dict], dict] | None = getattr(self, f"on_{request['type']}", None)
        if handler is None:
            raise EngineError("invalid_request", f"unknown request type {request['type']!r}")
        try:
            return handler(request)
        except KeyError as exc:
            raise EngineError("invalid_request", f"missing field {exc}") from exc

    def _need_source(self):
        if self.source is None:
            raise EngineError("no_source", "open a source first")
        return self.source

    def on_hello(self, r: dict) -> dict:
        return {
            "type": "hello",
            "engine_version": __version__,
            "capabilities": {
                "cameras": True,
                "landmarks": _landmarks_installed(),
                "feature_sets": list(feat.FEATURE_SETS),
                "model_kinds": [KIND],
            },
        }

    def on_open_source(self, r: dict) -> dict:
        self.on_close_source(r)
        spec = r["source"]
        if spec["kind"] == "synthetic":
            self.source = SyntheticFeatures(spec["scenario"], spec["seed"])
        elif spec["kind"] == "cameras":
            self.source = CameraFeatures(spec["experiment_config"])
        else:
            raise EngineError("invalid_request", f"unknown source kind {spec['kind']!r}")
        s = self.source
        return {
            "type": "source_opened",
            "cameras": [
                {"camera_id": c, "description": s.descriptions[c], "eyes": list(feat.EYES)}
                for c in s.cameras
            ],
            "synthetic": s.synthetic,
            "clock_origin_ns": s.origin_ns,
            "feature_set": s.feature_set,
        }

    def on_close_source(self, r: dict) -> dict:
        if self.source is not None:
            self.source.close()
        self.source = None
        self._reset()
        return {"type": "ok"}

    def on_tracking_status(self, r: dict) -> dict:
        source = self._need_source()
        status = tracking_status(source, time.monotonic_ns(), self.neutral_scale)
        level = mean_level(source)
        status["mean_image_level"] = (
            {"status": "available", "value": level}
            if level is not None
            else {
                "status": "unavailable",
                "reason": "synthetic source" if source.synthetic else "no quality result yet",
            }
        )
        return {"type": "tracking_status", "status": status}

    def on_capture_baseline_stage(self, r: dict) -> dict:
        source = self._need_source()
        span = r["span"]
        if self.baseline is None:
            self.baseline = BaselineBuilder(source.cameras, source.pose_source)
        samples = source.samples(
            span["start_ns"], span["end_ns"], Context(baseline_stage=r["stage"])
        )
        try:
            result = self.baseline.add_stage(r["stage"], samples)
        except ValueError as exc:
            raise EngineError("invalid_request", str(exc)) from exc
        return {"type": "baseline_stage", "result": result}

    def on_finish_baseline(self, r: dict) -> dict:
        if self.baseline is None:
            raise EngineError("insufficient_data", "no baseline stage captured")
        try:
            baseline = self.baseline.finish()
        except ValueError as exc:
            raise EngineError("insufficient_data", str(exc)) from exc
        self.neutral_openness = self.baseline.neutral_openness()
        self.neutral_scale = {
            c["camera_id"]: c["interocular_px"]["value"]
            for c in baseline["cameras"]
            if c["interocular_px"]["status"] == "available"
        }
        return {"type": "baseline", "baseline": baseline}

    def on_plan(self, r: dict) -> dict:
        self._need_source()
        self._plan_counter += 1
        plan_id = f"plan-{self._plan_counter}"
        try:
            plan = targets.make_plan(plan_id, r["request"])
        except ValueError as exc:
            raise EngineError("invalid_request", str(exc)) from exc
        self.plans[plan_id] = plan
        return {"type": "plan", "plan": plan}

    def on_submit_presentation(self, r: dict) -> dict:
        source = self._need_source()
        presentation = r["presentation"]
        plan = self.plans.get(presentation["plan_id"])
        if plan is None:
            raise EngineError("unknown_plan", f"no plan {presentation['plan_id']!r}")
        spans = presentation["spans"]
        if not spans or not presentation["frames"]:
            raise EngineError("insufficient_data", "the presentation has no frames")
        method = plan["body"]["method"]
        start = min(s["start_ns"] for s in spans)
        end = max(s["end_ns"] for s in spans)
        samples = source.samples(start, end, Context(presentation, method))
        collection = alignment.align(
            plan, presentation, samples, neutral_openness=self.neutral_openness
        )
        self.collections[plan["plan_id"]] = collection
        return {"type": "collection", "summary": collection.summary}

    # --- models ----------------------------------------------------------------------------

    def _collections(self, ids: list[str], purpose: str) -> list[Collection]:
        out = []
        for plan_id in ids:
            c = self.collections.get(plan_id)
            if c is None:
                raise EngineError("unknown_plan", f"no collected presentation for {plan_id!r}")
            if c.plan["purpose"] != purpose:
                raise EngineError(
                    "invalid_request",
                    f"{plan_id} was collected for {c.plan['purpose']}, not {purpose}",
                )
            out.append(c)
        return out

    def _model(self, contract: dict) -> GazeModel:
        try:
            return GazeModel.from_contract(contract, self._need_source().feature_set)
        except ModelError as exc:
            raise EngineError("model_incompatible", str(exc)) from exc

    @staticmethod
    def _lag(collections: list[Collection]) -> float | None:
        lags = [c.lag_ms for c in collections if c.lag_ms is not None]
        return float(np.median(lags)) if lags else None

    def on_fit(self, r: dict) -> dict:
        source = self._need_source()
        fit_c = self._collections(r["fit_plans"], "fit")
        val_c = self._collections(r["validation_plans"], "validation")
        observations = [o for c in fit_c for o in c.observations]
        try:
            model = fit_model(observations, source.feature_set)
        except ModelError as exc:
            raise EngineError("insufficient_data", str(exc)) from exc
        scale = r["scale"]
        return {
            "type": "fit",
            "result": {
                "model": model.to_contract(),
                "training": validation.training_summary(model, fit_c, scale),
                "validation": validation.evaluate(
                    model, val_c, scale, self._lag(list(self.collections.values()))
                ),
                "coverage": coverage(observations, source.pose_source),
            },
        }

    def on_evaluate(self, r: dict) -> dict:
        model = self._model(r["model"])
        val_c = self._collections(r["validation_plans"], "validation")
        # Latency is a property of the setup: take it from any pursuit in this session.
        report = validation.evaluate(
            model, val_c, r["scale"], self._lag(list(self.collections.values()))
        )
        return {"type": "validation", "report": report}

    def on_recalibrate(self, r: dict) -> dict:
        current = self._model(r["current"])
        fit_c = self._collections(r["fit_plans"], "fit")
        val_c = self._collections(r["validation_plans"], "validation")
        try:
            candidate = recalibration.fit_correction(
                current, [o for c in fit_c for o in c.observations]
            )
        except ModelError as exc:
            raise EngineError("insufficient_data", str(exc)) from exc
        comparison = recalibration.compare(current, candidate, val_c, r["scale"])
        return {
            "type": "recalibration",
            "result": {"candidate": candidate.to_contract(), "comparison": comparison},
        }

    def on_compare(self, r: dict) -> dict:
        current, candidate = self._model(r["current"]), self._model(r["candidate"])
        val_c = self._collections(r["validation_plans"], "validation")
        return {
            "type": "comparison",
            "comparison": recalibration.compare(current, candidate, val_c, r["scale"]),
        }

    def on_propose_correction(self, r: dict) -> dict:
        source = self._need_source()
        model = self._model(r["current"])
        observations = []
        for obs in r["observations"]:
            t, target = obs["t_ns"], obs["target"]
            # What the user looked at for the half second before confirming.
            shown = {
                "plan_id": "trusted", "spans": [{"start_ns": t - 500_000_000, "end_ns": t}],
                "frames": [{"t_ns": t - 500_000_000, "position": target, "target_index": 0}],
            }  # fmt: skip
            samples = source.samples(t - 150_000_000, t, Context(shown, "stationary"))
            reasons = alignment.quality.classify(samples, neutral_openness=self.neutral_openness)
            observations += [
                Observation(s, (target["x"], target["y"]), 0, "trusted", "fit", "stationary")
                for s, why in zip(samples, reasons, strict=True)
                if why is None
            ]
        candidate, used, reason = recalibration.propose_offset(model, observations)
        return {
            "type": "correction_proposal",
            "proposal": {
                "candidate": candidate.to_contract() if candidate else None,
                "observations_used": used,
                "reason": reason,
            },
        }

    def on_shutdown(self, r: dict) -> dict:
        self.on_close_source(r)
        return {"type": "ok"}


def _range(values):
    values = [v for v in values if v is not None]
    if len(values) < 3:
        return None
    lo, hi = np.percentile(values, [2, 98])
    return {"min": float(lo), "max": float(hi)}


def coverage(observations: list[Observation], pose_source: str) -> dict:
    """Head poses and positions the fit data covered: outside them the model extrapolates."""
    heads = [o.sample.head for o in observations if o.sample.head is not None]
    return {
        "pose_source": pose_source,
        "yaw_deg": _range([h.yaw_deg for h in heads]),
        "pitch_deg": _range([h.pitch_deg for h in heads]),
        "roll_deg": _range([h.roll_deg for h in heads]),
        "face_x_norm": _range([h.x for h in heads]),
        "face_y_norm": _range([h.y for h in heads]),
        "scale_rel": None,
    }


def serve(stdin=sys.stdin, stdout=sys.stdout) -> int:
    engine = Engine()
    while True:
        request_id, kind = 0, None
        try:
            request = protocol.read_message(stdin)
            if request is None:
                engine.on_close_source({})
                return 0
            request_id, kind = int(request.get("id", 0)), request.get("type")
            response = engine.handle(request)
        except EngineError as exc:
            response = protocol.error(exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - the process must answer, not die
            traceback.print_exc(file=sys.stderr)
            response = protocol.error("internal", f"{type(exc).__name__}: {exc}")
        protocol.write_message(stdout, protocol.envelope(request_id, response))
        if kind == "shutdown" and response["type"] == "ok":
            return 0


def main() -> int:
    print(f"sight-engine {__version__}, protocol {protocol.PROTOCOL_VERSION}", file=sys.stderr)
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
