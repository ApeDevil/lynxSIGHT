import math

import numpy as np
import pytest

from lynx_sight_diag.processing import ProcessorUnavailable
from lynx_sight_diag.processing import landmarks as lm


def test_euler_angles_from_rotation_matrix():
    assert lm.euler_from_matrix(np.eye(4)) == (0.0, 0.0, 0.0)
    a = math.radians(20)
    yaw_20 = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    yaw, pitch, roll = lm.euler_from_matrix(yaw_20)
    assert abs(yaw - 20) < 1e-9 and abs(pitch) < 1e-9 and abs(roll) < 1e-9


def test_missing_model_makes_the_processor_unavailable(monkeypatch, make_frame):
    pytest.importorskip("mediapipe")
    monkeypatch.setattr(lm.models, "locate", lambda key: None)
    with pytest.raises(ProcessorUnavailable, match="models fetch"):
        lm.LandmarksProcessor().process(make_frame())


def test_no_face_gives_no_landmarks(make_frame):
    pytest.importorskip("mediapipe")
    if lm.models.locate("face_landmarker") is None:
        pytest.skip("face_landmarker model not fetched")
    processor = lm.LandmarksProcessor()
    try:
        assert processor.process(make_frame(np.full((240, 320), 120, np.uint8))) is None
    finally:
        processor.close()
