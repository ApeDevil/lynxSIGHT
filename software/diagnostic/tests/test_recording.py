"""Recording, summaries and replay of recorded data."""

import json

import numpy as np

from lynx_sight_diag.app import run_headless
from lynx_sight_diag.config import CaptureSettings, ProcessorConfig, quick_config
from lynx_sight_diag.processing.pupil import Pupil
from lynx_sight_diag.recorder import summarize_records, to_jsonable
from lynx_sight_diag.session import Session
from lynx_sight_diag.sources import EndOfStream, ReplaySource

SMALL = CaptureSettings("MJPG", 160, 100, 100)


def frame(cid, seq, t_ms, interval, dropped=0, phase=None):
    return {
        "camera_id": cid,
        "seq": seq,
        "t_capture_ns": int(t_ms * 1e6),
        "interval_ms": interval,
        "est_dropped": dropped,
        "read_ms": 1.0,
        "phase": phase,
    }


def test_summary_aggregates_timing_and_detections():
    frames = [frame("cam_left", i + 1, i * 10.0, None if i == 0 else 10.0) for i in range(101)]
    frames[50]["est_dropped"] = 2
    face_hit = {"faces": [{"score": 0.9}]}
    eyes = {
        "eye_distance_px": 80.0,
        "roll_deg": 2.0,
        "face_centre_norm": [0.5, 0.4],
        "regions": [{"pupil": {"confidence": 0.8}}, {"pupil": None}],
    }
    results = (
        [
            {
                "camera_id": "cam_left",
                "processor": "face",
                "latency_ms": 20.0,
                "compute_ms": 15.0,
                "phase": "centre",
                "error": None,
                "data": face_hit,
            }
        ]
        * 3
        + [
            {
                "camera_id": "cam_left",
                "processor": "face",
                "latency_ms": 22.0,
                "compute_ms": 15.0,
                "phase": "left",
                "error": None,
                "data": {"faces": []},
            }
        ]
        + [
            {
                "camera_id": "cam_left",
                "processor": "face",
                "latency_ms": 0,
                "compute_ms": 0,
                "phase": "left",
                "error": "RuntimeError: x",
                "data": None,
            }
        ]
        + [
            {
                "camera_id": "cam_left",
                "processor": "eyes",
                "latency_ms": 25.0,
                "compute_ms": 2.0,
                "phase": "centre",
                "error": None,
                "data": eyes,
            }
        ]
    )
    s = summarize_records(frames, results)
    cam = s["cameras"]["cam_left"]
    assert cam["frames"] == 101 and cam["fps"] == 100.0 and cam["est_dropped"] == 2
    face = s["processors"]["cam_left/face"]
    assert face["results"] == 5 and face["errors"] == 1
    assert face["face_detect_rate"] == 0.75 and face["face_score_mean"] == 0.9
    assert s["phases"]["centre"]["cam_left"]["face_detect_rate"] == 1.0
    assert s["phases"]["centre"]["cam_left"]["pupil_found_rate"] == 0.5
    assert s["phases"]["left"]["cam_left"]["face_detect_rate"] == 0.0


def test_jsonable_handles_dataclasses_arrays_and_nan():
    out = to_jsonable(
        {
            "p": Pupil(1.23456, 2.0, 3.0, 0.5, 0.1, 0.9),
            "big": np.zeros((478, 2)),
            "small": np.array([1.5, 2.5]),
            "nan": float("nan"),
            "t": (1, 2),
        }
    )
    assert out["p"]["x"] == 1.235
    assert out["big"] == {"shape": [478, 2]}
    assert out["small"] == [1.5, 2.5] and out["nan"] is None and out["t"] == [1, 2]
    json.dumps(out)


def test_headless_run_writes_a_complete_run_directory_and_replays(tmp_path):
    cfg = quick_config("synthetic", "synthetic", SMALL, experiment_id="t-rec")
    cfg.output_dir = str(tmp_path)
    procs = {"quality": ProcessorConfig(True, 20.0), "face": ProcessorConfig(False)}
    run_dir, summary = run_headless(
        Session(cfg, processors=procs),
        1.0,
        raw_video=True,
        phases=[("centre", 0.5), ("left", 0.5)],
        warmup_s=0.2,
        quiet=True,
    )
    names = {p.name for p in run_dir.iterdir()}
    assert {
        "config.yaml",
        "frames.jsonl",
        "results.jsonl",
        "events.jsonl",
        "summary.json",
        "cam_left.avi",
        "cam_left.timestamps.csv",
        "cam_right.avi",
    } <= names
    for cid in ("cam_left", "cam_right"):
        cam = summary["cameras"][cid]
        assert 60 <= cam["frames"] <= 110 and cam["est_dropped"] == 0
    assert summary["record_dropped"] == 0
    assert "cam_left/quality" in summary["processors"]
    config_text = (run_dir / "config.yaml").read_text()
    assert "negotiated: SYNTH 160x100@100" in config_text
    events = [
        json.loads(line)["event"] for line in (run_dir / "events.jsonl").read_text().splitlines()
    ]
    assert events[0] == "start" and events.count("phase") == 2 and events[-1] == "stop"

    # Replay the raw video as recorded data, unpaced for speed.
    replay = ReplaySource(str(run_dir / "cam_left.avi"), paced=False)
    replay.open()
    count = 0
    try:
        while True:
            image, _ = replay.read()
            assert image.shape == (100, 160)
            count += 1
    except EndOfStream:
        pass
    assert count == summary["cameras"]["cam_left"]["frames"]


def test_image_directory_replay(tmp_path):
    import cv2

    for i in range(3):
        cv2.imwrite(str(tmp_path / f"{i:03d}.png"), np.full((20, 30), i * 50, np.uint8))
    replay = ReplaySource(str(tmp_path), paced=False)
    replay.open()
    levels = [int(replay.read()[0].mean()) for _ in range(3)]
    assert levels == [0, 50, 100]
