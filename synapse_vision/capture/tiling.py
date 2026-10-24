"""Ink-density-balanced horizontal bands of the dewarped page (LoBE-GS idea: balance the load, keep detail)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from capture.compat import absolute, cfg, repo_relative, runtime_dir, timed
from capture.quality import ink_mask

TILES_DIR = "tiles"
DEFAULT_OVERLAP_PX = 60
DEFAULT_QUIET_SEARCH_PX = 40
MIN_TILE_HEIGHT_PX = 200


def _row_ink_profile(gray: np.ndarray) -> np.ndarray:
    ink = ink_mask(gray)
    profile = (ink > 0).sum(axis=1).astype(np.float64)
    return cv2.GaussianBlur(profile.reshape(-1, 1), (1, 0), 3).ravel() if len(profile) > 8 else profile


def plan_cuts(profile: np.ndarray, max_tiles: int, quiet_search_px: int, min_tile_px: int) -> list[int]:
    """Row indices where bands end (exclusive), balanced by cumulative ink and nudged to the quietest nearby row."""
    h = len(profile)
    total = float(profile.sum())
    n = int(max(1, min(max_tiles, h // max(1, min_tile_px))))
    if n <= 1 or total <= 0:
        return [h]
    cumulative = np.cumsum(profile)
    cuts: list[int] = []
    prev = 0
    for k in range(1, n):
        target = total * k / n
        y = int(np.searchsorted(cumulative, target))
        lo, hi = max(prev + min_tile_px, y - quiet_search_px), min(h - min_tile_px, y + quiet_search_px)
        if lo < hi:
            window = profile[lo:hi]
            y = lo + int(np.argmin(window)) if window.min() < profile[min(y, h - 1)] else y
        y = int(np.clip(y, prev + min_tile_px, h - min_tile_px))
        if y <= prev:
            continue
        cuts.append(y)
        prev = y
    cuts.append(h)
    return sorted(set(cuts))


def tile(dewarped_path: str, max_tiles: int = 6) -> list[dict]:
    """Ink-density-balanced horizontal bands with overlap. Each {path, bbox}."""
    with timed("capture.tile") as info:
        img = cv2.imread(str(absolute(dewarped_path)), cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            info["tiles"] = 0
            return []
        h, w = img.shape[:2]
        gray_path = absolute(dewarped_path).with_name(Path(dewarped_path).stem + "_gray.png")
        gray = cv2.imread(str(gray_path), cv2.IMREAD_GRAYSCALE) if gray_path.exists() else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        overlap = int(cfg("page.tile_overlap_px", DEFAULT_OVERLAP_PX))
        quiet = int(cfg("page.tile_quiet_search_px", DEFAULT_QUIET_SEARCH_PX))
        cuts = plan_cuts(_row_ink_profile(gray), max_tiles, quiet, MIN_TILE_HEIGHT_PX)
        out_dir = runtime_dir(TILES_DIR)
        stem = Path(dewarped_path).stem.replace("_dewarped", "")
        tiles: list[dict] = []
        start = 0
        for i, end in enumerate(cuts):
            y0, y1 = max(0, start - (overlap if i > 0 else 0)), min(h, end + (overlap if i < len(cuts) - 1 else 0))
            path = out_dir / f"{stem}_tile_{i:02d}.jpg"
            cv2.imwrite(str(path), img[y0:y1], [cv2.IMWRITE_JPEG_QUALITY, 95])
            tiles.append({"path": repo_relative(path), "bbox": [0, int(y0), int(w), int(y1 - y0)]})
            start = end
        info["tiles"] = len(tiles)
        return tiles
