"""The full-screen calibration and the stereo capture loop, with OpenCV's GUI calls stubbed.

Checks the wiring (what gets recorded and saved), not the on-screen experience."""

import time

import cv2
import numpy as np
from stereo_helpers import board_pose, make_rig, observe_face, render_view

from lynx_sight_diag import app, config
from lynx_sight_diag.frames import Frame, freeze
from lynx_sight_diag.processing import Result
from lynx_sight_diag.processing.landmarks import Landmarks
from lynx_sight_diag.session import Session
from lynx_sight_diag.stereo.board import Checkerboard
from lynx_sight_diag.stereo.capture import run_stereo_capture
from lynx_sight_diag.stereo.evaluate import Recording, evaluate
from lynx_sight_diag.stereo.gaze import ScreenPlane
from lynx_sight_diag.stereo.live import run_gaze_preview
from lynx_sight_diag.stereo.rig import StereoRig


def stub_gui(monkeypatch, keys):
    """`keys`: callable returning the next key code for waitKey."""
    for fn in ("namedWindow", "setWindowProperty", "imshow", "destroyWindow", "resizeWindow"):
        monkeypatch.setattr(cv2, fn, lambda *a, **k: None)
    monkeypatch.setattr(cv2, "waitKey", lambda *a: keys())
    monkeypatch.setattr(cv2, "getWindowImageRect", lambda *a: (0, 0, 2048, 1152))


class FakeBoard:
    """Publishes a fresh simulated MediaPipe result per camera on every read."""

    def __init__(self, rig, screen):
        self.rig, self.screen = rig, screen
        self.target = np.array([1024.0, 576.0])
        self.seq = 0
        self.rng = np.random.default_rng(0)

    def latest(self, cid, name):
        if name != "landmarks":
            return None
        self.seq += 1
        S = self.screen.to_rig(self.target)[0]
        lm = observe_face(self.rig, np.eye(3), np.array([0.0, -90, 600]), S, self.rng)[cid]
        frame = Frame(
            cid, self.seq, time.monotonic_ns(), None, freeze(np.zeros((800, 1280), np.uint8)), "t"
        )
        return Result("landmarks", cid, frame, frame.t_capture_ns, 1.0, Landmarks(lm, [], None))


class FakeSession:
    def __init__(self, board):
        self.board = board
        self.cameras = {"cam_left": None, "cam_right": None}

    def start(self):
        pass

    def stop(self):
        pass


def test_calibration_run_records_landmarks_per_head_position(monkeypatch, tmp_path):
    stub_gui(monkeypatch, lambda: 32)  # space: start each head position
    rig = StereoRig.nominal()
    screen = ScreenPlane.below_rig((510.0, 287.0), (2048, 1152))
    board = FakeBoard(rig, screen)
    original = app._show_targets

    def show_targets(targets, settle_s, dwell_s, w, h, name, collect):
        def collect_and_track(i, t):
            board.target = np.array(t, float)  # the simulated user looks at the shown target
            collect(i, t)

        return original(targets, settle_s, dwell_s, w, h, name, collect_and_track)

    monkeypatch.setattr(app, "_show_targets", show_targets)
    report = app.run_calibration(
        FakeSession(board), tmp_path, (3, 3), 0.0, 0.05, None, ["centre", "left"]
    )
    assert report["head_positions"] == ["centre", "left"] and report["landmarks_file"]
    rec = Recording.load(tmp_path)
    assert set(rec.position.tolist()) == {0, 1} and set(rec.camera.tolist()) == {0, 1}
    assert rec.points.shape[1:] == (478, 2) and len(rec.targets_px) == 9
    result, models = evaluate(rec, rig, screen, max_skew_ms=50)
    assert result["models"]["head-ray/v1 degree 1"]["centre"]["targets"] == 9

    # the live preview pairs the two cameras' results and predicts
    board.target = np.array([500.0, 300.0])
    stats = run_gaze_preview(FakeSession(board), rig, models[1], max_skew_ms=50, max_frames=10)
    assert stats["pairs"] == 10


def test_stereo_capture_takes_a_still_view_and_reports(monkeypatch, tmp_path):
    board = Checkerboard(9, 6, 25.0)
    rig, _, _ = make_rig((640, 400))
    R, t = board_pose((0, 0, 500), 10, -10)
    devices = {}
    for cid in ("cam_left", "cam_right"):
        d = tmp_path / cid
        d.mkdir()
        cv2.imwrite(str(d / "000.png"), render_view(board, rig.camera(cid), R, t))
        devices[cid] = str(d)
    cfg = config.quick_config(devices["cam_left"], devices["cam_right"])
    cfg.capture.fps = 30
    out = tmp_path / "capture"
    deadline = time.monotonic() + 8

    def keys():
        if any(out.glob("*_cam_left.png")) or time.monotonic() > deadline:
            return ord("q")
        return 255

    stub_gui(monkeypatch, keys)
    result = run_stereo_capture(lambda procs: Session(cfg, processors=procs), out, board)
    assert (
        len(list(out.glob("*_cam_left.png"))) == 1 and len(list(out.glob("*_cam_right.png"))) == 1
    )
    assert (out / "views.jsonl").exists()
    assert "error" in result and result["detected"] == {"views": 1, "cam_left": 1, "cam_right": 1}
