"""Thin, failure-tolerant wrappers around T1's perception_geometry.

Everything here degrades gracefully: if T1's module is missing or half-written we fall back to
an identity homography and a nearest-hole search built on hole_to_pixel, and never raise into
the twin pipeline.
"""
from __future__ import annotations

import math
import re
from typing import Any

import threading
from dataclasses import dataclass

IDENTITY: list[list[float]] = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
LETTERS = "ABCDEFGHIJ"
N_COLS = 63
HOLE_RE = re.compile(r"^([A-J])(\d{1,2})$")
SNAP_TOLERANCE_PITCHES = 0.6

_state_lock = threading.Lock()
_manual_corners: list[tuple[float, float]] | None = None
_last_good_h: list[list[float]] | None = None
_grid_cache: dict[str, list[tuple[str, float, float]]] = {}


@dataclass(frozen=True)
class Calibration:
    homography: list[list[float]]
    source: str            # "markers_or_corners" | "last_good" | "identity"
    error: str | None      # why the live calibration failed, if it did

    @property
    def calibrated(self) -> bool:
        return self.source != "identity"


def set_manual_corners(corners: list[tuple[float, float]] | None) -> None:
    """T5 calls this with the 4 clicked corner holes (TL, TR, BR, BL) from the `calibrate` WS message;
    they are passed to T1's calibrate() whenever markers are not enough. None clears them."""
    global _manual_corners
    with _state_lock:
        _manual_corners = None if corners is None else [(float(x), float(y)) for x, y in corners]
    try:
        from .twin import clear_cache

        clear_cache()
    except Exception:
        pass


def last_good_homography() -> list[list[float]] | None:
    with _state_lock:
        return None if _last_good_h is None else [r[:] for r in _last_good_h]


def _geometry():
    try:
        import perception_geometry as g  # type: ignore

        return g
    except Exception:
        return None


def parse_hole(hole: str | None) -> tuple[str, int] | None:
    """'B40' -> ('B', 40); None for rails / invalid ids."""
    if not hole:
        return None
    m = HOLE_RE.match(hole)
    if not m:
        return None
    col = int(m.group(2))
    return (m.group(1), col) if 1 <= col <= N_COLS else None


def hole_to_pixel(hole: str, homography: Any) -> tuple[float, float] | None:
    """Centre of a hole in original-image pixels, or None if T1 cannot resolve it."""
    g = _geometry()
    if g is None:
        return None
    try:
        x, y = g.hole_to_pixel(hole, homography)
        return float(x), float(y)
    except Exception:
        return None


def pitch_px(homography: Any) -> float:
    """Distance between two neighbouring holes in original pixels (default 25 px if unknown)."""
    a, b = hole_to_pixel("A1", homography), hole_to_pixel("A2", homography)
    if a and b:
        d = math.dist(a, b)
        if d > 1e-3:
            return d
    return 25.0


def _hash(homography: Any) -> str:
    try:
        return repr([[round(float(v), 4) for v in row] for row in homography])
    except Exception:
        return repr(homography)


def _grid(homography: Any) -> list[tuple[str, float, float]]:
    """All terminal-strip holes in original px for this homography (cached per homography)."""
    key = _hash(homography)
    with _state_lock:
        grid = _grid_cache.get(key)
    if grid is None:
        grid = []
        for letter in LETTERS:
            for col in range(1, N_COLS + 1):
                hole = f"{letter}{col}"
                p = hole_to_pixel(hole, homography)
                if p is not None:
                    grid.append((hole, p[0], p[1]))
        with _state_lock:
            if len(_grid_cache) > 8:
                _grid_cache.clear()
            _grid_cache[key] = grid
    return grid


def _nearest_hole(px: tuple[float, float], homography: Any) -> tuple[str | None, float]:
    best, best_d = None, float("inf")
    for hole, x, y in _grid(homography):
        d = math.dist(px, (x, y))
        if d < best_d:
            best, best_d = hole, d
    return best, best_d


def snap_to_hole(px: tuple[float, float], homography: Any, *, tolerance_px: float | None = None) -> str | None:
    """Original-image pixel -> terminal-strip hole id. T1's pixel_to_hole first, then a nearest-hole
    search on hole_to_pixel (covers the Step-1 stub that returns None). None if off-board."""
    g = _geometry()
    if g is not None:
        try:
            hole = g.pixel_to_hole(float(px[0]), float(px[1]), homography)
            if hole and parse_hole(hole):
                return hole
        except Exception:
            pass
    hole, d = _nearest_hole((float(px[0]), float(px[1])), homography)
    limit = tolerance_px if tolerance_px is not None else SNAP_TOLERANCE_PITCHES * pitch_px(homography)
    if hole is None or d > limit:
        return None
    return hole


def calibrate(frame_path: str) -> Calibration:
    """Live calibration via T1 (markers, else the corners T5 registered). If it fails on this frame
    (hand over a marker, bad light) the LAST GOOD homography is reused — on a fixed mount it is
    still right. Identity only when nothing has ever calibrated; pins are not snapped under it."""
    global _last_good_h
    g = _geometry()
    error: str | None = None
    if g is None:
        error = "perception_geometry not importable"
    else:
        with _state_lock:
            corners = None if _manual_corners is None else [c for c in _manual_corners]
        try:
            H = [[float(v) for v in row] for row in g.calibrate(frame_path, corners)]
            with _state_lock:
                _last_good_h = [r[:] for r in H]
            return Calibration(H, "markers_or_corners", None)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:200]
    last = last_good_homography()
    if last is not None:
        return Calibration(last, "last_good", error)
    return Calibration([r[:] for r in IDENTITY], "identity", error)


def calibrate_tuple(frame_path: str) -> tuple[list[list[float]], str | None]:
    """Backwards-compatible (homography, error) form."""
    c = calibrate(frame_path)
    return c.homography, c.error

