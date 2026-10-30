import math

from lynx_sight_diag.stats import RateMeter, Summary, estimate_dropped, percentile


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([5], 95) == 5
    assert math.isnan(percentile([], 50))


def test_drop_estimate_from_gaps():
    assert estimate_dropped(16.7, 16.7) == 0
    assert estimate_dropped(24.0, 16.7) == 0  # jitter below 1.5 periods
    assert estimate_dropped(33.3, 16.7) == 1
    assert estimate_dropped(50.0, 16.7) == 2


def test_rate_meter_measures_fps_and_drops():
    meter = RateMeter()
    t = 0.0
    for i in range(100):
        t += 10.0 * (3 if i in (50, 80) else 1)  # two gaps: 2 frames lost each
        meter.add(t)
    assert meter.total_frames == 100
    assert meter.total_dropped == 4
    assert meter.nominal_interval_ms == 10.0
    assert 90 < meter.fps < 100


def test_summary_ignores_missing_values():
    s = Summary.of([1.0, None, float("nan"), 3.0])
    assert s.count == 2 and s.mean == 2.0 and s.max == 3.0
    assert Summary.of([]).as_dict()["mean"] is None
