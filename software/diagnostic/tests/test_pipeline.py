"""Capture + processing framework on synthetic sources: timing, sharing, isolation."""

import time

import numpy as np
from conftest import wait_until

from lynx_sight_diag.capture import CaptureWorker, State
from lynx_sight_diag.config import CaptureSettings, ProcessorConfig, quick_config
from lynx_sight_diag.processing import ProcessorRunner, ProcessorUnavailable, ResultBoard
from lynx_sight_diag.session import Session
from lynx_sight_diag.sources import CameraError, SyntheticSource

SMALL = CaptureSettings("MJPG", 160, 100, 200)


def test_capture_measures_rate_and_estimates_drops():
    source = SyntheticSource("cam_left", SMALL, drop_every=20)
    worker = CaptureWorker("cam_left", source)
    worker.start()
    assert wait_until(lambda: worker.meter.total_frames >= 120)
    worker.stop()
    status = worker.status()
    assert status.state is State.STOPPED
    # Every 20th frame is skipped by the generator; timestamps reveal it.
    assert 0.7 * status.frames / 20 <= status.est_dropped <= 1.3 * status.frames / 20 + 1
    assert abs(status.interval_p50_ms - 5.0) < 0.5
    frame = worker.slot.latest()
    assert frame.image.shape == (100, 160) and frame.image.dtype == np.uint8
    assert not frame.image.flags.writeable


class Recording:
    name = "probe"
    upstream = None

    def __init__(self, delay=0.0, fail=False):
        self.delay, self.fail, self.frames = delay, fail, []

    def process(self, frame, upstream=None):
        self.frames.append(frame)
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        return frame.seq


def test_one_frame_is_shared_and_slow_or_failing_functions_are_isolated():
    worker = CaptureWorker("cam_left", SyntheticSource("cam_left", SMALL))
    board = ResultBoard()
    fast, slow, broken = Recording(), Recording(delay=0.05), Recording(fail=True)
    fast.name, slow.name, broken.name = "fast", "slow", "broken"
    runners = [ProcessorRunner(p, "cam_left", worker.slot, board) for p in (fast, slow, broken)]
    for r in runners:
        r.start()
    fast_r, slow_r, broken_r = runners
    worker.start()
    # Wait on progress rather than a fixed time, so a loaded machine slows the test, not fails it.
    assert wait_until(
        lambda: fast_r.stats.processed > 40 and slow_r.stats.processed >= 5, timeout=20
    )
    worker.stop()
    for r in runners:
        r.stop()
    # Capture kept going while the slow consumer worked: it skipped frames instead of queueing
    # them, and the crashing consumer did not stop anything.
    assert worker.meter.total_frames > 3 * slow_r.stats.processed
    assert slow_r.stats.skipped > slow_r.stats.processed
    assert broken_r.stats.errors >= 1 and broken_r.stats.processed == 0
    assert "boom" in board.latest("cam_left", "broken").error
    assert board.latest("cam_left", "fast").ok
    # The same frame object (no copies) reached different consumers.
    shared = {id(f) for f in fast.frames} & {id(f) for f in slow.frames}
    assert shared
    # Latency is measured from capture.
    assert slow_r.stats.latency_summary().p50 >= 50


def test_downstream_processor_runs_on_its_upstream_frame():
    worker = CaptureWorker("cam_left", SyntheticSource("cam_left", SMALL))
    board = ResultBoard()

    class Up:
        name, upstream = "up", None

        def process(self, frame, upstream=None):
            return frame.seq

    class Down:
        name, upstream = "down", "up"

        def __init__(self):
            self.pairs = []

        def process(self, frame, upstream):
            self.pairs.append((frame.seq, upstream.data, upstream.frame is frame))
            return None

    down = Down()
    runners = [
        ProcessorRunner(Up(), "cam_left", worker.slot, board),
        ProcessorRunner(down, "cam_left", worker.slot, board),
    ]
    for r in runners:
        r.start()
    worker.start()
    assert wait_until(lambda: len(down.pairs) > 10)
    worker.stop()
    for r in runners:
        r.stop()
    assert all(seq == data and same for seq, data, same in down.pairs)


def test_unavailable_processor_reports_once_and_stops():
    class Missing:
        name, upstream = "missing", None
        calls = 0

        def process(self, frame, upstream=None):
            Missing.calls += 1
            raise ProcessorUnavailable("model missing")

    worker = CaptureWorker("cam_left", SyntheticSource("cam_left", SMALL))
    board = ResultBoard()
    runner = ProcessorRunner(Missing(), "cam_left", worker.slot, board)
    runner.start()
    worker.start()
    assert wait_until(lambda: runner.stats.unavailable is not None)
    time.sleep(0.1)
    worker.stop()
    runner.stop()
    assert Missing.calls == 1
    assert board.latest("cam_left", "missing").error == "unavailable: model missing"


class FlakySource(SyntheticSource):
    """Fails to open once, then disconnects after a few frames."""

    def __init__(self):
        super().__init__("cam_left", SMALL)
        self.opens = 0

    def open(self):
        self.opens += 1
        if self.opens == 1:
            raise CameraError("device busy")
        super().open()

    def read(self):
        if self.opens == 2 and self._n >= 5:
            raise CameraError("disconnected")
        return super().read()


def test_worker_reports_errors_and_reconnects():
    source = FlakySource()
    worker = CaptureWorker("cam_left", source, reconnect_delay_s=0.05)
    worker.start()
    assert wait_until(lambda: source.opens >= 3 and worker.state is State.RUNNING)
    worker.stop()
    assert worker.reconnects >= 1


def test_session_runs_two_cameras_with_real_processors():
    cfg = quick_config("synthetic", "synthetic", CaptureSettings("MJPG", 320, 200, 60))
    processors = {
        "quality": ProcessorConfig(True, 20.0),
        "face": ProcessorConfig(True, 20.0),
        "eyes": ProcessorConfig(True, None),
    }
    session = Session(cfg, processors=processors)
    session.start()
    try:
        assert wait_until(
            lambda: all(
                session.board.latest(cid, "face") is not None
                and session.board.latest(cid, "quality") is not None
                for cid in ("cam_left", "cam_right")
            ),
            timeout=10,
        )
    finally:
        session.stop()
    for cid in ("cam_left", "cam_right"):
        face = session.board.latest(cid, "face")
        assert face.ok and face.data.faces == []  # the synthetic pattern contains no face
        assert session.board.latest(cid, "quality").data.mean > 0
    value, err = session.adjust_control("cam_left", "exposure_time_absolute", value=300)
    assert err is None and value == 300
