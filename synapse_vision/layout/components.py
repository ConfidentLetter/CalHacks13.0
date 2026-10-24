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
STRONG_INK_PERCENTILE = 90      # "strong ink" contrast = this percentile over components (bleed may outnumber ink)
BAR_MIN_LEN_CHARS = 1.0         # a bar is a horizontal run at least this many char widths long
BAR_MIN_LEN_PX = 12
BAR_MAX_WIDTH_FRAC = 0.5        # of page width (longer = rule, not a fraction)
BAR_PROBE_FRAC = 0.9            # probe this many comp heights above/below the bar for stacked ink
BAR_MIN_STACK_INK = 0.5         # pixels of ink needed in a probe zone, x bar width
BAR_REACH_FRAC = 1.3            # how far above/below a numerator/denominator may extend, x comp height
BAR_X_SLACK_FRAC = 0.15         # numerator/denominator centers may overhang the bar by this
EQUALS_MAX_GAP_FRAC = 0.6       # two similar bars this close (x comp height) are an '=' sign


@dataclass(frozen=True)
class Component:
    x: int
    y: int
    w: int
    h: int
    area: int

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
    H, W = binary.shape[:2]
    min_area = speck_area(binary.shape)
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    comps: list[Component] = []
    bx, by = int(EDGE_BAND_FRAC * W), int(EDGE_BAND_FRAC * H)
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < min_area or w >= GIANT_FRAC * W or h >= GIANT_FRAC * H:
            continue
        if x + w <= bx or x >= W - bx or y + h <= by or y >= H - by:
            continue  # sliver of desk/shadow left along the page edge by an imperfect dewarp
        comps.append(Component(x, y, w, h, area))
    return comps


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
    keep = contrasts >= FAINT_CONTRAST_FRAC * strong
    return [c for c, k in zip(comps, keep) if k]


def median_component_size(comps: list[Component]) -> tuple[float, float]:
    """(median width, median height) of non-trivial components."""
    if not comps:
        return 10.0, 10.0
    hs = np.array([c.h for c in comps], dtype=float)
    ws = np.array([c.w for c in comps], dtype=float)
    big = hs >= np.percentile(hs, 40)
    return float(np.median(ws[big])), float(np.median(hs[big]))


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
    for other in bars:
        if other is bar or abs(other.w - bar.w) > 0.5 * max(bar.w, other.w):
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
    """Ink directly above AND below the bar, inside the bar's own x-span."""
    reach = max(4, int(BAR_PROBE_FRAC * med_h))
    inset = int(0.1 * bar.w)
    x0, x1 = bar.x + inset, bar.x1 - inset
    need = BAR_MIN_STACK_INK * bar.w
    above = _ink_rows(binary, x0, x1, bar.y - reach, bar.y - 1)
    below = _ink_rows(binary, x0, x1, bar.y1 + 1, bar.y1 + reach)
    return above >= need and below >= need


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
        if len(group) >= 2:
            remaining = [c for c in remaining if c not in group] + [union(group)]
    return remaining
