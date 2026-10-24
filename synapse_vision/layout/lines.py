"""Group components into handwriting lines by local neighbour links.

Baselines drift, so there is no global projection profile: every glyph is
linked to the compatible glyphs just to its right (small horizontal gap,
centres on about the same height, some vertical overlap) and the connected
groups are the lines.  Afterwards small stacked fragments (exponents,
subscripts, underlines, '=' halves) are merged into their neighbour and lines
containing a wide gap with a baseline jump are split in two.
"""
from __future__ import annotations

import numpy as np

from layout.components import Component, union

LINK_MAX_GAP_CHARS = 2.5       # horizontal gap (in char widths) that still links two glyphs
LINK_MIN_OVERLAP = 0.3         # vertical overlap of the smaller glyph (tight print: next line overlaps nothing)
LINK_DY_FRAC = 0.5             # centres may differ by this x the smaller glyph height (sloppy pencil)
TALL_GLYPH_FRAC = 2.2          # a component taller than this x the typical glyph (bracket, fraction, big Σ) never
                               # links two lines: it joins the one line it overlaps most
ADJACENT_MAX_X_GAP_CHARS = 2.5 # pieces of one line sit side by side: at most this gap ...
ADJACENT_MAX_X_OVERLAP_CHARS = 2.0  # ... and at most this overlap (stacked lines overlap far more)
ADJACENT_MAX_DY_FRAC = 0.8     # centres within this x the taller piece's height
FRAGMENT_HOST_MIN_RATIO = 1.3  # a fragment's host is at least this much taller (measured beside the fragment)
FRAGMENT_MIN_OVERLAP = 0.1     # a piece overlapping its host by this much of its own height (subscript, exponent,
                               # '=' half) merges whatever its size ...
FRAGMENT_MAX_HEIGHT_FRAC = 0.8 # ... a piece with a gap below/above the host (dot, bar, underline) must be shorter
FRAGMENT_MERGE_GAP_FRAC = 0.6  #     than this x glyph height and closer than this x line height
STACK_MAX_WIDTH_FRAC = 0.6     # a full-height superscript/subscript group: narrower than this x its host, inside the
STACK_MAX_UNION_FRAC = 1.8     # host's x-range, touching it, and together not taller than this x the host beside it
STACK_MAX_GAP_FRAC = 0.15      # "touching": at most this x glyph height apart (an erased rule leaves a hairline gap)
FRAGMENT_MAX_X_GAP_CHARS = 1.0 # fragment may sit this far beside its line horizontally
FRAGMENT_LOCAL_CHARS = 2.0     # the host's height is measured from its glyphs within this many chars of the fragment
SPLIT_GAP_CHARS = 3.0          # horizontal whitespace that may split a line ...
SPLIT_MIN_DY_FRAC = 0.5        # ... when baselines differ by this much (of line height)
MARGIN_ZONE_FRAC = 0.2         # outer page zones where a gapped part is a margin note
MIN_LINE_AREA_SPECKS = 3       # single-component lines below this many specks are noise
MIN_LINE_HEIGHT_FRAC = 0.25    # a line thinner than this x layout.min_line_height_px is a rule/underline remnant
DUPLICATE_MIN_Y_OVERLAP = 0.8  # x-overlapping lines sharing this much height are duplicates (tilted neighbours share less) ...
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

    @property
    def height(self) -> int:
        return self.bbox[3]

    @property
    def width(self) -> int:
        return self.bbox[2]


def _compatible(a: Component, b: Component, glyph_h: float) -> bool:
    """Same line: centres at about the same height and some vertical overlap."""
    overlap = min(a.y1, b.y1) - max(a.y, b.y)
    if overlap < LINK_MIN_OVERLAP * min(a.h, b.h):
        return False
    return abs(a.cy - b.cy) <= LINK_DY_FRAC * min(a.h, b.h)


def _link_glyphs(comps: list[Component], glyph_h: float, max_gap: float) -> list[list[Component]]:
    comps = sorted(comps, key=lambda c: c.x)
    parent = list(range(len(comps)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, c in enumerate(comps):
        for j in range(i + 1, len(comps)):
            d = comps[j]
            if d.x - c.x1 > max_gap:
                break
            if _compatible(c, d, glyph_h):
                parent[find(i)] = find(j)
    groups: dict[int, list[Component]] = {}
    for i, c in enumerate(comps):
        groups.setdefault(find(i), []).append(c)
    return list(groups.values())


def _attach_tall(lines: list[Line], tall: list[Component], max_gap: float) -> list[Line]:
    """Each tall component joins the nearby line it overlaps most vertically, or starts its own."""
    for c in sorted(tall, key=lambda c: c.x):
        best, best_px = None, 0
        for line in lines:
            lb = line.bbox
            if _x_gap(c.bbox, lb) > max_gap:
                continue
            px = min(c.y1, lb[1] + lb[3]) - max(c.y, lb[1])
            if px > best_px:
                best, best_px = line, px
        if best is None:
            lines.append(Line([c]))
        else:
            best.append(c)
    return lines


def group_into_lines(comps: list[Component], med_char_w: float, med_comp_h: float | None = None) -> list[Line]:
    glyph_h = med_comp_h if med_comp_h is not None else med_char_w
    max_gap = LINK_MAX_GAP_CHARS * med_char_w
    normal = [c for c in comps if c.h <= TALL_GLYPH_FRAC * glyph_h]
    tall = [c for c in comps if c.h > TALL_GLYPH_FRAC * glyph_h]
    lines = [Line(sorted(g, key=lambda c: c.cx)) for g in _link_glyphs(normal, glyph_h, max_gap)]
    return _attach_tall(lines, tall, max_gap)


def _side_by_side(a: list[int], b: list[int], med_char_w: float) -> bool:
    gap = _x_gap(a, b)
    return -ADJACENT_MAX_X_OVERLAP_CHARS * med_char_w <= gap <= ADJACENT_MAX_X_GAP_CHARS * med_char_w


def merge_adjacent(lines: list[Line], med_char_w: float) -> list[Line]:
    """Join pieces of one handwritten line that the strict glyph links missed: a tall 'ΣF' written
    above the baseline, a term that drifted downwards.  Pieces must sit side by side (little x-overlap),
    overlap vertically and have centres within the taller piece's height; stacked lines never qualify."""
    merged = True
    while merged:
        merged = False
        for i, a in enumerate(lines):
            for b in lines[i + 1:]:
                ab, bb = a.bbox, b.bbox
                y_ov = min(ab[1] + ab[3], bb[1] + bb[3]) - max(ab[1], bb[1])
                dy = abs((ab[1] + ab[3] / 2) - (bb[1] + bb[3] / 2))
                if _side_by_side(ab, bb, med_char_w) and y_ov > 0 and dy <= ADJACENT_MAX_DY_FRAC * max(ab[3], bb[3]):
                    a.comps = sorted(a.comps + b.comps, key=lambda c: c.cx)
                    lines = [l for l in lines if l is not b]
                    merged = True
                    break
            if merged:
                break
    return lines


def median_line_height(lines: list[Line]) -> float:
    major = [l.height for l in lines if len(l.comps) >= 3]
    pool = major or [l.height for l in lines] or [1]
    return float(np.median(pool))


def _x_gap(a: list[int], b: list[int]) -> float:
    return max(a[0] - (b[0] + b[2]), b[0] - (a[0] + a[2]))


def _y_gap(a: list[int], b: list[int]) -> float:
    return max(a[1] - (b[1] + b[3]), b[1] - (a[1] + a[3]))


def merge_fragments(lines: list[Line], med_line_h: float, med_char_w: float, med_comp_h: float | None = None) -> list[Line]:
    """Attach short stacked fragments (exponents, underlines, limits) to the nearest line."""
    glyph_h = med_comp_h if med_comp_h is not None else 0.6 * med_line_h
    lines = sorted(lines, key=lambda l: l.bbox[1])
    changed = True
    while changed:
        changed = False
        for frag in sorted(lines, key=lambda l: l.width):
            fb = frag.bbox
            candidates = [
                (_y_gap(fb, host.bbox), host)
                for host in lines
                if host is not frag and (_absorbs(host, frag, med_line_h, med_char_w, glyph_h) or _stacked(host, frag, med_char_w, glyph_h))
            ]
            if candidates:
                _, host = min(candidates, key=lambda t: t[0])
                host.comps = sorted(host.comps + frag.comps, key=lambda c: c.cx)
                lines = [l for l in lines if l is not frag]
                changed = True
                break
    return lines


def _absorbs(host: Line, frag: Line, med_line_h: float, med_char_w: float, glyph_h: float) -> bool:
    """A fragment (exponent, subscript, dot, underline, '=' half) is much shorter than the part of its
    host beside it and either overlaps it vertically or is a small mark sitting just above/below.
    The host height is measured locally so a sloping row never swallows the next row's glyphs."""
    fb = frag.bbox
    hb = _local_bbox(host, fb, FRAGMENT_LOCAL_CHARS * med_char_w)
    if hb[3] < FRAGMENT_HOST_MIN_RATIO * frag.height or _x_gap(fb, hb) > FRAGMENT_MAX_X_GAP_CHARS * med_char_w:
        return False
    y_gap = _y_gap(fb, hb)
    if y_gap <= -FRAGMENT_MIN_OVERLAP * fb[3]:
        return True
    scale = min(float(hb[3]), med_line_h)  # small print and big handwriting share one page
    return fb[3] < FRAGMENT_MAX_HEIGHT_FRAC * glyph_h and y_gap < FRAGMENT_MERGE_GAP_FRAC * scale


def _stacked(host: Line, frag: Line, med_char_w: float, glyph_h: float) -> bool:
    """A narrow group riding on its host (a tall exponent, a limit): inside the host's x-range, touching it,
    and not making it much taller.  A piece of the next row is wide or leaves a gap."""
    fb, hb_full = frag.bbox, host.bbox
    if fb[2] > STACK_MAX_WIDTH_FRAC * hb_full[2]:
        return False
    if fb[0] < hb_full[0] - med_char_w or fb[0] + fb[2] > hb_full[0] + hb_full[2] + med_char_w:
        return False
    hb = _local_bbox(host, fb, FRAGMENT_LOCAL_CHARS * med_char_w)
    if _y_gap(fb, hb) > STACK_MAX_GAP_FRAC * glyph_h:
        return False
    union_h = max(fb[1] + fb[3], hb[1] + hb[3]) - min(fb[1], hb[1])
    return union_h <= STACK_MAX_UNION_FRAC * hb[3]


def _local_bbox(host: Line, around: list[int], reach: float) -> list[int]:
    """Bbox of the host's components within ``reach`` px of ``around`` horizontally (nearest two if none)."""
    x0, x1 = around[0] - reach, around[0] + around[2] + reach
    near = [c for c in host.comps if c.x1 >= x0 and c.x <= x1]
    if not near:
        near = sorted(host.comps, key=lambda c: _x_gap(c.bbox, around))[:2]
    return union(near).bbox


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
