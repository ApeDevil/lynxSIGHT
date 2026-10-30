import cv2
import numpy as np
import pytest

from lynx_sight_diag.processing.pupil import locate_pupil


def synthetic_eye(cx, cy, pupil_r=7, iris_r=16, size=(120, 80), noise=4, seed=0):
    """Skin, sclera ellipse, iris, dark pupil; drawn at 8x and downsampled for sub-pixel edges."""
    w, h = size
    k = 8
    big = np.full((h * k, w * k), 175, np.uint8)
    cv2.ellipse(
        big, (w * k // 2, h * k // 2), (w * k * 4 // 10, h * k * 3 // 10), 0, 0, 360, 215, -1
    )
    cv2.circle(big, (round(cx * k + k / 2), round(cy * k + k / 2)), iris_r * k, 105, -1)
    cv2.circle(big, (round(cx * k + k / 2), round(cy * k + k / 2)), pupil_r * k, 25, -1)
    img = cv2.resize(big, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    img += np.random.default_rng(seed).normal(0, noise, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


@pytest.mark.parametrize("cx, cy", [(60.0, 40.0), (52.3, 37.6), (68.8, 43.2), (45.5, 40.5)])
def test_pupil_centre_is_found_to_subpixel_accuracy(cx, cy):
    pupil = locate_pupil(synthetic_eye(cx, cy))
    assert pupil is not None
    assert abs(pupil.x - cx) < 0.75 and abs(pupil.y - cy) < 0.75
    assert 5.5 < pupil.radius < 8.5
    assert pupil.confidence > 0.5


def test_featureless_region_has_no_pupil():
    flat = np.random.default_rng(1).normal(150, 3, (80, 120)).clip(0, 255).astype(np.uint8)
    assert locate_pupil(flat) is None


def test_elongated_dark_lash_line_is_not_preferred_over_the_pupil():
    eye = synthetic_eye(60, 45)
    cv2.line(eye, (15, 12), (105, 12), 10, 4)  # eyelash/eyebrow-like dark bar
    pupil = locate_pupil(eye)
    assert pupil is not None and abs(pupil.y - 45) < 1.5


def test_tiny_regions_are_rejected():
    assert locate_pupil(np.zeros((8, 8), np.uint8)) is None
