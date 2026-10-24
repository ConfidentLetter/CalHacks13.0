"""Step 2: calibrate / pixel_to_hole / hole_to_pixel on the synthetic bench."""
import cv2
import numpy as np
import pytest

from perception_geometry import BOARD_CONFIG, CalibrationError, calibrate, hole_to_pixel, pixel_to_hole
from perception_geometry import board, calibration
from perception_geometry.warp import to_original

from .synth import render_board

MODEL_IDS = list(board.iter_holes())
MODEL_PX = np.array([board.hole_px(h) for h in MODEL_IDS])


def _save(tmp_path, name, img):
    p = tmp_path / f"{name}.jpg"
    cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return str(p)


def _hole_accuracy(H, H_true) -> float:
    """Fraction of model holes that, projected to the image with the TRUE homography, map back correctly."""
    orig = to_original(MODEL_PX, H_true)
    hits = sum(pixel_to_hole(x, y, H) == h for (x, y), h in zip(orig, MODEL_IDS))
    return hits / len(MODEL_IDS)


@pytest.fixture(autouse=True)
def _fresh_cache():
    calibration.clear_cache()
    yield
    calibration.clear_cache()


def test_identity_roundtrip_every_hole():
    H = calibration.make_identity()
    for h in MODEL_IDS:
        x, y = hole_to_pixel(h, H)
        assert pixel_to_hole(x, y, H) == h


def test_rails_and_offboard():
    H = calibration.make_identity()
    for rail in BOARD_CONFIG["rails"]:
        x, y = hole_to_pixel(rail, H)
        assert pixel_to_hole(x, y, H) == rail
    assert pixel_to_hole(5, 5, H) is None
    assert pixel_to_hole(-100, -100, H) is None
    # halfway between two holes but inside the grid: still snaps (0.5 pitch tolerance is inclusive-ish)
    ax, ay = board.hole_px("A1")
    assert pixel_to_hole(ax + 0.3 * board.pitch_px(), ay, H) == "A1"
    assert pixel_to_hole(ax + 0.7 * board.pitch_px(), ay, H) == "A2"


@pytest.mark.parametrize("jitter_mm", [0.0, 2.0])
def test_fifty_random_warps(tmp_path, jitter_mm):
    accs = []
    for seed in range(50):
        r = render_board(100 + seed, n_wires=5, marker_jitter_mm=jitter_mm)
        H = calibrate(_save(tmp_path, f"w{seed}", r.image))
        assert len(H) == 3 and all(len(row) == 3 for row in H)
        accs.append(_hole_accuracy(np.array(H), r.H_true))
        # round trip with the same H is exact
        for h in ("A1", "E31", "F32", "J63"):
            assert pixel_to_hole(*hole_to_pixel(h, H), H) == h
    mean = float(np.mean(accs))
    worst = float(np.min(accs))
    print(f"jitter {jitter_mm} mm: mean {mean:.4f} worst {worst:.4f}")
    assert mean >= 0.99, f"mean hole accuracy {mean:.4f}, worst {worst:.4f}"


def test_wire_endpoints_snap_to_truth(tmp_path):
    r = render_board(7, n_wires=6)
    H = calibrate(_save(tmp_path, "ends", r.image))
    for w in r.wires:
        assert pixel_to_hole(*w.pixel_a, H) == w.hole_a
        assert pixel_to_hole(*w.pixel_b, H) == w.hole_b


def test_missing_markers_raise_with_count(tmp_path):
    r = render_board(3, n_wires=2, hide_markers={1, 2})
    with pytest.raises(CalibrationError) as ei:
        calibrate(_save(tmp_path, "missing", r.image))
    assert "2 of 4" in str(ei.value)


def test_clicked_corners_fallback(tmp_path):
    r = render_board(4, n_wires=3, hide_markers={0})
    path = _save(tmp_path, "clicked", r.image)
    corners = [to_original([board.hole_px(h)], r.H_true)[0] for h in BOARD_CONFIG["click_corner_holes"]]
    # simulate imprecise clicks (up to ~0.3 pitch in the image)
    rng = np.random.default_rng(0)
    corners = [tuple(c + rng.uniform(-4, 4, 2)) for c in corners]
    H = calibrate(path, corners=corners)
    assert _hole_accuracy(np.array(H), r.H_true) >= 0.99


def test_cache_hits_when_markers_do_not_move(tmp_path):
    r = render_board(5, n_wires=2)
    path = _save(tmp_path, "cache", r.image)
    H1 = calibrate(path)
    H2 = calibrate(path)
    assert H1 is H2  # same cached object


def test_blank_frame_raises(tmp_path):
    p = tmp_path / "blank.jpg"
    cv2.imwrite(str(p), np.full((720, 1280, 3), 200, np.uint8))
    with pytest.raises(CalibrationError):
        calibrate(str(p))
