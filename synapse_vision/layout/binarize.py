"""Binarization and ruled-line removal for a dewarped page.

Sauvola thresholding (window ~1.5 x typical line height) handles uneven
lighting and faint pencil; long thin horizontal / vertical structures that
span most of the page (notebook rules, the left margin rule, graph-paper grid)
are erased without touching handwriting that crosses them.
"""
from __future__ import annotations

import cv2
import numpy as np

from layout._compat import config_get

SAUVOLA_K = 0.2
SAUVOLA_R = 128.0
MIN_INK_CONTRAST = 20          # pixel must be this much darker than the local mean
RULE_MIN_CONTRAST = 8          # lenient contrast used only to *find* faint printed rules
WINDOW_PER_LINE_HEIGHT = 1.5
MAX_LINE_HEIGHT_FRAC = 0.10    # of page height, for the line-height estimate
RULE_MIN_SPAN_FRAC = 0.75      # a rule spans at least this fraction of the page
RULE_MAX_THICKNESS_PX = 6      # thicker horizontal structures are handwriting (strikes, bars)
RULE_SEED_RUN_FRAC = 1 / 40    # minimum straight run to seed a rule candidate
RULE_BRIDGE_FRAC = 1 / 100     # bridge gaps along a slightly tilted rule


def to_gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _odd(n: float) -> int:
    n = int(round(n))
    return n if n % 2 == 1 else n + 1


def estimate_line_height(gray: np.ndarray) -> int:
    """Rough typical handwriting line height from an Otsu pass (bounded by config)."""
    min_h = int(config_get("layout.min_line_height_px", 28))
    max_h = max(min_h + 1, int(gray.shape[0] * MAX_LINE_HEIGHT_FRAC))
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, _, stats, _ = cv2.connectedComponentsWithStats(otsu, connectivity=8)
    heights = stats[1:, cv2.CC_STAT_HEIGHT]
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = heights[(areas > 20) & (heights < max_h)]
    if len(keep) == 0:
        return min_h
    return int(np.clip(2.0 * float(np.median(keep)), min_h, max_h))


def sauvola(gray: np.ndarray, window: int, k: float = SAUVOLA_K, r: float = SAUVOLA_R) -> tuple[np.ndarray, np.ndarray]:
    """Sauvola binarization. Returns (ink mask, lenient low-contrast mask) as uint8 masks with 255 = dark.

    The lenient mask (anything a little darker than its surroundings) is only used to
    locate printed rules, which Sauvola proper picks up near text but not on blank paper."""
    window = _odd(max(3, window))
    g = gray.astype(np.float64)
    mean = cv2.boxFilter(g, -1, (window, window), normalize=True, borderType=cv2.BORDER_REFLECT)
    sq = cv2.boxFilter(g * g, -1, (window, window), normalize=True, borderType=cv2.BORDER_REFLECT)
    std = np.sqrt(np.maximum(sq - mean * mean, 0.0))
    thresh = mean * (1.0 + k * (std / r - 1.0))
    ink = (g < thresh) & (g < mean - MIN_INK_CONTRAST)
    lenient = g < mean - RULE_MIN_CONTRAST
    return ink.astype(np.uint8) * 255, lenient.astype(np.uint8) * 255


def _thin_structures(binary: np.ndarray, horizontal: bool) -> np.ndarray:
    """Ink pixels not part of any run thicker than RULE_MAX_THICKNESS_PX across the rule direction."""
    k = (1, RULE_MAX_THICKNESS_PX) if horizontal else (RULE_MAX_THICKNESS_PX, 1)
    thick = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, k))
    return cv2.bitwise_and(binary, cv2.bitwise_not(thick))


def _rule_mask(binary: np.ndarray, lenient: np.ndarray, horizontal: bool) -> np.ndarray:
    """Band of thin pixels (of ``binary``) lying along page-spanning rules found in ``lenient``."""
    H, W = binary.shape
    span = W if horizontal else H
    thin = _thin_structures(lenient, horizontal)
    seed_len = max(20, int(span * RULE_SEED_RUN_FRAC))
    seed_k = (seed_len, 1) if horizontal else (1, seed_len)
    seeds = cv2.morphologyEx(thin, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, seed_k))
    bridge = max(5, int(span * RULE_BRIDGE_FRAC))
    bridge_k = (bridge, 3) if horizontal else (3, bridge)
    bridged = cv2.dilate(seeds, cv2.getStructuringElement(cv2.MORPH_RECT, bridge_k))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bridged, connectivity=8)
    mask = np.zeros_like(binary)
    for i in range(1, n):
        extent = stats[i, cv2.CC_STAT_WIDTH] if horizontal else stats[i, cv2.CC_STAT_HEIGHT]
        if extent >= RULE_MIN_SPAN_FRAC * span:
            _paint_rule_band(mask, np.argwhere(labels == i), horizontal)
    # erase only thin pixels inside the rule band so crossing handwriting survives
    return cv2.bitwise_and(_thin_structures(binary, horizontal), mask)


def _paint_rule_band(mask: np.ndarray, pts: np.ndarray, horizontal: bool) -> None:
    """Fit a straight line through the rule pixels and paint a thin band along it across the whole page."""
    H, W = mask.shape
    along, across = (pts[:, 1], pts[:, 0]) if horizontal else (pts[:, 0], pts[:, 1])
    slope, intercept = np.polyfit(along.astype(np.float64), across.astype(np.float64), 1)
    spread = float(np.percentile(np.abs(across - (slope * along + intercept)), 95))
    half = int(min(RULE_MAX_THICKNESS_PX, max(1.0, spread))) + 1
    extent = W if horizontal else H
    xs = np.arange(extent)
    centre = np.round(slope * xs + intercept).astype(int)
    for off in range(-half, half + 1):
        rows = np.clip(centre + off, 0, (H if horizontal else W) - 1)
        if horizontal:
            mask[rows, xs] = 255
        else:
            mask[xs, rows] = 255


def remove_rules(binary: np.ndarray, lenient: np.ndarray | None = None) -> np.ndarray:
    """Erase notebook rules (horizontal) and margin / grid rules (vertical)."""
    lenient = binary if lenient is None else lenient
    rules = cv2.bitwise_or(_rule_mask(binary, lenient, horizontal=True), _rule_mask(binary, lenient, horizontal=False))
    return cv2.bitwise_and(binary, cv2.bitwise_not(rules))


def binarize_page(gray: np.ndarray) -> tuple[np.ndarray, int]:
    """Returns (clean ink mask, estimated line height in px)."""
    line_h = estimate_line_height(gray)
    binary, lenient = sauvola(gray, int(WINDOW_PER_LINE_HEIGHT * line_h))
    return remove_rules(binary, lenient), line_h
