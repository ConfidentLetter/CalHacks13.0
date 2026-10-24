"""Reading order and regions.

Columns: lines whose x-ranges chain together form a column; narrow columns in
the outer page zones are margins.  Order = columns left to right, lines top to
bottom within each column.  The first main-column line is the *problem* when a
clear vertical gap separates it from the rest.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from layout.lines import MARGIN_ZONE_FRAC, Line, _x_gap, _y_gap

COLUMN_JOIN_GAP_CHARS = 2.0     # x-gap (in char widths) that still joins a column
MARGIN_MAX_WIDTH_FRAC = 0.5     # of the main column width
PROBLEM_GAP_FACTOR = 1.3        # first line gap vs median gap to call it a problem statement
DIAGRAM_MIN_HEIGHT_LINES = 3.0  # a "line" taller than this many line heights is a diagram


@dataclass
class Column:
    lines: list[Line]

    @property
    def x0(self) -> int:
        return min(l.bbox[0] for l in self.lines)

    @property
    def x1(self) -> int:
        return max(l.bbox[0] + l.bbox[2] for l in self.lines)

    @property
    def width(self) -> int:
        return self.x1 - self.x0


def cluster_columns(lines: list[Line], med_char_w: float) -> list[Column]:
    columns: list[Column] = []
    for line in sorted(lines, key=lambda l: l.bbox[0]):
        for col in columns:
            if _x_gap(line.bbox, [col.x0, 0, col.width, 1]) <= COLUMN_JOIN_GAP_CHARS * med_char_w:
                col.lines.append(line)
                break
        else:
            columns.append(Column([line]))
    return sorted(columns, key=lambda c: c.x0)


def _is_margin(col: Column, main: Column, page_w: int) -> bool:
    if col is main:
        return False
    in_zone = col.x0 >= (1 - MARGIN_ZONE_FRAC) * page_w or col.x1 <= MARGIN_ZONE_FRAC * page_w
    return in_zone and col.width <= MARGIN_MAX_WIDTH_FRAC * max(1, main.width)


def _problem_lines(main_lines: list[Line]) -> int:
    """How many leading lines form the problem statement (0 or 1)."""
    if len(main_lines) < 3:
        return 0
    gaps = [_y_gap(a.bbox, b.bbox) for a, b in zip(main_lines, main_lines[1:])]
    rest = gaps[1:]
    return 1 if gaps[0] > PROBLEM_GAP_FACTOR * float(np.median(rest)) and gaps[0] > 0 else 0


def _region(rid: int, rtype: str, lines: list[Line]) -> dict:
    xs0 = min(l.bbox[0] for l in lines)
    ys0 = min(l.bbox[1] for l in lines)
    xs1 = max(l.bbox[0] + l.bbox[2] for l in lines)
    ys1 = max(l.bbox[1] + l.bbox[3] for l in lines)
    return {"id": f"R{rid}", "type": rtype, "bbox": [xs0, ys0, xs1 - xs0, ys1 - ys0]}


def order_and_regionize(lines: list[Line], med_char_w: float, med_line_h: float, page_w: int) -> tuple[list[dict], list[dict]]:
    """Returns (regions, ordered line specs [{bbox, region_id}])."""
    diagrams = [l for l in lines if l.height > DIAGRAM_MIN_HEIGHT_LINES * med_line_h]
    text_lines = [l for l in lines if l not in diagrams]
    regions: list[dict] = []
    specs: list[dict] = []
    if not text_lines:
        regions.extend(_region(i, "diagram", [d]) for i, d in enumerate(diagrams))
        return regions, specs

    columns = cluster_columns(text_lines, med_char_w)
    main = max(columns, key=lambda c: sum(l.width for l in c.lines))
    for col in columns:
        col.lines.sort(key=lambda l: l.bbox[1])
        if col is main:
            n_problem = _problem_lines(col.lines)
            if n_problem:
                regions.append(_region(len(regions), "problem", col.lines[:n_problem]))
                specs.extend({"bbox": l.bbox, "region_id": regions[-1]["id"]} for l in col.lines[:n_problem])
            regions.append(_region(len(regions), "work", col.lines[n_problem:] or col.lines))
            specs.extend({"bbox": l.bbox, "region_id": regions[-1]["id"]} for l in col.lines[n_problem:])
        else:
            rtype = "margin" if _is_margin(col, main, page_w) else "work"
            regions.append(_region(len(regions), rtype, col.lines))
            specs.extend({"bbox": l.bbox, "region_id": regions[-1]["id"]} for l in col.lines)
    regions.extend(_region(len(regions) + i, "diagram", [d]) for i, d in enumerate(diagrams))
    return regions, specs
