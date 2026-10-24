"""Pin layout: footprint row + anchor hole -> one hole per pin (pure hole-space arithmetic)."""
from __future__ import annotations

from dataclasses import dataclass

from .geometry_bridge import N_COLS, parse_hole


@dataclass(frozen=True)
class RowLayout:
    pins: tuple[tuple[str, str], ...]   # ((pin_name, hole), ...)
    direction: int                      # +1 towards higher column numbers, -1 towards lower

    @property
    def columns(self) -> tuple[int, int]:
        cols = [parse_hole(h)[1] for _, h in self.pins]  # type: ignore[index]
        return min(cols), max(cols)


def _fits(start_col: int, n: int, direction: int) -> bool:
    end = start_col + direction * (n - 1)
    return 1 <= end <= N_COLS


def _overlap(start_col: int, n: int, direction: int, ref: tuple[int, int]) -> int:
    lo, hi = sorted((start_col, start_col + direction * (n - 1)))
    return max(0, min(hi, ref[1]) - max(lo, ref[0]) + 1)


def choose_direction(start_col: int, n_pins: int, *, end_col: int | None = None,
                     reference_columns: tuple[int, int] | None = None) -> int:
    """Which way the row runs along the numbered axis.

    1. A click on the last pin (end_col) decides it outright.
    2. Otherwise, if another row of the same component is already laid out, pick the direction
       that overlaps its column span most (a DevKit's two headers are mirrored when seen from above).
    3. Otherwise towards higher numbers, unless that would leave the board.
    """
    if end_col is not None and end_col != start_col:
        return 1 if end_col > start_col else -1
    if reference_columns is not None:
        plus, minus = (_overlap(start_col, n_pins, d, reference_columns) for d in (1, -1))
        if plus != minus:
            return 1 if plus > minus else -1
    return 1 if _fits(start_col, n_pins, 1) or not _fits(start_col, n_pins, -1) else -1


def layout_row(pin_names: list[str], anchor_hole: str, *, end_hole: str | None = None,
               reference_columns: tuple[int, int] | None = None) -> RowLayout:
    """Place pins k = 0..n-1 at anchor column + k * direction on the anchor's letter row.
    Pins that would fall off the board get hole None (the twin stays valid; T3 sees an unplaced pin)."""
    parsed = parse_hole(anchor_hole)
    if parsed is None:
        raise ValueError(f"anchor must be a terminal-strip hole like 'B40', got {anchor_hole!r}")
    letter, col0 = parsed
    end_parsed = parse_hole(end_hole) if end_hole else None
    direction = choose_direction(col0, len(pin_names),
                                 end_col=end_parsed[1] if end_parsed else None,
                                 reference_columns=reference_columns)
    pins = []
    for k, name in enumerate(pin_names):
        col = col0 + direction * k
        pins.append((name, f"{letter}{col}" if 1 <= col <= N_COLS else None))
    return RowLayout(tuple(pins), direction)
