import time

import numpy as np
import pytest

from lynx_sight_diag.frames import Frame, freeze


def wait_until(predicate, timeout=5.0, interval=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def make_frame():
    def _make(image=None, camera_id="cam_left", seq=1):
        if image is None:
            image = np.full((80, 120), 128, np.uint8)
        return Frame(camera_id, seq, time.monotonic_ns(), None, freeze(image), "test")

    return _make
