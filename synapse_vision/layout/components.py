"""Connected components of the ink mask, speck filtering and fraction fusion.

A *fraction bar* is a short thin horizontal component with ink directly above
and below it; the bar, numerator and denominator are fused into one component
before line grouping so a denominator can never become its own line.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

SPECK_AREA_PER_PIXEL = 4e-6     # speck threshold = this x page area (≈15 px on 1700x2200)
SPECK_AREA_MIN = 6
GIANT_FRAC = 0.9                # components this big are borders, not ink
EDGE_BAND_FRAC = 0.02           # ink lying entirely within this outer band of the page is a dewarp border artifact
FAINT_CONTRAST_FRAC = 0.5       # components lighter than this x the page's strong-ink contrast are bleed-through
FAINT_KEEP_ABS = 60             # ... and never drop anything with at least this much contrast (light pencil)
TALL_COMP_FRAC = 5.0            # a component taller than this x the typical glyph height is drawing, not writing
BAR_FLANK_FRAC = 1.5            # flank width (x bar width) checked beside a fraction stack ...
BAR_FLANK_MAX_RATIO = 0.5       # ... ink in the OUTER half-rows there (where inline text never reaches, but a
                                #     neighbouring text line does) must stay below this fraction of the stack's ink
TEXTURE_MAX_FRAC = 0.8          # a component smaller than this x glyph size in both directions is a speck ...
TEXTURE_RADIUS_GLYPHS = 1.5     # ... and with at least TEXTURE_MIN_NEIGHBOURS specks within this radius it is
TEXTURE_MIN_NEIGHBOURS = 5      #     halftone texture of a printed figure, not an i-dot or a decimal point
TEXTURE_MIN_Y_SPREAD = 0.4      # ... and those neighbours are spread vertically by this x glyph height (text rows are flat)
TEXTURE_MAX_DROP_FRAC = 0.5     # never drop more than this share of all components as texture (bad glyph estimate)
SLIVER_MAX_W_FRAC = 0.6         # a rule remnant: narrower than this x glyph width ...
SLIVER_MIN_H_FRAC = 1.5         # ... taller than this x glyph height, at least SLIVER_MIN_ASPECT times taller than wide,
SLIVER_MIN_ASPECT = 4.0         #     and stacked in one column with others (printed margin line the dewarp left in pieces)
SLIVER_MIN_IN_COLUMN = 3        # column members needed anywhere on the page ...
SLIVER_MIN_IN_MARGIN = 2        # ... or this many inside the outer page zones
SLIVER_MARGIN_FRAC = 0.15
COLUMN_MIN_PIECES = 5           # narrow pieces of any height stacked in one tight column (x within
COLUMN_MIN_SPAN_H = 3.0         # COLUMN_TOL_FRAC x glyph width) inside the margin zone, over at least
COLUMN_TOL_FRAC = 0.15          # COLUMN_MIN_SPAN_H glyph heights, are also a broken rule; thin letters
                                # (l, 1, i) stacked by chance in a paragraph scatter more than that
ISOLATED_TINY_FRAC = 0.4        # a mark smaller than this x glyph size needs ink within ISOLATED_TINY_RADIUS glyphs
ISOLATED_TINY_RADIUS = 1.2
ISOLATED_MAX_FRAC = 0.8         # a component smaller than this x glyph size in both directions ...
ISOLATED_RADIUS_GLYPHS = 2.5    # ... with no other component within this many glyphs is a stray mark (rule crossing,
                                #     dust, dewarp speck); real dots and commas sit next to writing
GLYPH_MAX_ASPECT = 4.0          # wider than this x its height is not a glyph (rule, bar, chained letters)
GLYPH_MIN_H_FRAC = 0.4          # glyph candidates are at least this x the typical component height (not dots)
GLYPH_MIN_H_PX = 5              # and at least this tall in pixels (rule remnants are 1-3 px)
GLYPH_MIN_SHARE = 0.3           # fewer single glyphs than this share of components = chained writing ...
GLYPH_W_PER_H = 0.9             # ... then a char is about this x its height wide
STRONG_INK_PERCENTILE = 90      # "strong ink" contrast = this percentile over components (bleed may outnumber ink)
BAR_MIN_LEN_CHARS = 1.0         # a bar is a horizontal run at least this many char widths long
BAR_MIN_LEN_PX = 12
BAR_MAX_WIDTH_FRAC = 0.5        # of page width (longer = rule, not a fraction)
BAR_PROBE_FRAC = 0.9            # probe this many comp heights above/below the bar for stacked ink
BAR_MIN_STACK_INK = 0.5         # pixels of ink needed in a probe zone, x bar width
BAR_REACH_FRAC = 1.3            # how far above/below a numerator/denominator may extend, x comp height
BAR_X_SLACK_FRAC = 0.15         # numerator/denominator centers may overhang the bar by this
EQUALS_MAX_GAP_FRAC = 0.6       # two similar bars this close (x comp height) are an '=' sign ...
EQUALS_MAX_WIDTH_FRAC = 2.0     # ... when no wider than this x glyph height (a stacked pair of fraction bars is not)
EQUALS_MAX_THICKNESS_DIFF = 3   # ... and equally thick (px)
STACK_MAX_HEIGHT_FRAC = 4.5     # a fused fraction taller than this x comp height is two lines, not a fraction


@dataclass(frozen=True)
class Component:
    x: int
    y: int
    w: int
    h: int
    area: int
    label: int = -1   # id in the label image of find_components_with_labels (-1 when unknown)

    @property
    def x1(self) -> int:
        return self.x + self.w

    @property
    def y1(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def bbox(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]


def speck_area(shape: tuple[int, ...]) -> int:
    return max(SPECK_AREA_MIN, int(shape[0] * shape[1] * SPECK_AREA_PER_PIXEL))


def find_components(binary: np.ndarray) -> list[Component]:
    return find_components_with_labels(binary)[0]


def ink_mask(labels: np.ndarray, comps: list[Component]) -> np.ndarray:
    """Binary mask of exactly these components (what survives the speck / faint / texture filters)."""
    keep = np.isin(labels, [c.label for c in comps if c.label >= 0])
    return keep.astype(np.uint8) * 255


def find_components_with_labels(binary: np.ndarray) -> tuple[list[Component], np.ndarray]:
    H, W = binary.shape[:2]
    min_area = speck_area(binary.shape)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    comps: list[Component] = []
    bx, by = int(EDGE_BAND_FRAC * W), int(EDGE_BAND_FRAC * H)
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < min_area or w >= GIANT_FRAC * W or h >= GIANT_FRAC * H:
            continue
        if x + w <= bx or x >= W - bx or y + h <= by or y >= H - by:
            continue  # sliver of desk/shadow left along the page edge by an imperfect dewarp
        comps.append(Component(x, y, w, h, area, i))
    return comps, labels


def component_contrast(c: Component, gray: np.ndarray, binary: np.ndarray, background: float) -> float:
    """Background minus the mean gray of the component's ink pixels (bbox approximation)."""
    region = gray[c.y : c.y1, c.x : c.x1]
    mask = binary[c.y : c.y1, c.x : c.x1] > 0
    if not mask.any():
        return 0.0
    return float(background - region[mask].mean())


def drop_faint_components(comps: list[Component], gray: np.ndarray, binary: np.ndarray) -> list[Component]:
    """Ink bleeding through from the back of the page is much lighter than the page's own ink: drop it."""
    if len(comps) < 2:
        return comps
    background = float(np.median(gray))
    contrasts = np.array([component_contrast(c, gray, binary, background) for c in comps])
    strong = float(np.percentile(contrasts, STRONG_INK_PERCENTILE))
    keep = (contrasts >= FAINT_CONTRAST_FRAC * strong) | (contrasts >= FAINT_KEEP_ABS)
    return [c for c, k in zip(comps, keep) if k]


def drop_texture_specks(comps: list[Component], med_char_w: float, med_h: float) -> list[Component]:
    """Remove halftone texture: clusters of specks far smaller than a glyph (shaded blocks in a printed
    figure).  Isolated small marks (dots, commas, decimal points, dashes) have few speck neighbours."""
    small = [i for i, c in enumerate(comps) if c.w < TEXTURE_MAX_FRAC * med_char_w and c.h < TEXTURE_MAX_FRAC * med_h]
    if len(small) <= TEXTURE_MIN_NEIGHBOURS:
        return comps
    pts = np.array([(comps[i].cx, comps[i].cy) for i in small], dtype=np.float32)
    radius = TEXTURE_RADIUS_GLYPHS * max(med_char_w, med_h)
    d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
    near = d2 <= radius * radius
    neighbours = near.sum(1) - 1
    ys = np.where(near, pts[None, :, 1], np.nan)
    y_spread = np.nanstd(ys, axis=1)
    texture = {small[k] for k in np.flatnonzero((neighbours >= TEXTURE_MIN_NEIGHBOURS)
                                                & (y_spread >= TEXTURE_MIN_Y_SPREAD * med_h))}
    if len(texture) > TEXTURE_MAX_DROP_FRAC * len(comps):
        return comps
    return [c for i, c in enumerate(comps) if i not in texture]


def drop_rule_slivers(comps: list[Component], med_char_w: float, med_h: float, page_w: int) -> list[Component]:
    """Remove pieces of a printed vertical rule (notebook margin line) that survived rule removal: narrow
    pieces lined up in one column.  Tall slivers need three in a column (two inside the page margins);
    pieces of any height need five spanning several line heights.  Big parentheses are thin and tall too
    but never line up like that."""
    narrow = [c for c in comps if c.w < SLIVER_MAX_W_FRAC * med_char_w and c.h >= c.w]
    if len(narrow) < SLIVER_MIN_IN_MARGIN:
        return comps
    tol, tight = 0.5 * med_char_w, max(3.0, COLUMN_TOL_FRAC * med_char_w)
    drop: set[int] = set()
    for c in narrow:
        column = [o for o in narrow if abs(o.cx - c.cx) <= tol]
        tall = [o for o in column if o.h >= SLIVER_MIN_H_FRAC * med_h and o.h >= SLIVER_MIN_ASPECT * o.w]
        in_margin = c.cx <= SLIVER_MARGIN_FRAC * page_w or c.cx >= (1 - SLIVER_MARGIN_FRAC) * page_w
        if len(tall) >= SLIVER_MIN_IN_COLUMN or (in_margin and len(tall) >= SLIVER_MIN_IN_MARGIN):
            drop.update(id(o) for o in column)
            continue
        if not in_margin:
            continue
        aligned = [o for o in column if abs(o.cx - c.cx) <= tight]
        span = max(o.y1 for o in aligned) - min(o.y for o in aligned)
        if len(aligned) >= COLUMN_MIN_PIECES and span >= COLUMN_MIN_SPAN_H * med_h:
            drop.update(id(o) for o in aligned)
    return [c for c in comps if id(c) not in drop]


def drop_isolated_specks(comps: list[Component], med_char_w: float, med_h: float) -> list[Component]:
    """Remove lone marks far from any other ink (remnants of printed rule crossings, dust)."""
    if len(comps) < 2:
        return comps
    pts = np.array([(c.cx, c.cy) for c in comps], dtype=np.float32)
    radius = ISOLATED_RADIUS_GLYPHS * max(med_char_w, med_h)
    small = np.array([c.w < ISOLATED_MAX_FRAC * med_char_w and c.h < ISOLATED_MAX_FRAC * med_h for c in comps])
    tiny = np.array([c.w < ISOLATED_TINY_FRAC * med_char_w and c.h < ISOLATED_TINY_FRAC * med_h for c in comps])
    if small.all():
        return comps
    anchors = pts[~small]   # a mark counts as writing only when glyph-sized ink is nearby (two stray dots do not)
    tiny_radius = ISOLATED_TINY_RADIUS * max(med_char_w, med_h)
    keep = []
    for i, c in enumerate(comps):
        limit = tiny_radius if tiny[i] else radius
        if not small[i] or ((anchors - pts[i]) ** 2).sum(1).min() <= limit * limit:
            keep.append(c)
    return keep


def split_tall_components(comps: list[Component], med_h: float) -> tuple[list[Component], list[Component]]:
    """(writing-sized components, tall drawing components such as free-body diagrams and big circled answers)."""
    limit = TALL_COMP_FRAC * med_h
    return [c for c in comps if c.h <= limit], [c for c in comps if c.h > limit]


def median_component_size(comps: list[Component]) -> tuple[float, float]:
    """Typical glyph (width, height): medians over letter-like components, ignoring specks and long thin
    pieces (rule remnants, bars, arrows, letters chained by a rule) that are not single glyphs."""
    if not comps:
        return 10.0, 10.0
    letters = [c for c in comps if c.h >= GLYPH_MIN_H_PX and c.w <= GLYPH_MAX_ASPECT * c.h] or comps
    hs_all = np.array([c.h for c in letters], dtype=float)
    med_h = float(np.median(hs_all[hs_all >= np.percentile(hs_all, 40)]))
    glyphs = [c for c in letters if c.h >= GLYPH_MIN_H_FRAC * med_h]
    if len(glyphs) < GLYPH_MIN_SHARE * len(comps):   # letters chained into word blobs: width ~ height
        return GLYPH_W_PER_H * med_h, med_h
    ws = np.array([c.w for c in glyphs], dtype=float)
    hs = np.array([c.h for c in glyphs], dtype=float)
    return float(np.median(ws)), float(np.median(hs))


def union(comps: list[Component]) -> Component:
    x0 = min(c.x for c in comps)
    y0 = min(c.y for c in comps)
    x1 = max(c.x1 for c in comps)
    y1 = max(c.y1 for c in comps)
    return Component(x0, y0, x1 - x0, y1 - y0, sum(c.area for c in comps))


def _find_bars(binary: np.ndarray, med_char_w: float, page_w: int) -> list[Component]:
    """Horizontal strokes at least ~1 char wide and shorter than half the page (bars, minus, '=' halves, strikes)."""
    bar_len = max(BAR_MIN_LEN_PX, int(BAR_MIN_LEN_CHARS * med_char_w))
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (bar_len, 1)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    bars = [Component(*(int(v) for v in stats[i])) for i in range(1, n)]
    return [b for b in bars if b.w < BAR_MAX_WIDTH_FRAC * page_w]


def _is_equals_half(bar: Component, bars: list[Component], med_h: float) -> bool:
    """One of the two short, equally thick, stacked bars of an '=' sign (a fraction bar is far wider)."""
    if bar.w > EQUALS_MAX_WIDTH_FRAC * med_h:
        return False
    for other in bars:
        if other is bar or abs(other.w - bar.w) > 0.5 * max(bar.w, other.w) or abs(other.h - bar.h) > EQUALS_MAX_THICKNESS_DIFF:
            continue
        if abs(other.cx - bar.cx) <= 0.5 * bar.w and 0 < abs(other.cy - bar.cy) <= EQUALS_MAX_GAP_FRAC * med_h:
            return True
    return False


def _ink_rows(binary: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> int:
    H, W = binary.shape
    x0, x1, y0, y1 = max(0, x0), min(W, x1), max(0, y0), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return 0
    return int(np.count_nonzero(binary[y0:y1, x0:x1]))


def _is_fraction_bar(bar: Component, binary: np.ndarray, med_h: float) -> bool:
    """Ink directly above AND below the bar inside its x-span, and little ink beside that stack
    (a hyphen between two text lines has ink above and below too, but the flanks are full of text)."""
    reach = max(4, int(BAR_PROBE_FRAC * med_h))
    inset = int(0.1 * bar.w)
    x0, x1 = bar.x + inset, bar.x1 - inset
    need = BAR_MIN_STACK_INK * bar.w
    above = _ink_rows(binary, x0, x1, bar.y - reach, bar.y - 1)
    below = _ink_rows(binary, x0, x1, bar.y1 + 1, bar.y1 + reach)
    if above < need or below < need:
        return False
    flank, half = max(4, int(BAR_FLANK_FRAC * bar.w)), reach // 2
    beside = sum(_ink_rows(binary, fx0, fx1, fy0, fy1)
                 for fx0, fx1 in ((bar.x - flank, bar.x), (bar.x1, bar.x1 + flank))
                 for fy0, fy1 in ((bar.y - reach, bar.y - half), (bar.y1 + half, bar.y1 + reach)))
    return beside <= BAR_FLANK_MAX_RATIO * (above + below)


def _in_stack(bar: Component, c: Component, med_h: float) -> bool:
    slack = BAR_X_SLACK_FRAC * bar.w
    if c.x <= bar.x and c.x1 >= bar.x1 and c.y <= bar.y and c.y1 >= bar.y1:
        return True  # the component that carries the bar itself
    if not (bar.x - slack <= c.cx <= bar.x1 + slack) or c.w > 1.6 * bar.w + 4:
        return False
    reach = BAR_REACH_FRAC * med_h
    return c.y1 >= bar.y - reach and c.y <= bar.y1 + reach


def fuse_fractions(comps: list[Component], binary: np.ndarray, med_char_w: float, med_h: float, page_w: int) -> list[Component]:
    """Merge numerator + bar + denominator stacks into single components."""
    bars = _find_bars(binary, med_char_w, page_w)
    remaining = list(comps)
    for bar in bars:
        if _is_equals_half(bar, bars, med_h) or not _is_fraction_bar(bar, binary, med_h):
            continue
        group = [c for c in remaining if _in_stack(bar, c, med_h)]
        if len(group) >= 2 and union(group).h <= STACK_MAX_HEIGHT_FRAC * med_h:
            grouped = {id(c) for c in group}
            remaining = [c for c in remaining if id(c) not in grouped] + [union(group)]
    return remaining
