import numpy as np

from capture.tests import synth


def test_render_is_deterministic_per_seed():
    a, b = synth.render(7), synth.render(7)
    assert np.array_equal(a.image, b.image) and np.allclose(a.corners, b.corners)


def test_corners_inside_frame_and_convex():
    for seed in range(10):
        s = synth.render(seed)
        h, w = s.image.shape[:2]
        assert (s.corners[:, 0] >= 0).all() and (s.corners[:, 0] < w).all()
        assert (s.corners[:, 1] >= 0).all() and (s.corners[:, 1] < h).all()
        assert abs(__import__("cv2").contourArea(s.corners)) > 0.1 * w * h


def test_corner_error_fraction_handles_cyclic_order():
    s = synth.render(3)
    assert synth.corner_error_fraction(s.corners, s.corners) == 0.0
    assert synth.corner_error_fraction(np.roll(s.corners, 1, axis=0), s.corners) == 0.0
    assert synth.corner_error_fraction(s.corners + 20, s.corners) > 0.01
