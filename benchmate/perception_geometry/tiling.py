"""Density-balanced tiles of the board for T2's open-vocabulary detector.

Strips run along the numbered axis (vertical cuts in the warped board frame) with boundaries at equal
quantiles of Canny edge density, so busy regions get narrower tiles. Each tile overlaps its neighbours
by one pitch. Tiles are cropped from the ORIGINAL frame (axis-aligned), upscaled 2x when narrower than
640 px, and saved to runtime/tiles/. bbox is in original pixels; `scale` is the saved image's upscale.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import cv2
import numpy as np

from . import board
from .paths import tiles_dir
from .telemetry import log
from .warp import as_matrix, read_frame, to_original, warp_image

TILE_PARAMS = {
    "min_tile_px": 640,          # upscale 2x below this width (original px)
    "target_tile_px": 400,       # aim for about one tile per this many original px of board width
    "min_strip_pitches": 6.0,    # never cut a strip narrower than this
    "overlap_pitches": 1.0,
    "canny": (60, 160),
    "jpeg_quality": 92,
}


def _board_region_px() -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of the board outline in warped px."""
    cfg = board.BOARD_CONFIG
    s = cfg["px_per_mm"]
    bx, by = cfg["board_tl_mm"]
    bw, bh = cfg["board_size_mm"]
    return int(bx * s), int(by * s), int((bx + bw) * s), int((by + bh) * s)


def _edge_profile(warped: np.ndarray, region) -> np.ndarray:
    x0, y0, x1, y1 = region
    gray = cv2.cvtColor(warped[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, *TILE_PARAMS["canny"])
    prof = edges.sum(axis=0).astype(np.float64) / 255.0
    k = int(board.pitch_px()) | 1
    prof = cv2.blur(prof.reshape(1, -1), (k, 1)).ravel()
    return prof + 1e-3                                   # never all-zero (blank board -> equal strips)


def _cut_points(profile: np.ndarray, n: int, min_w: float) -> list[int]:
    """n-1 interior cut positions at equal quantiles of the cumulative profile, min strip width enforced."""
    W = profile.size
    if n <= 1:
        return []
    cum = np.cumsum(profile)
    cum /= cum[-1]
    cuts = [int(np.searchsorted(cum, k / n)) for k in range(1, n)]
    # enforce minimum width by pushing cuts right, then left
    prev = 0
    for i, c in enumerate(cuts):
        cuts[i] = max(c, int(prev + min_w))
        prev = cuts[i]
    nxt = W
    for i in range(len(cuts) - 1, -1, -1):
        cuts[i] = min(cuts[i], int(nxt - min_w))
        nxt = cuts[i]
    if any(c <= 0 or c >= W for c in cuts) or any(b - a < min_w * 0.5 for a, b in zip([0] + cuts, cuts + [W])):
        cuts = [int(W * k / n) for k in range(1, n)]     # fallback: equal widths
    return cuts


def tile(frame_path: str, homography, max_tiles: int = 6) -> list[dict]:
    """Density-balanced tiles of the board region. Each: {path, bbox:[x,y,w,h]} in original pixels."""
    t0 = time.perf_counter()
    img = read_frame(frame_path)
    H = as_matrix(homography)
    img_h, img_w = img.shape[:2]
    warped = warp_image(img, H)
    region = _board_region_px()
    x0, y0, x1, y1 = region
    pitch = board.pitch_px()

    # how wide is the board in the original frame? -> number of tiles
    corners_w = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float64)
    corners_o = to_original(corners_w, H)
    width_orig = float(max(np.linalg.norm(corners_o[1] - corners_o[0]), np.linalg.norm(corners_o[2] - corners_o[3])))
    n = int(min(max(1, max_tiles), max(1, math.ceil(width_orig / TILE_PARAMS["target_tile_px"]))))

    profile = _edge_profile(warped, region)
    cuts = _cut_points(profile, n, TILE_PARAMS["min_strip_pitches"] * pitch)
    bounds = [0] + cuts + [x1 - x0]
    ov = TILE_PARAMS["overlap_pitches"] * pitch

    out_dir = tiles_dir()
    stem = Path(frame_path).stem
    tiles = []
    for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        sa, sb = max(0, a - ov) + x0, min(x1 - x0, b + ov) + x0
        quad_w = np.array([[sa, y0], [sb, y0], [sb, y1], [sa, y1]], np.float64)
        quad_o = to_original(quad_w, H)
        bx0 = int(max(0, math.floor(quad_o[:, 0].min())))
        by0 = int(max(0, math.floor(quad_o[:, 1].min())))
        bx1 = int(min(img_w, math.ceil(quad_o[:, 0].max())))
        by1 = int(min(img_h, math.ceil(quad_o[:, 1].max())))
        if bx1 - bx0 < 8 or by1 - by0 < 8:
            continue
        crop = img[by0:by1, bx0:bx1]
        scale = 2.0 if crop.shape[1] < TILE_PARAMS["min_tile_px"] else 1.0
        if scale != 1.0:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        path = out_dir / f"{stem}_tile{i}.jpg"
        cv2.imwrite(str(path), crop, [cv2.IMWRITE_JPEG_QUALITY, TILE_PARAMS["jpeg_quality"]])
        tiles.append({"path": str(path), "bbox": [float(bx0), float(by0), float(bx1 - bx0), float(by1 - by0)],
                      "scale": scale, "strip_warped_x": [float(sa), float(sb)]})
    log("tile", (time.perf_counter() - t0) * 1000, n_tiles=len(tiles), width_orig=round(width_orig))
    return tiles
