"""Group components into handwriting lines by local vertical overlap.

Baselines drift, so there is no global projection profile: components are
visited left to right and attached to the line whose *running* y-band (the
last few components) they overlap most.  Afterwards small vertically stacked
fragments (exponents, limits, underlines) are merged into their neighbour and
lines containing a wide gap with a baseline jump are split in two.
"""
from __future__ import annotations

import numpy as np

from layout.components import Component, union

ATTACH_MIN_OVERLAP = 0.40      # of the smaller height
ATTACH_MAX_GAP_CHARS = 3.0     # horizontal gap (in median char widths) to still attach ...
ATTACH_MAX_GAP_BANDS = 1.5     # ... or in multiples of the line's own band height (big handwriting on a page of small print)
BAND_MAX_COMP_H_FRAC = 2.0     # components taller than this x glyph height never define a band (fractions, arrows)
BAND_MEMORY = 6                # components that define the running band
FRAGMENT_MAX_HEIGHT_FRAC = 0.6 # of median line height
FRAGMENT_MERGE_GAP_FRAC = 0.6  # vertical gap (of median line height) to merge a fragment
FRAGMENT_MAX_X_GAP_CHARS = 1.0 # fragment may sit this far beside its line horizontally
SPLIT_GAP_CHARS = 3.0          # horizontal whitespace that may split a line ...
SPLIT_MIN_DY_FRAC = 0.5        # ... when baselines differ by this much (of line height)
MARGIN_ZONE_FRAC = 0.2         # outer page zones where a gapped part is a margin note
MIN_LINE_AREA_SPECKS = 3       # single-component lines below this many specks are noise
MIN_LINE_HEIGHT_FRAC = 0.25    # a line thinner than this x layout.min_line_height_px is a rule/underline remnant
DUPLICATE_MIN_Y_OVERLAP = 0.5  # x-overlapping lines sharing this much height are duplicates ...
DUPLICATE_MAX_HEIGHT_RATIO = 2 # ... when they are the same kind of line (a tall blob never swallows a line)


class Line:
    """A growing line of components with a cached bounding box (grouping touches every line per glyph)."""

    def __init__(self, comps: list[Component]):
        self._comps: list[Component] = list(comps)
        self._bbox: list[int] | None = None

    @property
    def comps(self) -> list[Component]:
        return self._comps

    @comps.setter
    def comps(self, value: list[Component]) -> None:
        self._comps = list(value)
        self._bbox = None

    def append(self, c: Component) -> None:
        self._comps.append(c)
        if self._bbox is not None:
            x0, y0 = min(self._bbox[0], c.x), min(self._bbox[1], c.y)
            x1, y1 = max(self._bbox[0] + self._bbox[2], c.x1), max(self._bbox[1] + self._bbox[3], c.y1)
            self._bbox = [x0, y0, x1 - x0, y1 - y0]

    @property
    def bbox(self) -> list[int]:
        if self._bbox is None:
            self._bbox = union(self._comps).bbox
        return self._bbox

    @property
    def x1(self) -> int:
        return self.bbox[0] + self.bbox[2]

    band_max_h: float = float("inf")  # components taller than this do not define the band (set per page)

    @property
    def band(self) -> tuple[int, int]:
        recent = self.comps[-BAND_MEMORY:]
        typical = [c for c in recent if c.h <= self.band_max_h] or recent
        return min(c.y for c in typical), max(c.y1 for c in typical)

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


def group_into_lines(comps: list[Component], med_char_w: float, med_comp_h: float | None = None) -> list[Line]:
    lines: list[Line] = []
    if med_comp_h is not None:
        Line.band_max_h = BAND_MAX_COMP_H_FRAC * med_comp_h
    for c in sorted(comps, key=lambda c: c.cx):
        best, best_px = None, 0
        for line in lines:
            band = line.band
            max_gap = max(ATTACH_MAX_GAP_CHARS * med_char_w, ATTACH_MAX_GAP_BANDS * (band[1] - band[0]))
            if c.x - line.x1 > max_gap:
                continue
            # eligible when the overlap is a decent share of the smaller height; ranked by
            # absolute overlap so a tiny band (an apostrophe, a dot) cannot win every glyph
            px = _overlap_px(c, band)
            if _overlap_fraction(c, band) >= ATTACH_MIN_OVERLAP and px > best_px:
                best, best_px = line, px
        if best is None:
            lines.append(Line([c]))
        else:
            best.append(c)
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
    """A fragment (exponent, subscript, dot, underline) is much shorter than its host and sits on or
    beside it. Real lines overlap vertically by a few px and tight print lines differ by 1-2 px in
    height, so both tests are relative to the host's OWN height, never to the page median."""
    hb, fb = host.bbox, frag.bbox
    x_gap, y_gap = _x_gap(fb, hb), _y_gap(fb, hb)
    scale = min(float(host.height), med_line_h)  # small print and big handwriting share one page
    return (frag.height < FRAGMENT_MAX_HEIGHT_FRAC * host.height
            and x_gap <= FRAGMENT_MAX_X_GAP_CHARS * med_char_w
            and y_gap < FRAGMENT_MERGE_GAP_FRAC * scale)


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
                same_scale = max(ab[3], bb[3]) <= DUPLICATE_MAX_HEIGHT_RATIO * max(1, min(ab[3], bb[3]))
                if _x_gap(ab, bb) < 0 and same_scale and y_ov >= DUPLICATE_MIN_Y_OVERLAP * min(ab[3], bb[3]):
                    a.comps = sorted(a.comps + b.comps, key=lambda c: c.cx)
                    lines = [l for l in lines if l is not b]
                    merged = True
                    break
            if merged:
                break
    return lines


def drop_noise_lines(lines: list[Line], speck: int, min_line_h: float) -> list[Line]:
    """Drop specks and anything far too thin to be handwriting (rule remnants, stray underlines)."""
    return [
        l for l in lines
        if not (len(l.comps) == 1 and l.comps[0].area < MIN_LINE_AREA_SPECKS * speck)
        and l.height >= MIN_LINE_HEIGHT_FRAC * min_line_h
    ]
