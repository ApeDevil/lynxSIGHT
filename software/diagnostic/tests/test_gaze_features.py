import numpy as np
import pytest

from lynx_sight_diag import features as feat
from lynx_sight_diag.baseline import BaselineBuilder


def mesh(iris_shift=(0.0, 0.0), closed=False):
    """A 478-point mesh with two eyes 60 px wide, the image-left one centred at (400, 300)."""
    pts = np.tile(np.array([500.0, 350.0]), (478, 1))
    pts[:468] += np.random.default_rng(0).uniform(-120, 120, (468, 2))
    lid = 2.0 if closed else 9.0
    for (outer, inner, up, low, iris), cx, sign in (
        ((33, 133, 159, 145, 468), 400.0, 1),  # subject's right eye: image left
        ((263, 362, 386, 374, 473), 600.0, -1),
    ):
        pts[outer] = (cx - 30 * sign, 300)
        pts[inner] = (cx + 30 * sign, 300)
        pts[up], pts[low] = (cx, 300 - lid), (cx, 300 + lid)
        pts[iris] = (cx + iris_shift[0] * 60, 300 + iris_shift[1] * 60)
    return pts


def test_iris_in_eye_is_relative_to_the_corners_in_eye_widths():
    s = feat.from_landmarks(5, "cam_left", mesh((0.1, -0.05)), (1280, 800), (3.0, -2.0, 1.0), 0.9)
    left, right = s.eye("image_left"), s.eye("image_right")
    assert left.iris == pytest.approx((0.1, -0.05)) and right.iris == pytest.approx((0.1, -0.05))
    assert left.openness == pytest.approx(0.3)
    assert s.head.scale_px == pytest.approx(200.0)
    assert s.head.yaw_deg == 3.0 and s.face_confidence == 0.9


def test_a_tilted_eye_measures_along_its_own_axis():
    a, b = np.array([0.0, 0.0]), np.array([30.0, 30.0])
    (u, v), width = feat.iris_in_eye(b, a, np.array([15.0, 15.0]) + np.array([-3.0, 3.0]))
    assert width == pytest.approx(np.hypot(30, 30))
    assert u == pytest.approx(0.0, abs=1e-9) and v > 0  # perpendicular, downward


def test_eye_offsets_let_one_eye_stand_in():
    s = feat.from_landmarks(0, "c", mesh(), (1280, 800), None)
    shifted = feat.FeatureSample(0, "c", 1.0, (
        feat.EyeFeature("image_left", (0.02, 0.0), 0.3, 1.0),
        feat.EyeFeature("image_right", (-0.02, 0.0), 0.3, 1.0)), s.head)  # fmt: skip
    offsets = feat.eye_offsets([shifted])
    assert offsets["image_left"] == pytest.approx((0.02, 0.0))
    one = feat.FeatureSample(0, "c", 1.0, (shifted.eyes[0],), s.head)
    assert feat.combined_iris(one, offsets) == pytest.approx((0.0, 0.0))
    assert feat.combined_iris(feat.no_face(0, "c"), offsets) is None


def test_baseline_needs_all_stages_and_reports_physical_values_as_unavailable():
    b = BaselineBuilder(["cam_left"], "landmarks-uncalibrated")
    open_samples = [feat.from_landmarks(i * 16_000_000, "cam_left", mesh(), (1280, 800),
                                        (i % 9 - 4.0, 0.0, 0.0)) for i in range(60)]  # fmt: skip
    assert b.add_stage("detect_stable", open_samples)["ok"]
    with pytest.raises(ValueError):
        b.finish()
    assert b.add_stage("neutral", open_samples)["ok"]
    closed = [feat.from_landmarks(0, "cam_left", mesh(closed=True), (1280, 800), None)] * 30
    assert not b.add_stage("detect_stable", closed)["ok"]
    b.add_stage("detect_stable", open_samples)
    b.add_stage("pose_range", open_samples)
    baseline = b.finish()
    cam = baseline["cameras"][0]
    assert cam["interocular_px"]["value"] == pytest.approx(200.0)
    assert baseline["observed"]["yaw_deg"]["min"] < 0 < baseline["observed"]["yaw_deg"]["max"]
    assert baseline["inferred"]["interocular_mm"]["status"] == "unavailable"
    assert any(f["feature"] == "physical_scale" and not f["valid"] for f in baseline["features"])
    assert b.neutral_openness() == pytest.approx(0.3)
