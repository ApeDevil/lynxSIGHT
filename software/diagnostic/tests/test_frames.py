import threading

import numpy as np
import pytest

from lynx_sight_diag.frames import FrameSlot


def test_frames_are_read_only(make_frame):
    frame = make_frame()
    with pytest.raises(ValueError):
        frame.image[0, 0] = 1


def test_slot_returns_newest_frame_and_skips_older_ones(make_frame):
    slot = FrameSlot("cam_left")
    assert slot.wait_newer(0, timeout=0.01) is None
    for seq in (1, 2, 3):
        slot.publish(make_frame(seq=seq))
    frame, token = slot.wait_newer(0, timeout=0.01)
    assert frame.seq == 3 and token == 3
    assert slot.wait_newer(token, timeout=0.01) is None  # nothing newer yet


def test_slot_wakes_a_waiting_consumer(make_frame):
    slot = FrameSlot("cam_left")
    got = []
    t = threading.Thread(target=lambda: got.append(slot.wait_newer(0, timeout=2)))
    t.start()
    slot.publish(make_frame(np.zeros((4, 4), np.uint8), seq=7))
    t.join(2)
    assert got and got[0][0].seq == 7
