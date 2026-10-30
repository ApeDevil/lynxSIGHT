from pathlib import Path

import pytest

from lynx_sight_diag import config

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "experiment.example.yaml"


def test_example_config_loads_and_round_trips(tmp_path):
    cfg = config.load(EXAMPLE)
    assert set(cfg.cameras) == {"cam_left", "cam_right"}
    assert cfg.baseline_mm == 100
    assert cfg.capture.fourcc == "MJPG"
    out = tmp_path / "again.yaml"
    out.write_text(config.dump(cfg))
    again = config.load(out)
    assert again.to_dict() == cfg.to_dict()


def test_per_camera_controls_override_shared_ones():
    cfg = config.from_dict(
        {
            "experiment_id": "x",
            "cameras": {
                "cam_left": {"device": "/dev/video0", "controls": {"gain": 5}},
                "cam_right": {"device": "/dev/video2"},
            },
            "capture": {"controls": {"gain": 1, "exposure_time_absolute": 100}},
        }
    )
    assert cfg.capture_for("cam_left").controls == {"gain": 5, "exposure_time_absolute": 100}
    assert cfg.capture_for("cam_right").controls == {"gain": 1, "exposure_time_absolute": 100}
    assert cfg.capture.controls["gain"] == 1  # shared settings are not mutated


@pytest.mark.parametrize(
    "patch, message",
    [
        ({"experiment_id": "bad id!"}, "experiment_id"),
        ({"cameras": {"cam_middle": {"device": "/dev/video0"}}}, "unknown camera id"),
        ({"cameras": {"cam_left": {}}}, "device is required"),
        ({"cameras": {"cam_left": {"device": "x", "yaw_deg": 40}}}, "yaw_deg"),
        ({"capture": {"fourcc": "MJPEG"}}, "fourcc"),
        ({"capture": {"fps": "fast"}}, "capture.fps"),
        ({"processing": {"gaze": {}}}, "unknown processor"),
        ({"schema": "other/v9"}, "unsupported schema"),
    ],
)
def test_invalid_configs_are_rejected_with_a_reason(patch, message):
    data = {"experiment_id": "ok", "cameras": {"cam_left": {"device": "/dev/video0"}}}
    data.update(patch)
    with pytest.raises(config.ConfigError, match=message):
        config.from_dict(data)


def test_processing_defaults_merge_with_overrides():
    cfg = config.from_dict(
        {
            "experiment_id": "ok",
            "cameras": {"cam_left": {"device": "synthetic"}},
            "processing": {
                "face": {"max_hz": 10, "options": {"score_threshold": 0.5}},
                "landmarks": {"enabled": True},
            },
        }
    )
    assert cfg.processing["face"].max_hz == 10
    assert cfg.processing["face"].options == {"input_width": 640, "score_threshold": 0.5}
    assert cfg.processing["landmarks"].enabled
    assert cfg.processing["quality"].enabled
