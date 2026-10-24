"""Group components into handwriting lines by local vertical overlap.

Baselines drift, so there is no global projection profile: components are
visited left to right and attached to the line whose *running* y-band (the
last few components) they overlap most.  Afterwards small vertically stacked
fragments (exponents, limits, underlines) are merged into their neighbour and
lines containing a wide gap with a baseline jump are split in two.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from layout.components import Component, union

ATTACH_MIN_OVERLAP = 0.40      # of the smaller height
ATTACH_MAX_GAP_CHARS = 3.0     # horizontal gap (in median char widths) to still attach
BAND_MEMORY = 6                # components that define the running band
FRAGMENT_MAX_HEIGHT_FRAC = 0.6 # of median line height
FRAGMENT_MERGE_GAP_FRAC = 0.6  # vertical gap (of median line height) to merge a fragment
FRAGMENT_MAX_X_GAP_CHARS = 1.0 # fragment may sit this far beside its line horizontally
STACK_MAX_WIDTH_FRAC = 0.6     # a stacked piece is at most this wide relative to its host ...
STACK_MERGE_GAP_FRAC = 0.25    # ... and at most this far (of median line height) above/below it
SPLIT_GAP_CHARS = 3.0          # horizontal whitespace that may split a line ...
SPLIT_MIN_DY_FRAC = 0.5        # ... when baselines differ by this much (of line height)
MARGIN_ZONE_FRAC = 0.2         # outer page zones where a gapped part is a margin note
MIN_LINE_AREA_SPECKS = 3       # single-component lines below this many specks are noise
DUPLICATE_MIN_Y_OVERLAP = 0.5  # x-overlapping lines sharing this much height are duplicates


@dataclass
class Line:
    comps: list[Component] = field(default_factory=list)

    @property
    def bbox(self) -> list[int]:
        return union(self.comps).bbox

    @property
    def x1(self) -> int:
        return max(c.x1 for c in self.comps)

    @property
    def band(self) -> tuple[int, int]:
        recent = self.comps[-BAND_MEMORY:]
        return min(c.y for c in recent), max(c.y1 for c in recent)

    @property
    def height(self) -> int:
        return self.bbox[3]

    @property
    def width(self) -> int:
        return self.bbox[2]


def _overlap_px(c: Component, band: tuple[int, int]) -> int:
    return max(0, min(c.y1, band[1]) - max(c.y, band[0]))


def _overlap_fraction(c: Component, band: tuple[int, int]) -> float:
    smaller = max(1, min(c.h, band[1] - band[0]))
    return _overlap_px(c, band) / smaller


def group_into_lines(comps: list[Component], med_char_w: float) -> list[Line]:
    lines: list[Line] = []
    max_gap = ATTACH_MAX_GAP_CHARS * med_char_w
    for c in sorted(comps, key=lambda c: c.cx):
        best, best_px = None, 0
        for line in lines:
            if c.x - line.x1 > max_gap:
                continue
            # eligible when the overlap is a decent share of the smaller height; ranked by
            # absolute overlap so a tiny band (an apostrophe, a dot) cannot win every glyph
            px = _overlap_px(c, line.band)
            if _overlap_fraction(c, line.band) >= ATTACH_MIN_OVERLAP and px > best_px:
                best, best_px = line, px
        if best is None:
            lines.append(Line([c]))
        else:
            best.comps.append(c)
    return lines


def median_line_height(lines: list[Line]) -> float:
    major = [l.height for l in lines if len(l.comps) >= 3]
    pool = major or [l.height for l in lines] or [1]
    return float(np.median(pool))


def _x_gap(a: list[int], b: list[int]) -> float:
    return max(a[0] - (b[0] + b[2]), b[0] - (a[0] + a[2]))


def _y_gap(a: list[int], b: list[int]) -> float:
    return max(a[1] - (b[1] + b[3]), b[1] - (a[1] + a[3]))


def merge_fragments(lines: list[Line], med_line_h: float, med_char_w: float) -> list[Line]:
    """Attach short stacked fragments (exponents, underlines, limits) to the nearest line."""
    lines = sorted(lines, key=lambda l: l.bbox[1])
    changed = True
    while changed:
        changed = False
        for frag in sorted(lines, key=lambda l: l.width):
            fb = frag.bbox
            candidates = [
                (_y_gap(fb, host.bbox), host)
                for host in lines
                if host is not frag and _absorbs(host, frag, med_line_h, med_char_w)
            ]
            if candidates:
                _, host = min(candidates, key=lambda t: t[0])
                host.comps = sorted(host.comps + frag.comps, key=lambda c: c.cx)
                lines = [l for l in lines if l is not frag]
                changed = True
                break
    return lines


def _absorbs(host: Line, frag: Line, med_line_h: float, med_char_w: float) -> bool:
    hb, fb = host.bbox, frag.bbox
    x_gap, y_gap = _x_gap(fb, hb), _y_gap(fb, hb)
    short_piece = (frag.height < FRAGMENT_MAX_HEIGHT_FRAC * med_line_h and host.height > frag.height
                   and x_gap <= FRAGMENT_MAX_X_GAP_CHARS * med_char_w and y_gap < FRAGMENT_MERGE_GAP_FRAC * med_line_h)
    inside = fb[0] >= hb[0] - med_char_w and fb[0] + fb[2] <= hb[0] + hb[2] + med_char_w
    stacked_piece = (frag.width <= STACK_MAX_WIDTH_FRAC * host.width and inside and y_gap < STACK_MERGE_GAP_FRAC * med_line_h)
    return short_piece or stacked_piece


def _in_margin_zone(bbox: list[int], page_w: int) -> bool:
    return bbox[0] >= (1 - MARGIN_ZONE_FRAC) * page_w or bbox[0] + bbox[2] <= MARGIN_ZONE_FRAC * page_w


def _should_split(left: list[Component], right: list[Component], med_line_h: float, page_w: int) -> bool:
    lb, rb = union(left).bbox, union(right).bbox
    dy = abs((lb[1] + lb[3] / 2) - (rb[1] + rb[3] / 2))
    if dy > SPLIT_MIN_DY_FRAC * med_line_h:
        return True
    return _in_margin_zone(lb, page_w) != _in_margin_zone(rb, page_w) and (_in_margin_zone(lb, page_w) or _in_margin_zone(rb, page_w))


def split_columns(lines: list[Line], med_line_h: float, med_char_w: float, page_w: int) -> list[Line]:
    """Split a line at a wide whitespace gap when the two halves sit on different baselines or in a margin."""
    out: list[Line] = []
    for line in lines:
        comps = sorted(line.comps, key=lambda c: c.x)
        parts: list[list[Component]] = [[comps[0]]]
        right_edge = comps[0].x1
        for c in comps[1:]:
            if c.x - right_edge > SPLIT_GAP_CHARS * med_char_w and _should_split(parts[-1], [c], med_line_h, page_w):
                parts.append([c])
            else:
                parts[-1].append(c)
            right_edge = max(right_edge, c.x1)
        out.extend(Line(p) for p in parts)
    return out


def merge_duplicates(lines: list[Line]) -> list[Line]:
    """Two lines sharing horizontal space and most of their height are one line (safety net)."""
    merged = True
    while merged:
        merged = False
        for i, a in enumerate(lines):
            for b in lines[i + 1:]:
                ab, bb = a.bbox, b.bbox
                y_ov = min(ab[1] + ab[3], bb[1] + bb[3]) - max(ab[1], bb[1])
                if _x_gap(ab, bb) < 0 and y_ov >= DUPLICATE_MIN_Y_OVERLAP * min(ab[3], bb[3]):
                    a.comps = sorted(a.comps + b.comps, key=lambda c: c.cx)
                    lines = [l for l in lines if l is not b]
                    merged = True
                    break
            if merged:
                break
    return lines


def drop_noise_lines(lines: list[Line], speck: int) -> list[Line]:
    return [l for l in lines if not (len(l.comps) == 1 and l.comps[0].area < MIN_LINE_AREA_SPECKS * speck)]
