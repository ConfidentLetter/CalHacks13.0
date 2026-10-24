"""Breadboard model: hole ids, rail bands, and the warped board frame.

Everything geometric lives in BOARD_CONFIG (millimetres, in the *warped* top-down
board frame: x runs along the numbered axis 1..63, y runs down the lettered axis).
Pixels in the warped image are BOARD_CONFIG["px_per_mm"] * mm.

Tune BOARD_CONFIG against the real board; nothing else in the package hard-codes layout.
"""
from __future__ import annotations

import re
from typing import Iterator

PITCH_MM = 2.54
_BOARD_W_MM, _BOARD_H_MM = 165.1, 54.6   # physical outline of an 830-point board
_BOARD_TL_MM = (40.0, 40.0)              # where the board's top-left corner sits in the warped frame
_MARKER_OUT_MM = 15.0                    # marker centres this far outside each board corner (diagonal)

BOARD_CONFIG = {
    "type": "breadboard_830",
    "px_per_mm": 10.0,
    "pitch_mm": PITCH_MM,
    "n_cols": 63,
    # Row order as seen top-to-bottom in the warped image. Flip to "JIHGFEDCBA" if the
    # real board is mounted the other way up relative to marker 0.
    "letters_top_to_bottom": "ABCDEFGHIJ",
    "channel_gap_pitches": 3,            # E -> F distance (0.3 inch)
    # Centre of the first column / row A, in warped mm.
    "origin_mm": (_BOARD_TL_MM[0] + 3.81, _BOARD_TL_MM[1] + 3.2 + 4 * PITCH_MM),
    # Rail bands: y range in *pitch units relative to row A* (row J is at 11).
    # VERIFY +/- assignment on the real board (red line = PLUS). Swapping two names here is the fix.
    "rails": {
        "RAIL_TOP_PLUS": (-4.6, -3.5),
        "RAIL_TOP_MINUS": (-3.5, -2.3),
        "RAIL_BOTTOM_MINUS": (13.3, 14.5),
        "RAIL_BOTTOM_PLUS": (14.5, 15.6),
    },
    # Nominal rail hole rows (pitch units from row A) — used only by the synthetic renderer
    # and the hole-blob filter; rail hole x spacing varies by brand, so rails are bands.
    "rail_rows": {"RAIL_TOP_PLUS": -4, "RAIL_TOP_MINUS": -3, "RAIL_BOTTOM_MINUS": 14, "RAIL_BOTTOM_PLUS": 15},
    # Rails extend this many pitches beyond columns 1 and 63 in x.
    "rail_x_slack_pitches": 1.0,
    # Warped frame size in mm (board + room for the markers).
    "warped_size_mm": (_BOARD_W_MM + 2 * _BOARD_TL_MM[0], _BOARD_H_MM + 2 * _BOARD_TL_MM[1]),
    "board_tl_mm": _BOARD_TL_MM,
    "board_size_mm": (_BOARD_W_MM, _BOARD_H_MM),
    # ArUco DICT_4X4_50 ids -> target centre in the warped frame (mm). 0 TL, 1 TR, 2 BR, 3 BL.
    "markers": {
        0: (_BOARD_TL_MM[0] - _MARKER_OUT_MM, _BOARD_TL_MM[1] - _MARKER_OUT_MM),
        1: (_BOARD_TL_MM[0] + _BOARD_W_MM + _MARKER_OUT_MM, _BOARD_TL_MM[1] - _MARKER_OUT_MM),
        2: (_BOARD_TL_MM[0] + _BOARD_W_MM + _MARKER_OUT_MM, _BOARD_TL_MM[1] + _BOARD_H_MM + _MARKER_OUT_MM),
        3: (_BOARD_TL_MM[0] - _MARKER_OUT_MM, _BOARD_TL_MM[1] + _BOARD_H_MM + _MARKER_OUT_MM),
    },
    "marker_size_mm": 20.0,
    # Which holes the user clicks when markers are missing (TL, TR, BR, BL of the main grid).
    "click_corner_holes": ("A1", "A63", "J63", "J1"),
    # Snap tolerance for pixel_to_hole, in pitches.
    "snap_tolerance_pitches": 0.5,
}

RAIL_IDS = tuple(BOARD_CONFIG["rails"].keys())
_HOLE_RE = re.compile(r"([A-J])(\d{1,2})")


def letters() -> str:
    return BOARD_CONFIG["letters_top_to_bottom"]


def row_offset_pitches(letter: str) -> float:
    """Row position in pitch units relative to the first letter row (A=0 ... J=11)."""
    idx = letters().index(letter)
    gap = BOARD_CONFIG["channel_gap_pitches"] - 1
    return idx + (gap if idx >= 5 else 0)


def pitch_px() -> float:
    return BOARD_CONFIG["pitch_mm"] * BOARD_CONFIG["px_per_mm"]


def warped_size_px() -> tuple[int, int]:
    w_mm, h_mm = BOARD_CONFIG["warped_size_mm"]
    s = BOARD_CONFIG["px_per_mm"]
    return int(round(w_mm * s)), int(round(h_mm * s))


def hole_mm(hole: str) -> tuple[float, float]:
    """Centre of a terminal-strip hole in warped mm. Rails map to the centre of their band."""
    ox, oy = BOARD_CONFIG["origin_mm"]
    p = BOARD_CONFIG["pitch_mm"]
    if hole in BOARD_CONFIG["rails"]:
        lo, hi = BOARD_CONFIG["rails"][hole]
        return ox + (BOARD_CONFIG["n_cols"] - 1) * p / 2, oy + (lo + hi) / 2 * p
    m = _HOLE_RE.fullmatch(hole)
    if not m:
        raise ValueError(f"not a hole id: {hole!r}")
    col = int(m.group(2))
    if not 1 <= col <= BOARD_CONFIG["n_cols"]:
        raise ValueError(f"column out of range: {hole!r}")
    return ox + (col - 1) * p, oy + row_offset_pitches(m.group(1)) * p


def hole_px(hole: str) -> tuple[float, float]:
    x, y = hole_mm(hole)
    s = BOARD_CONFIG["px_per_mm"]
    return x * s, y * s


def iter_holes() -> Iterator[str]:
    for letter in letters():
        for col in range(1, BOARD_CONFIG["n_cols"] + 1):
            yield f"{letter}{col}"


def rail_at_mm(x: float, y: float) -> str | None:
    """Rail id whose band contains (x, y) in warped mm, else None."""
    ox, oy = BOARD_CONFIG["origin_mm"]
    p = BOARD_CONFIG["pitch_mm"]
    slack = BOARD_CONFIG["rail_x_slack_pitches"] * p
    if not (ox - slack <= x <= ox + (BOARD_CONFIG["n_cols"] - 1) * p + slack):
        return None
    yp = (y - oy) / p
    for rail, (lo, hi) in BOARD_CONFIG["rails"].items():
        if lo <= yp < hi:
            return rail
    return None


def nearest_hole_mm(x: float, y: float) -> tuple[str, float]:
    """Nearest terminal-strip hole id and its distance in mm (no tolerance applied)."""
    ox, oy = BOARD_CONFIG["origin_mm"]
    p = BOARD_CONFIG["pitch_mm"]
    col = int(round((x - ox) / p)) + 1
    col = min(max(col, 1), BOARD_CONFIG["n_cols"])
    yp = (y - oy) / p
    best_letter, best_dy = None, float("inf")
    for letter in letters():
        dy = abs(yp - row_offset_pitches(letter))
        if dy < best_dy:
            best_letter, best_dy = letter, dy
    hole = f"{best_letter}{col}"
    hx, hy = hole_mm(hole)
    return hole, ((x - hx) ** 2 + (y - hy) ** 2) ** 0.5


def node_of(hole: str | None) -> str | None:
    """Electrical node of a hole: A-E of a column share one, F-J another, each rail is its own."""
    if hole is None:
        return None
    if hole in BOARD_CONFIG["rails"]:
        return hole
    m = _HOLE_RE.fullmatch(hole)
    if not m:
        raise ValueError(f"not a hole id: {hole!r}")
    letter, col = m.group(1), int(m.group(2))
    return f"R{col}{'L' if letters().index(letter) < 5 else 'R'}"
