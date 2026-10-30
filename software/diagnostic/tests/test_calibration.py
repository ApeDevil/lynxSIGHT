import numpy as np
import pytest

from lynx_sight_diag import calibration


def test_grid_targets_cover_the_screen_with_margin():
    targets = calibration.grid_targets(3, 3, 1920, 1080)
    assert len(targets) == 9
    assert targets[0] == (192, 108) and targets[4] == (960, 540) and targets[-1] == (1728, 972)


def test_polynomial_mapping_is_recovered_from_noisy_offsets():
    rng = np.random.default_rng(3)
    targets = np.array(calibration.grid_targets(4, 3, 1920, 1080), float)
    # Invert a known smooth mapping screen -> offset to fabricate offsets for a known answer.
    offsets = np.column_stack(
        [
            (targets[:, 0] - 960) / 4000,
            (targets[:, 1] - 540) / 5000 + 0.02 * ((targets[:, 0] - 960) / 960) ** 2,
        ]
    )
    fit = calibration.fit(offsets + rng.normal(0, 0.0005, offsets.shape), targets)
    assert fit.n_targets == 12
    assert fit.train_rmse_px < 10
    assert fit.loo_rmse_px is not None and fit.loo_rmse_px < 20
    predicted = fit.predict(offsets[0])
    assert np.allclose(predicted[0], targets[0], atol=15)


def test_fit_needs_enough_targets():
    with pytest.raises(ValueError):
        calibration.fit(np.zeros((5, 2)), np.zeros((5, 2)))
    assert calibration.mean_offset([(0.1, 0.2)] * 3) is None
    assert calibration.mean_offset([(0.1, 0.2)] * 4 + [(9, 9)]) == (0.1, 0.2)
