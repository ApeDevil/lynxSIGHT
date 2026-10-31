"""Calibration engine on deterministic synthetic data (no camera, no display).

Synthetic success shows that the algorithms recover a known truth; it is not a measurement of
real gaze accuracy."""

import numpy as np
import pytest
from calib_helpers import (
    SCALE,
    SCALE_PX_ONLY,
    collect,
    full_run,
    pursuit_request,
    stationary_request,
)  # fmt: skip

from lynx_sight_diag import features as feat
from lynx_sight_diag.calibration import model as gaze_model
from lynx_sight_diag.calibration import quality, recalibration, targets, validation
from lynx_sight_diag.calibration.alignment import Observation
from lynx_sight_diag.features import EyeFeature, FeatureSample, HeadState
from lynx_sight_diag.simulation import SyntheticUser, default_scenario, ideal_scenario


def fitted(scenario, seed=1):
    user, c = full_run(scenario, seed)
    m = gaze_model.fit(c["grid"].observations + c["spiral"].observations, feat.IRIS_IN_EYE)
    return user, c, m


# --- targets -----------------------------------------------------------------------------------


def test_stationary_layout_covers_centre_edges_and_corners():
    pts = targets.stationary_points({"layout": "centre_edges_corners", "margin": 0.05})
    assert pts[0] == (0.5, 0.5) and len(pts) == 9
    assert {(0.05, 0.05), (0.95, 0.95), (0.5, 0.05), (0.05, 0.5)} <= set(pts)


def test_validation_points_never_coincide_with_fit_points():
    fit = set(targets.stationary_points({"layout": "grid", "cols": 4, "rows": 3, "margin": 0.08}))
    val = targets.stationary_points(
        {"layout": "validation_offset_grid", "cols": 4, "rows": 3, "margin": 0.08}
    )
    assert len(val) == 6 and not fit & set(val)


@pytest.mark.parametrize(
    "trajectory",
    [
        {"trajectory": "spiral", "turns": 3, "margin": 0.08},
        {"trajectory": "sweeps", "rows": 3, "cols": 3, "margin": 0.1},
        {"trajectory": "perimeter", "margin": 0.05},
    ],
)
def test_pursuit_paths_move_at_constant_screen_speed_inside_the_margin(trajectory):
    plan = targets.make_plan("p", pursuit_request(trajectory=trajectory, speed=0.2))
    path = plan["body"]["path"][1:]  # after the lead-in sample
    xy = np.array([[p["position"]["x"], p["position"]["y"]] for p in path])
    t = np.array([p["t_ms"] for p in path])
    m = trajectory["margin"]
    assert xy.min() >= m - 1e-9 and xy.max() <= 1 - m + 1e-9
    speed = np.hypot(np.diff(xy[:, 0]) * 16 / 9, np.diff(xy[:, 1])) / (np.diff(t) / 1000)
    # Constant except where the path turns a corner within one step.
    assert np.median(speed) == pytest.approx(0.2, rel=0.02)
    assert path[0]["t_ms"] == 800


def test_off_screen_targets_are_refused():
    with pytest.raises(ValueError):
        targets.make_plan(
            "p", stationary_request(layout={"layout": "points", "points": [{"x": 1.2, "y": 0.5}]})
        )


# --- quality -----------------------------------------------------------------------------------


def _sample(t_ms, openness=0.28, conf=0.9, iris=(0.0, 0.0), face=0.9):
    eyes = tuple(EyeFeature(e, iris, openness, conf) for e in feat.EYES)
    return FeatureSample(int(t_ms * 1e6), "cam_left", face, eyes, HeadState(0.5, 0.5, 100))


def test_quality_rejects_missing_low_confidence_and_pads_blinks():
    samples = [_sample(t) for t in range(0, 1000, 20)]
    samples[10] = _sample(200, openness=0.05)  # a closed-eye frame
    samples[30] = _sample(600, conf=0.2)
    samples[40] = FeatureSample(int(800e6), "cam_left", None, (), None)
    reasons = quality.classify(samples)
    assert reasons[10] == quality.BLINK
    # 20 ms apart, padded by 100 ms: samples 5..15 belong to the blink.
    assert reasons[4] is None and reasons[5] == quality.BLINK and reasons[15] == quality.BLINK
    assert reasons[16] is None
    assert reasons[30] == quality.LOW_CONFIDENCE and reasons[40] == quality.MISSING
    # Relative to a personal neutral opening, a squint is not a blink.
    squint = [_sample(0, openness=0.1)]
    assert quality.classify(squint) == [quality.BLINK]
    assert quality.classify(squint, neutral_openness=0.15) == [None]


# --- alignment ---------------------------------------------------------------------------------


def test_stationary_alignment_skips_settling_and_pauses():
    user = SyntheticUser(ideal_scenario(), 1, 0)
    plan = targets.make_plan("s", stationary_request())
    collection, _ = collect(user, plan, 10**9, pause=(5000, 3000))
    s = collection.summary
    assert s["targets_usable"] == s["targets_total"] == 12
    assert s["rejected"]["settling"] > 0 and s["rejected"]["outside_presentation"] > 0
    assert all(o.target_index is not None for o in collection.observations)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_pursuit_lag_is_recovered(seed):
    scenario = default_scenario()
    user = SyntheticUser(scenario, seed, 0)
    plan = targets.make_plan("p", pursuit_request())
    collection, _ = collect(user, plan, 10**9)
    true_lag = scenario["display_latency_ms"] + scenario["pursuit_lag_ms"]
    assert abs(collection.lag_ms - true_lag) <= 30
    assert collection.summary["estimated_lag_ms"]["value"] == collection.lag_ms


def test_look_aways_during_pursuit_are_rejected():
    scenario = ideal_scenario()
    scenario["pursuit_lapse_fraction"] = 0.2
    user = SyntheticUser(scenario, 4, 0)
    plan = targets.make_plan("p", pursuit_request())
    collection, _ = collect(user, plan, 10**9)
    following = collection.summary["following_fraction"]["value"]
    assert 0.6 < following < 0.95
    # Accepted samples are (almost) never taken during a look-away.
    in_lapse = sum(
        user._active("lapse", o.sample.t_ns) is not None for o in collection.observations
    )
    assert in_lapse / len(collection.observations) < 0.03


def test_too_little_pursuit_data_is_reported_not_guessed():
    scenario = ideal_scenario()
    scenario["disconnects"] = [
        {"camera_id": c, "after_ms": 0, "duration_ms": 1e9} for c in ("cam_left", "cam_right")
    ]
    user = SyntheticUser(scenario, 1, 0)
    collection, _ = collect(user, targets.make_plan("p", pursuit_request()), 10**9)
    assert collection.observations == []
    assert collection.summary["estimated_lag_ms"]["status"] == "unavailable"
    assert collection.summary["samples_total"] == 0


# --- model and validation ----------------------------------------------------------------------


def test_ideal_user_is_fitted_accurately():
    _, c, m = fitted(ideal_scenario())
    report = validation.evaluate(m, [c["validation"]], SCALE)
    assert report["source"] == "independent" and report["targets"] == 6
    assert report["accuracy"]["median"]["px"]["value"] < 15
    assert report["accuracy"]["p90"]["deg"]["value"] < 0.6


def test_realistic_user_fit_is_deterministic_and_bounded():
    _, c1, m1 = fitted(default_scenario(), seed=5)
    _, c2, m2 = fitted(default_scenario(), seed=5)
    r1 = validation.evaluate(m1, [c1["validation"]], SCALE)
    r2 = validation.evaluate(m2, [c2["validation"]], SCALE)
    assert r1 == r2
    assert r1["accuracy"]["median"]["px"]["value"] < 80
    acc = r1["acceptance"]
    assert acc["accepted"] < acc["total"] and acc["rejected"]["blink"] > 0
    assert r1["regions"] and all(reg["samples"] > 0 for reg in r1["regions"])


def test_one_eye_suffices_after_fitting():
    _, c, m = fitted(ideal_scenario())
    o = c["validation"].observations[0]
    left_only = FeatureSample(o.sample.t_ns, o.sample.camera_id, o.sample.face_confidence,
                              (o.sample.eyes[0], EyeFeature("image_right", None, None, 0.0)),
                              o.sample.head)  # fmt: skip
    both, one = np.array(m.predict(o.sample)), np.array(m.predict(left_only))
    assert np.hypot(*(both - one)) < 0.025  # the eyes' gains differ slightly


def test_model_contract_round_trip_and_compatibility_checks():
    _, _, m = fitted(ideal_scenario())
    contract = m.to_contract()
    back = gaze_model.GazeModel.from_contract(contract, feat.IRIS_IN_EYE)
    eyes = tuple(EyeFeature(e, (0.01, 0.02), 0.28, 0.9) for e in feat.EYES)
    s = FeatureSample(0, "cam_left", 0.9, eyes, HeadState(0.5, 0.45, 180, 0.0, 0.0, 0.0))
    assert back.predict(s) == m.predict(s)
    with pytest.raises(gaze_model.ModelError, match="fitted on"):
        gaze_model.GazeModel.from_contract(contract, feat.PUPIL_OFFSET)
    broken = {
        **contract,
        "parameters": {**contract["parameters"], "cameras": {"cam_left": {"coefficients": [[1]]}}},
    }
    with pytest.raises(gaze_model.ModelError):
        gaze_model.GazeModel.from_contract(broken)
    with pytest.raises(gaze_model.ModelError):
        gaze_model.GazeModel.from_contract({**contract, "kind_version": 99})


def test_fit_refuses_too_few_targets():
    _, c = full_run(ideal_scenario())
    few = [o for o in c["grid"].observations if o.target_index in (0, 1, 2)]
    with pytest.raises(gaze_model.ModelError, match="distinct targets"):
        gaze_model.fit(few, feat.IRIS_IN_EYE)


def test_metrics_of_a_known_offset_in_every_unit():
    class Shifted:  # a "model" that is exactly 0.01 width to the right of every target
        def predict(self, sample):
            return (sample.t_ns / 1e12 + 0.01, 0.5)

    obs = [Observation(FeatureSample(int(x * 1e12), "c", 1.0, (), None), (x, 0.5), i, "v",
                       "validation", "stationary")
           for i, x in enumerate(np.linspace(0.1, 0.9, 30))]  # fmt: skip
    from lynx_sight_diag.calibration.alignment import Collection

    col = Collection({"plan_id": "v", "purpose": "validation"}, obs, {}, None, [None] * 30)
    report = validation.evaluate(Shifted(), [col], SCALE)
    acc = report["accuracy"]
    assert acc["median"]["px"]["value"] == pytest.approx(25.6)
    assert acc["rms"]["mm"]["value"] == pytest.approx(5.97)
    assert acc["bias_x"]["px"]["value"] == pytest.approx(25.6)
    assert acc["bias_y"]["px"]["value"] == pytest.approx(0.0)
    # 5.97 mm at about 615 mm: about 0.55 degrees.
    assert 0.4 < acc["median"]["deg"]["value"] < 0.6
    px_only = validation.evaluate(Shifted(), [col], SCALE_PX_ONLY)["accuracy"]
    assert px_only["median"]["mm"]["status"] == "unavailable"
    assert "physical display size" in px_only["median"]["deg"]["reason"]
    assert {(r["col"], r["row"]) for r in report["regions"]} == {(0, 1), (1, 1), (2, 1)}


def test_without_validation_data_no_accuracy_is_claimed():
    _, c, m = fitted(ideal_scenario())
    report = validation.evaluate(m, [], SCALE)
    assert report["source"] == "none" and report["accuracy"] is None
    training = validation.training_summary(m, [c["grid"], c["spiral"]], SCALE)
    assert training["leave_one_out_rms_px"]["status"] == "available"
    assert training["targets"] == 12


# --- recalibration -----------------------------------------------------------------------------


def _drifted_session(drift, seed=11):
    """A model fitted without drift, and new quick/validation data with `drift`."""
    _, _, m = fitted(default_scenario(), seed=seed)
    scenario = default_scenario()
    scenario["feature_drift"] = list(drift)
    user = SyntheticUser(scenario, seed, 0)  # the same person, later
    quick = targets.make_plan(
        "q",
        stationary_request(
            layout={"layout": "centre_edges_corners", "margin": 0.1}, settle=600, dwell=900
        ),
    )
    val = targets.make_plan(
        "v",
        stationary_request(
            "validation",
            {"layout": "validation_offset_grid", "cols": 3, "rows": 3, "margin": 0.1},
            600,
            900,
        ),
    )
    qc, t = collect(user, quick, 10**12)
    vc, _ = collect(user, val, t + 10**8)
    return m, qc, vc


def test_quick_recalibration_corrects_a_deliberate_offset():
    m, qc, vc = _drifted_session((0.03, -0.02))
    candidate = recalibration.fit_correction(m, qc.observations)
    comparison = recalibration.compare(m, candidate, [vc], SCALE)
    assert comparison["verdict"] == "better", comparison["reason"]
    before = comparison["current"]["accuracy"]["median"]["px"]["value"]
    after = comparison["candidate"]["accuracy"]["median"]["px"]["value"]
    assert before > 120 and after < 0.6 * before


def test_quick_recalibration_does_not_damage_an_accurate_model():
    m, qc, vc = _drifted_session((0.0, 0.0))
    candidate = recalibration.fit_correction(m, qc.observations)
    comparison = recalibration.compare(m, candidate, [vc], SCALE)
    assert comparison["verdict"] in ("equivalent", "better"), comparison["reason"]
    before = comparison["current"]["accuracy"]["median"]["px"]["value"]
    after = comparison["candidate"]["accuracy"]["median"]["px"]["value"]
    assert after < before * 1.15


def test_a_worse_candidate_is_called_worse():
    m, _, vc = _drifted_session((0.0, 0.0))
    bad = m.with_correction(np.array([[1.0, 0.0, 0.08], [0.0, 1.0, 0.0]]), "test")
    assert recalibration.compare(m, bad, [vc], SCALE)["verdict"] == "worse"
    assert recalibration.compare(m, bad, [], SCALE)["verdict"] == "inconclusive"


def test_incremental_offset_is_bounded():
    m, qc, _ = _drifted_session((0.004, 0.0))
    candidate, used, reason = recalibration.propose_offset(m, qc.observations)
    assert candidate is not None and used > 5, reason
    m2, qc2, _ = _drifted_session((0.05, 0.0))
    candidate, _, reason = recalibration.propose_offset(m2, qc2.observations)
    assert candidate is None and "recalibrate" in reason
    assert recalibration.propose_offset(m, qc.observations[:2])[0] is None
