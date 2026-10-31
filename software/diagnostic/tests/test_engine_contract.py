"""`sight-engine` speaks the contract: every request and response of a complete synthetic
workflow is validated against the JSON Schemas generated from the desktop's contract types."""

import io
import json
from pathlib import Path

import pytest
from calib_helpers import SCALE, present, pursuit_request, stationary_request
from jsonschema import Draft202012Validator

from lynx_sight_diag.engine import protocol
from lynx_sight_diag.engine.server import Engine, serve
from lynx_sight_diag.simulation import default_scenario

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def validator(name):
    return Draft202012Validator(json.loads((CONTRACTS / "schemas" / name).read_text()))


REQUEST = validator("engine-request.v1.schema.json")
RESPONSE = validator("engine-response.v1.schema.json")
PROFILE = validator("profile.v1.schema.json")


class Client:
    def __init__(self):
        self.engine = Engine()
        self.next_id = 0

    def __call__(self, type_, **body):
        self.next_id += 1
        request = protocol.envelope(self.next_id, {"type": type_, **body})
        REQUEST.validate(request)
        try:
            response = self.engine.handle(request)
        except protocol.EngineError as exc:
            response = protocol.error(exc.code, exc.message)
        message = json.loads(json.dumps(protocol.envelope(self.next_id, response), allow_nan=False))
        RESPONSE.validate(message)
        return message


def open_synthetic(client, scenario=None, seed=3):
    r = client(
        "open_source",
        source={"kind": "synthetic", "scenario": scenario or default_scenario(), "seed": seed},
    )
    assert r["type"] == "source_opened" and r["synthetic"]
    return r["clock_origin_ns"]


def run_plan(client, request, t):
    plan = client("plan", request=request)["plan"]
    presentation = present(plan, t)
    summary = client("submit_presentation", presentation=presentation)["summary"]
    return plan, summary, presentation["spans"][-1]["end_ns"] + 200_000_000


def test_default_scenario_matches_the_contract_default():
    fixture = json.loads((CONTRACTS / "fixtures" / "synthetic-scenario.default.json").read_text())
    assert default_scenario() == fixture


def test_the_v1_profile_fixture_matches_the_schema():
    PROFILE.validate(json.loads((CONTRACTS / "fixtures" / "profile-v1.json").read_text()))


def test_complete_synthetic_workflow_through_the_protocol():
    c = Client()
    hello = c("hello", client="test")
    assert hello["engine_version"] and "poly2-head-linear" in hello["capabilities"]["model_kinds"]
    t = open_synthetic(c) + 1_000_000_000
    status = c("tracking_status")["status"]
    assert [cam["camera_id"] for cam in status["cameras"]] == ["cam_left", "cam_right"]
    assert status["mean_image_level"]["status"] == "unavailable"
    for stage in ("detect_stable", "neutral", "pose_range"):
        r = c(
            "capture_baseline_stage", stage=stage, span={"start_ns": t, "end_ns": t + 3_000_000_000}
        )
        assert r["result"]["ok"], r
        t += 3_500_000_000
    baseline = c("finish_baseline")["baseline"]
    assert baseline["inferred"]["interocular_mm"]["status"] == "unavailable"
    assert baseline["reliable"]["yaw_deg"]["max"] > 5

    grid, s1, t = run_plan(c, stationary_request(), t)
    spiral, s2, t = run_plan(c, pursuit_request(), t)
    val_layout = {"layout": "validation_offset_grid", "cols": 4, "rows": 3, "margin": 0.08}
    val, s3, t = run_plan(c, stationary_request("validation", val_layout), t)
    assert s1["targets_usable"] == 12 and s2["following_fraction"]["value"] > 0.7

    fit = c(
        "fit",
        fit_plans=[grid["plan_id"], spiral["plan_id"]],
        validation_plans=[val["plan_id"]],
        scale=SCALE,
    )
    result = fit["result"]
    assert result["validation"]["source"] == "independent"
    assert result["validation"]["latency_ms"]["status"] == "available"
    model = result["model"]

    again = c("evaluate", model=model, validation_plans=[val["plan_id"]], scale=SCALE)["report"]
    assert again == result["validation"]

    quick, _, t = run_plan(
        c, stationary_request(layout={"layout": "centre_edges_corners", "margin": 0.1}), t
    )
    recal = c(
        "recalibrate",
        current=model,
        fit_plans=[quick["plan_id"]],
        validation_plans=[val["plan_id"]],
        scale=SCALE,
    )
    assert recal["result"]["comparison"]["verdict"] in (
        "better",
        "equivalent",
        "worse",
        "inconclusive",
    )
    cmp = c(
        "compare",
        current=model,
        candidate=recal["result"]["candidate"],
        validation_plans=[val["plan_id"]],
        scale=SCALE,
    )
    assert cmp["comparison"]["verdict"] == recal["result"]["comparison"]["verdict"]

    obs = [{"t_ns": t + k * 600_000_000, "display_stable_id": None, "target": {"x": 0.3, "y": 0.4},
            "source": "explicit_confirmation"} for k in range(1, 8)]  # fmt: skip
    proposal = c("propose_correction", current=model, observations=obs)["proposal"]
    assert proposal["observations_used"] > 0
    assert c("shutdown")["type"] == "ok"


def test_errors_are_typed():
    c = Client()
    assert c("tracking_status")["code"] == "no_source"
    t = open_synthetic(c) + 10**9
    assert (
        c(
            "submit_presentation",
            presentation={
                "plan_id": "nope",
                "frames": [],
                "spans": [],
                "completed": True,
                "clock": "monotonic",
                "clock_uncertainty_ms": None,
            },
        )["code"]
        == "unknown_plan"
    )
    grid, _, t = run_plan(c, stationary_request(), t)
    r = c("fit", fit_plans=[grid["plan_id"]], validation_plans=[grid["plan_id"]], scale=SCALE)
    assert r["code"] == "invalid_request" and "validation" in r["message"]
    few, _, t = run_plan(
        c, stationary_request(layout={"layout": "points", "points": [{"x": 0.5, "y": 0.5}]}), t
    )
    assert (
        c("fit", fit_plans=[few["plan_id"]], validation_plans=[], scale=SCALE)["code"]
        == "insufficient_data"
    )
    bogus = {
        "kind": "other",
        "kind_version": 1,
        "feature_set": "iris-in-eye/v1",
        "engine_version": "x",
        "parameters": {},
    }
    assert (
        c("evaluate", model=bogus, validation_plans=[], scale=SCALE)["code"] == "model_incompatible"
    )
    assert c("finish_baseline")["code"] == "insufficient_data"
    bad = c.engine.handle  # protocol mismatch, without the schema check of Client
    with pytest.raises(protocol.EngineError) as exc:
        bad({"protocol": 2, "id": 1, "type": "hello"})
    assert exc.value.code == "protocol_mismatch"


def test_camera_disconnection_shows_in_tracking_and_rejects_data():
    scenario = default_scenario()
    scenario["disconnects"] = [{"camera_id": "cam_right", "after_ms": 0, "duration_ms": 3_600_000}]
    c = Client()
    t = open_synthetic(c, scenario) + 10**9
    status = c("tracking_status")["status"]
    right = next(cam for cam in status["cameras"] if cam["camera_id"] == "cam_right")
    assert right["state"] == "disconnected" and not right["face_detected"]
    assert status["ready"]  # the other camera still tracks both eyes
    grid, summary, _ = run_plan(c, stationary_request(), t)
    assert summary["targets_usable"] == 12  # one camera is enough


def test_serve_frames_lines_and_survives_garbage():
    lines = [
        json.dumps({"protocol": 1, "id": 1, "type": "hello", "client": "t"}),
        "not json",
        json.dumps({"protocol": 1, "id": 3, "type": "warp_drive"}),
        json.dumps({"protocol": 1, "id": 4, "type": "shutdown"}),
        json.dumps({"protocol": 1, "id": 5, "type": "hello", "client": "never read"}),
    ]
    out = io.StringIO()
    assert serve(io.StringIO("\n".join(lines) + "\n"), out) == 0
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r["type"] for r in replies] == ["hello", "error", "error", "ok"]
    assert replies[1]["code"] == "invalid_request" and replies[2]["id"] == 3
    for r in replies:
        RESPONSE.validate(r)


def test_synthetic_runs_are_reproducible():
    def run():
        c = Client()
        t = open_synthetic(c, seed=9)
        # Relative to the engine's origin, so two engines see the same simulated user.
        _, summary, _ = run_plan(c, pursuit_request(), t + 10**9)
        return summary

    assert run() == run()
