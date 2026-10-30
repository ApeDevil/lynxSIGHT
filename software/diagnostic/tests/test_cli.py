import argparse

import pytest

from lynx_sight_diag import cli


def test_mode_parsing():
    m = cli._mode("YUYV:640x400@120")
    assert (m.fourcc, m.width, m.height, m.fps) == ("YUYV", 640, 400, 120.0)
    assert cli._mode("1280x800@60").fourcc == "MJPG"
    with pytest.raises(argparse.ArgumentTypeError):
        cli._mode("1280x800")


def test_phase_parsing():
    assert cli._phases("centre:10,left:5,right") == [
        ("centre", 10.0),
        ("left", 5.0),
        ("right", 10.0),
    ]


def test_list_without_cameras_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(cli.discovery, "discover", lambda: [])
    assert cli.main(["list"]) == 1
    assert "No V4L2 video devices" in capsys.readouterr().out


def test_missing_source_is_a_config_error(capsys):
    assert cli.main(["record", "--duration", "0.1"]) == 2
    assert "--config" in capsys.readouterr().err


def test_models_list(capsys):
    assert cli.main(["models", "list"]) == 0
    assert "yunet" in capsys.readouterr().out
