"""Step 4: tile() — coverage, overlap, density balancing, files."""
import cv2
import numpy as np
import pytest

from perception_geometry import board, calibrate, calibration, tile
from perception_geometry.warp import to_original

from .synth import render_board


@pytest.fixture(autouse=True)
def _runtime_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("BM_RUNTIME_DIR", str(tmp_path / "runtime"))
    calibration.clear_cache()
    yield
    calibration.clear_cache()


def _board(tmp_path, seed, n_wires, **kw):
    r = render_board(seed, n_wires=n_wires, **kw)
    p = tmp_path / f"t{seed}.jpg"
    cv2.imwrite(str(p), r.image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return r, str(p), calibrate(str(p))


def _inside(pt, bbox):
    x, y, w, h = bbox
    return x <= pt[0] <= x + w and y <= pt[1] <= y + h


def test_tiles_cover_every_hole_and_respect_max(tmp_path):
    r, path, H = _board(tmp_path, 2000, 5)
    tiles = tile(path, H, max_tiles=6)
    assert 1 <= len(tiles) <= 6
    holes_px = to_original(np.array([board.hole_px(h) for h in board.iter_holes()]), r.H_true)
    for p in holes_px:
        assert any(_inside(p, t["bbox"]) for t in tiles)
    for t in tiles:
        assert set(t) >= {"path", "bbox", "scale"}
        img = cv2.imread(t["path"])
        assert img is not None
        assert abs(img.shape[1] - t["bbox"][2] * t["scale"]) <= 2
        assert t["scale"] in (1.0, 2.0)


def test_neighbouring_tiles_overlap_by_about_a_pitch(tmp_path):
    r, path, H = _board(tmp_path, 2001, 4)
    tiles = tile(path, H, max_tiles=4)
    assert len(tiles) >= 2
    for a, b in zip(tiles, tiles[1:]):
        ov = a["strip_warped_x"][1] - b["strip_warped_x"][0]
        assert abs(ov - 2 * board.pitch_px()) < 1.0      # one pitch on each side


def test_busy_side_gets_narrower_tiles(tmp_path):
    """Wires only on the left half -> left tiles narrower (in warped x) than right tiles."""
    from perception_geometry.tests import synth
    rng = np.random.default_rng(3)
    canvas, _ = synth.draw_blank_board(rng)
    cfg = board.BOARD_CONFIG
    s, p = cfg["px_per_mm"], cfg["pitch_mm"]
    ox, oy = cfg["origin_mm"]
    # dense scribble of wires on columns 1-25
    for i in range(14):
        a = (ox + rng.uniform(0, 24) * p, oy + rng.uniform(0, 11) * p)
        b = (ox + rng.uniform(0, 24) * p, oy + rng.uniform(0, 11) * p)
        cv2.line(canvas, (int(a[0] * s), int(a[1] * s)), (int(b[0] * s), int(b[1] * s)), (30, 30, 200), 14)
    M, _ = synth.random_camera(rng, tilt_deg=2.0, scale_jitter=0.0)
    img = cv2.warpPerspective(canvas, M, (1920, 1080), borderValue=synth.MAT_BGR)
    path = tmp_path / "busy.jpg"
    cv2.imwrite(str(path), img)
    H = calibrate(str(path))
    tiles = tile(str(path), H, max_tiles=4)
    assert len(tiles) >= 2
    widths = [t["strip_warped_x"][1] - t["strip_warped_x"][0] for t in tiles]
    assert widths[0] < widths[-1]


def test_max_tiles_one_returns_whole_board(tmp_path):
    r, path, H = _board(tmp_path, 2002, 3)
    tiles = tile(path, H, max_tiles=1)
    assert len(tiles) == 1
    holes_px = to_original(np.array([board.hole_px(h) for h in board.iter_holes()]), r.H_true)
    assert all(_inside(p, tiles[0]["bbox"]) for p in holes_px)


def test_small_frame_tiles_are_upscaled(tmp_path):
    r = render_board(2003, n_wires=3, out_size=(1280, 720))
    path = tmp_path / "small.jpg"
    cv2.imwrite(str(path), r.image)
    H = calibrate(str(path))
    tiles = tile(str(path), H, max_tiles=6)
    assert any(t["scale"] == 2.0 for t in tiles)
