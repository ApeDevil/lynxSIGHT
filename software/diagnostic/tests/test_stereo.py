"""Stereo calibration, triangulation, head pose and head-compensated gaze on synthetic data.

All inputs are generated from known geometry (tests/stereo_helpers.py); passing says the maths
recovers that geometry, not that the real cameras or MediaPipe are this accurate."""

import json
import math

import cv2
import numpy as np
import pytest
from stereo_helpers import (
    _FACE_MM,
    board_pose,
    board_poses,
    make_rig,
    observe_face,
    render_view,
    rotation,
)

from lynx_sight_diag import calibration, cli, features
from lynx_sight_diag.calibration import grid_targets
from lynx_sight_diag.frames import Frame, freeze
from lynx_sight_diag.processing.chessboard import ChessboardProcessor
from lynx_sight_diag.stereo.board import (
    Checkerboard,
    find_corners,
    normalise_order,
    render_image,
    render_svg,
)
from lynx_sight_diag.stereo.calibrate import StereoCalibration, View, calibrate
from lynx_sight_diag.stereo.capture import ViewSelector, solve_directory
from lynx_sight_diag.stereo.evaluate import Recording, evaluate
from lynx_sight_diag.stereo.gaze import HeadRayModel, ScreenPlane, angles_of, direction_of
from lynx_sight_diag.stereo.head import (
    FaceTemplate,
    head_pose,
    kabsch,
    observe,
    pair_by_time,
    triangulate_face,
)
from lynx_sight_diag.stereo.rig import StereoRig

BOARD = Checkerboard(9, 6, 25.0)
SIZE = (640, 400)


def angle_between(Ra, Rb) -> float:
    return math.degrees(np.linalg.norm(cv2.Rodrigues(Ra.T @ Rb)[0]))


# --- board -------------------------------------------------------------------------------------


def test_board_spec_and_geometry():
    b = Checkerboard.parse("9x6@25")
    assert b == BOARD and b.spec == "9x6@25" and b.size_mm == (250.0, 175.0)
    obj = b.object_points()
    assert obj.shape == (54, 3) and obj[1, 0] == 25.0 and obj[9, 1] == 25.0
    with pytest.raises(ValueError):
        Checkerboard.parse("9x6")


def test_svg_is_to_scale():
    svg = render_svg(BOARD)
    assert 'width="297mm"' in svg and 'viewBox="0 0 297 210"' in svg
    assert svg.count('width="25" height="25"') == 35  # half of 10 x 7 squares are black
    with pytest.raises(ValueError):
        render_svg(Checkerboard(15, 10, 25.0))


def test_corners_found_in_order_on_a_flat_board():
    image = render_image(BOARD, 4.0)
    corners = find_corners(image, BOARD)
    assert corners is not None and corners.shape == (54, 2)
    # first inner corner: margin (1 square) + 1 square from the top-left, at 4 px/mm
    assert np.allclose(corners[0], (199.5, 199.5), atol=0.6)
    assert np.allclose(normalise_order(corners[::-1].copy()), corners)


# --- calibration -------------------------------------------------------------------------------


def _rendered_views(rig, poses):
    views = []
    for k, (R, t) in enumerate(poses):
        left = find_corners(render_view(BOARD, rig.left, R, t, seed=k), BOARD)
        right = find_corners(render_view(BOARD, rig.right, R, t, seed=100 + k), BOARD)
        views.append(View(f"v{k:03d}", left, right))
    return views


def test_calibration_from_rendered_images_recovers_the_rig():
    rig, R, T = make_rig(SIZE)
    views = _rendered_views(rig, board_poses(16))
    cal = calibrate(views, BOARD, SIZE)
    assert len(cal.pair_views) >= 8
    assert abs(cal.baseline_mm - np.linalg.norm(T)) < 1.5
    assert angle_between(cal.R, R) < 0.8
    for est, true in ((cal.left.K, rig.left.K), (cal.right.K, rig.right.K)):
        assert abs(est[0, 0] / true[0, 0] - 1) < 0.015
    assert cal.left.rms_px < 0.5 and cal.epipolar_px < 0.5
    assert not any("swapped" in w for w in cal.warnings(257))


def test_calibration_from_exact_corners_is_tight_and_round_trips(tmp_path):
    rig, R, T = make_rig(SIZE)
    rng = np.random.default_rng(0)
    views = []
    for k, (Rb, tb) in enumerate(board_poses(30)):
        pts = BOARD.object_points() @ Rb.T + tb
        sides = []
        for cam in (rig.left, rig.right):
            px = cam.project(pts)
            inside = px.min() > 5 and px[:, 0].max() < SIZE[0] - 5 and px[:, 1].max() < SIZE[1] - 5
            sides.append((px + rng.normal(0, 0.1, px.shape)).astype(np.float32) if inside else None)
        views.append(View(f"v{k}", *sides))
    cal = calibrate(views, BOARD, SIZE)
    assert abs(cal.baseline_mm - 257.0) < 0.8
    assert angle_between(cal.R, R) < 0.2
    path = tmp_path / "stereo.json"
    cal.save(path)
    again = StereoCalibration.load(path)
    assert np.allclose(again.R, cal.R) and np.allclose(again.left.K, cal.left.K)
    assert json.loads(path.read_text())["schema"] == "lynx-sight/stereo-calibration/v1"
    # the rig built from it triangulates a point 600 mm away to within a millimetre
    point = np.array([[30.0, -80.0, 600.0]])
    est, err = again.rig().triangulate(rig.left.project(point), rig.right.project(point))
    true_in_est_rig = point  # both rigs share the definition of the rig frame
    assert np.linalg.norm(est - true_in_est_rig) < 3.0 and err[0] < 0.5


def test_swapped_cameras_are_reported():
    rig, R, T = make_rig(SIZE)
    swapped_T = -R.T @ T  # cam_right's centre now on the user's left
    fake = type("C", (), {"rms_px": 0.2, "coverage": 0.8})()
    cal = StereoCalibration(BOARD, SIZE, fake, fake, R.T, swapped_T, 0.2, 0.2, ["v"] * 20)
    assert any("swapped" in w for w in cal.warnings())


def test_solve_directory_and_cli(tmp_path):
    rig, _, _ = make_rig(SIZE)
    for k, (R, t) in enumerate(board_poses(12, seed=3)):
        cv2.imwrite(
            str(tmp_path / f"view_{k:03d}_cam_left.png"), render_view(BOARD, rig.left, R, t)
        )
        cv2.imwrite(
            str(tmp_path / f"view_{k:03d}_cam_right.png"), render_view(BOARD, rig.right, R, t)
        )
    result = solve_directory(tmp_path, BOARD, 257.0)
    assert "saved" in result, result
    assert abs(result["baseline_mm"] - 257.0) < 3
    assert cli.main(["stereo", "show", str(tmp_path / "stereo_calibration.json")]) == 0
    svg = tmp_path / "board.svg"
    assert cli.main(["stereo", "board", "--out", str(svg)]) == 0 and svg.read_text().startswith(
        "<?xml"
    )


# --- rig ---------------------------------------------------------------------------------------


def test_nominal_rig_frame_matches_the_shared_interface():
    rig = StereoRig.nominal()
    assert np.allclose(rig.left.centre_rig, (-128.5, 0, 0))
    assert np.allclose(rig.right.centre_rig, (128.5, 0, 0))
    # a point to the user's right (+X) appears left of centre in the image (cameras face the user)
    px = rig.left.project(np.array([[100.0, 0, 600]]))[0]
    assert px[0] < 640
    up = rig.left.project(np.array([[-128.5, 100.0, 600]]))[0]
    assert up[1] < 400  # +Y (up) is up in the image
    pts = np.array([[0, -90, 600.0], [40, 30, 450]])
    est, err = rig.triangulate(rig.left.project(pts), rig.right.project(pts))
    assert np.allclose(est, pts, atol=1e-6) and err.max() < 1e-6


def test_scaled_rig_projects_to_scaled_pixels():
    rig, _, _ = make_rig(SIZE)
    point = np.array([[20.0, -50, 550]])
    full = rig.left.project(point)[0]
    half = rig.scaled_to((320, 200)).left.project(point)[0]
    assert np.allclose((full + 0.5) / 2 - 0.5, half, atol=1e-6)


# --- capture -----------------------------------------------------------------------------------


def test_view_selector_needs_stillness_in_both_cameras_and_novelty():
    rig = StereoRig.nominal(SIZE)
    sel = ViewSelector(BOARD, SIZE, still_s=0.5)
    R, t = board_pose((0, 0, 600))
    pts = BOARD.object_points() @ R.T + t
    corners = {cid: rig.camera(cid).project(pts) for cid in ("cam_left", "cam_right")}
    for k in range(8):  # 0.1 s steps, board still
        for cid, c in corners.items():
            sel.update(cid, k * 100_000_000, c)
    assert sel.ready(7 * 100_000_000)
    sel.accept()
    assert not sel.ready(
        8 * 100_000_000
    )  # same pose again: not novel, and needs a new still period
    moved = {cid: c + (120, 0) for cid, c in corners.items()}
    for k in range(8, 16):
        for cid, c in moved.items():
            sel.update(cid, k * 100_000_000, c)
    assert sel.ready(15 * 100_000_000)
    sel.update("cam_right", 16 * 100_000_000, None)  # lost in one camera
    assert not sel.ready(16 * 100_000_000)


def test_chessboard_processor_finds_full_resolution_corners():
    rig, _, _ = make_rig((1280, 800))
    R, t = board_pose((0, -20, 650), 15, -10)
    image = render_view(BOARD, rig.left, R, t)
    frame = Frame("cam_left", 1, 0, None, freeze(image), "test")
    live = ChessboardProcessor("9x6@25", detect_width=640).process(frame)
    full = find_corners(image, BOARD)
    assert live is not None and full is not None
    assert np.max(np.linalg.norm(live.corners - full, axis=1)) < 1.5


# --- head pose ---------------------------------------------------------------------------------


def test_kabsch_recovers_a_rigid_motion():
    rng = np.random.default_rng(0)
    src = rng.normal(0, 30, (12, 3))
    R_true, t_true = rotation(10, -5, 3), np.array([5.0, -80, 600])
    R, t = kabsch(src, src @ R_true.T + t_true)
    assert np.allclose(R, R_true, atol=1e-9) and np.allclose(t, t_true, atol=1e-9)


@pytest.fixture(scope="module")
def stereo_scene():
    rig = StereoRig.nominal()
    screen = ScreenPlane.below_rig((510.0, 287.0), (2048, 1152))
    return rig, screen


def _faces(rig, screen, R, t, targets, n, rng):
    out = []
    for k, target in enumerate(targets):
        S = screen.to_rig(np.array(target))[0]
        for _ in range(n):
            lm = observe_face(rig, R, t, S, rng)
            out.append((k, lm, triangulate_face(rig, lm["cam_left"], lm["cam_right"])))
    return out


def test_head_pose_from_triangulated_landmarks(stereo_scene):
    rig, screen = stereo_scene
    rng = np.random.default_rng(1)
    t0 = np.array([0.0, -90, 600])
    centre = _faces(rig, screen, np.eye(3), t0, [(1024, 576)], 10, rng)
    template = FaceTemplate.from_faces([f for _, _, f in centre])
    R_true, t_true = rotation(12, -6, 4), t0 + (40, 20, -60)
    _, _, face = _faces(rig, screen, R_true, t_true, [(1024, 576)], 1, rng)[0]
    pose = head_pose(face, template)
    assert pose is not None and pose.residual_mm < 2.0
    assert angle_between(pose.R, R_true) < 1.5
    # the head origin is the eye-corner midpoint, 5 mm behind the simulated face's origin
    corner_mid = np.mean([_FACE_MM[i] for i in (33, 133, 362, 263)], axis=0)
    assert np.linalg.norm(pose.t - (t_true + R_true @ corner_mid)) < 3.0
    yaw, pitch, roll = pose.angles_deg()
    assert abs(yaw - 12) < 2 and abs(pitch + 6) < 2 and abs(roll - 4) < 2


def test_pair_by_time_uses_each_result_once():
    left = [(0, "a"), (10_000_000, "b"), (40_000_000, "c")]
    right = [(2_000_000, "x"), (9_000_000, "y"), (90_000_000, "z")]
    pairs = pair_by_time(left, right, max_skew_ms=5)
    assert [(p[2], p[3]) for p in pairs] == [("a", "x"), ("b", "y")]
    assert pairs[0][1] == 2.0


# --- gaze --------------------------------------------------------------------------------------


def test_screen_plane_and_angles_round_trip():
    screen = ScreenPlane.below_rig((510.0, 287.0), (2048, 1152), above_mm=20, behind_mm=5)
    px = np.array([[0, 0], [2048, 1152], [700, 300]], float)
    rig_pts = screen.to_rig(px)
    assert np.allclose(rig_pts[0], (-255, -20, -5)) and np.allclose(rig_pts[1], (255, -307, -5))
    eye = np.array([10.0, -100, 600])
    assert np.allclose(screen.intersect(np.tile(eye, (3, 1)), rig_pts - eye), px)
    assert np.isnan(screen.intersect(eye, eye - rig_pts[0])).all()  # pointing away
    d = np.array([[0.2, -0.3, -0.93]])
    d /= np.linalg.norm(d)
    assert np.allclose(direction_of(angles_of(d)), d)


def test_head_ray_model_holds_when_the_head_moves(stereo_scene, tmp_path):
    rig, screen = stereo_scene
    rng = np.random.default_rng(2)
    R0, t0 = np.eye(3), np.array([0.0, -90, 600])
    cal_targets = grid_targets(5, 4, 2048, 1152)
    cal = _faces(rig, screen, R0, t0, cal_targets, 8, rng)
    template = FaceTemplate.from_faces([f for _, _, f in cal[:10]])
    obs = [observe(f, template) for _, _, f in cal]
    targets = np.array([cal_targets[k] for k, _, _ in cal])
    model = HeadRayModel.fit(obs, targets, screen, template, degree=1)

    # the 2-D model on main, fitted on the same frames (cam_left, both eyes combined)
    samples = {k: [] for k in range(len(cal_targets))}
    for k, lm, _ in cal:
        s = features.from_landmarks(0, "cam_left", lm["cam_left"], (1280, 800), None)
        samples[k].append(np.mean([e.iris for e in s.tracked_eyes], axis=0))
    poly = calibration.fit(
        np.array([np.median(samples[k], axis=0) for k in samples]), np.array(cal_targets)
    )

    val_targets = grid_targets(3, 3, 2048, 1152, margin=0.2)
    errors = {}
    for name, (R, t) in {
        "centre": (R0, t0),
        "moved": (rotation(-8, 5, 3), t0 + (-60, 30, 60)),
        "turned": (rotation(12, 0, 0), t0),
    }.items():
        val = _faces(rig, screen, R, t, val_targets, 4, rng)
        ray, flat = [], []
        for k, lm, face in val:
            pred = model.predict(observe(face, template))
            ray.append(np.linalg.norm(pred - val_targets[k]))
            s = features.from_landmarks(0, "cam_left", lm["cam_left"], (1280, 800), None)
            iris = np.mean([e.iris for e in s.tracked_eyes], axis=0)
            flat.append(np.linalg.norm(poly.predict(iris)[0] - val_targets[k]))
        errors[name] = (np.median(ray), np.median(flat))
    assert errors["centre"][0] < 80
    for name in ("moved", "turned"):
        ray, flat = errors[name]
        assert ray < 90, errors
        assert flat > 2 * ray, errors  # the uncompensated model breaks when the head moves

    path = tmp_path / "model.json"
    model.save(path)
    again = HeadRayModel.load(path)
    o = obs[0]
    assert np.allclose(again.predict(o), model.predict(o))


def test_offline_evaluation_of_a_recording(stereo_scene, tmp_path):
    rig, screen = stereo_scene
    rng = np.random.default_rng(3)
    targets = grid_targets(4, 3, 2048, 1152)
    positions = {
        "centre": (np.eye(3), np.array([0.0, -90, 600])),
        "left": (rotation(-10, 0, 0), np.array([-70.0, -90, 620])),
    }
    rows = {k: [] for k in ("t_ns", "camera", "target", "position", "points")}
    t_ns = 0
    for p, (R, t) in enumerate(positions.values()):
        for k, target in enumerate(targets):
            S = screen.to_rig(np.array(target))[0]
            for _ in range(6):
                lm = observe_face(rig, R, t, S, rng)
                for c, cid in enumerate(("cam_left", "cam_right")):
                    rows["t_ns"].append(t_ns + c * 3_000_000)  # cam_right 3 ms later
                    rows["camera"].append(c)
                    rows["target"].append(k)
                    rows["position"].append(p)
                    rows["points"].append(lm[cid])
                t_ns += 33_000_000
    rec = Recording(
        np.array(rows["t_ns"]),
        np.array(rows["camera"]),
        np.array(rows["target"]),
        np.array(rows["position"]),
        np.stack(rows["points"]),
        np.array(targets, float),
        list(positions),
        (1280, 800),
    )
    rec.save(tmp_path)
    rec = Recording.load(tmp_path)
    report, models = evaluate(rec, rig, screen)
    assert report["stereo_pairs"] == {"centre": 72, "left": 72}
    ray = report["models"]["head-ray/v1 degree 1"]
    flat = report["models"]["iris-in-eye/v1 cam_left (uncompensated)"]["degree 2"]
    assert ray["left"]["median_px"] < 60 and ray["loo_train"]["targets"] == 12
    assert flat["left"]["median_px"] > 2 * ray["left"]["median_px"]
    assert 1 in models and "median_deg" in ray["left"]
    assert abs(report["head"]["left"]["yaw_pitch_roll_deg"][0] + 10) < 2
