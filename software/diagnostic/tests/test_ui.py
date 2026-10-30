"""Headless rendering of the diagnostic view and snapshot saving."""

import json

import numpy as np
from conftest import wait_until

from lynx_sight_diag import overlay
from lynx_sight_diag.app import render, save_snapshot
from lynx_sight_diag.capture import CaptureStatus, State
from lynx_sight_diag.config import CaptureSettings, ProcessorConfig, quick_config
from lynx_sight_diag.processing import Result, RunnerStats
from lynx_sight_diag.processing.eyes import EyeRegion, Eyes
from lynx_sight_diag.processing.face import Face, Faces
from lynx_sight_diag.processing.pupil import Pupil
from lynx_sight_diag.session import Session


def test_panel_draws_detections_and_tiles(make_frame):
    frame = make_frame(np.full((400, 640), 100, np.uint8))
    face = Face(
        (200, 100, 200, 220),
        0.91,
        {
            "eye_image_left": (250.0, 180.0),
            "eye_image_right": (350.0, 180.0),
            "nose": (300.0, 230.0),
            "mouth_image_left": (260.0, 280.0),
            "mouth_image_right": (340.0, 280.0),
        },
    )
    region = EyeRegion(
        "image_left",
        (220, 160, 60, 40),
        (250.0, 180.0),
        Pupil(30, 20, 5, 0.8, 0.3, 0.9),
        (250.0, 180.0),
        (0.0, 0.0),
    )
    eyes = Eyes(0.91, 100.0, 0.0, (0.47, 0.5), [region])
    results = {
        "face": Result("face", "cam_left", frame, 0, 1.0, Faces([face])),
        "eyes": Result("eyes", "cam_left", frame, 0, 1.0, eyes),
    }
    status = CaptureStatus(
        "cam_left",
        State.RUNNING,
        "/dev/v4l/by-path/x",
        "MJPG 640x400@60",
        59.9,
        100,
        0,
        16.7,
        17.0,
        3.2,
        0,
        None,
    )
    panel = overlay.draw_panel(
        frame.image, status, results, {"face": RunnerStats()}, 320, {"gain": 3}, True
    )
    assert panel.shape == (200, 320, 3)
    assert (panel != panel[..., :1]).any()  # coloured overlays were drawn on the grey image
    tiles = overlay.eye_tiles(frame.image, results["eyes"])
    assert len(tiles) == 1 and tiles[0].shape == (160, 240, 3)  # aspect kept
    canvas = overlay.compose([panel, panel], tiles, "footer")
    assert canvas.shape == (200 + 160 + 44, 640, 3)


def test_live_render_and_snapshot_without_a_display(tmp_path):
    cfg = quick_config("synthetic", "synthetic", CaptureSettings("MJPG", 320, 200, 60))
    session = Session(cfg, processors={"quality": ProcessorConfig(True, 20.0)})
    session.start()
    try:
        assert wait_until(
            lambda: all(c.slot.latest() is not None for c in session.cameras.values())
        )
        assert wait_until(lambda: session.board.latest("cam_right", "quality") is not None)
        canvas = render(session, "cam_left", 320, True, "test")
        snap = save_snapshot(session, tmp_path, canvas)
    finally:
        session.stop()
    assert canvas.shape[1] == 640
    assert {p.name for p in snap.iterdir()} == {
        "cam_left.png",
        "cam_right.png",
        "overlay.png",
        "snapshot.json",
    }
    meta = json.loads((snap / "snapshot.json").read_text())
    assert meta["cameras"]["cam_left"]["controls"]["exposure_time_absolute"] == 150
    assert "quality" in meta["cameras"]["cam_right"]["results"]
