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
RULE_SEED_MIN_SPAN_FRAC = 0.2  # a seed piece must be at least this long to be fitted as a rule
RULE_MIN_COVERAGE = 0.5        # ink found along the fitted line over this fraction of the page ...
RULE_DASH_BRIDGE_FRAC = 1 / 40  # dashed/broken rules (JPEG, dewarp) are bridged by this much before measuring
RULE_EDGE_ZONE_FRAC = 0.12     # ... and over RULE_MIN_EDGE_COVERAGE of both outer zones (rules run edge to edge)
RULE_MIN_EDGE_COVERAGE = 0.3
RULE_MAX_THICKNESS_PX = 6      # thicker horizontal structures are handwriting (strikes, bars)
RULE_RECONNECT_PX = 7           # close gaps up to this many px across an erased rule (sliced glyph strokes)
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
    bridged_thin = _bridge_dashes(thin, horizontal)
    for i in range(1, n):
        extent = stats[i, cv2.CC_STAT_WIDTH] if horizontal else stats[i, cv2.CC_STAT_HEIGHT]
        if extent < RULE_SEED_MIN_SPAN_FRAC * span:
            continue
        band = _fit_band(np.argwhere(labels == i), mask.shape, horizontal)
        if band is not None and not _already_painted(mask, band, horizontal) and _is_page_rule(bridged_thin, band, horizontal):
            _paint(mask, band, horizontal)
    # erase only thin pixels inside the rule band so crossing handwriting survives
    return cv2.bitwise_and(_thin_structures(binary, horizontal), mask), mask


def _reconnect_across(cleaned: np.ndarray, band: np.ndarray, horizontal: bool) -> np.ndarray:
    """Strokes sliced by an erased rule leave a 1-3 px gap; close such gaps across the band only
    (a closing along the rule direction would bring the rule back)."""
    k = (1, RULE_RECONNECT_PX) if horizontal else (RULE_RECONNECT_PX, 1)
    closed = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, k))
    near_band = cv2.dilate(band, cv2.getStructuringElement(cv2.MORPH_RECT, k))
    return cv2.bitwise_or(cleaned, cv2.bitwise_and(closed, near_band))


def _fit_band(pts: np.ndarray, shape: tuple[int, int], horizontal: bool) -> tuple[np.ndarray, int] | None:
    """Least-squares line through a rule piece -> (centre position per column/row, half thickness)."""
    H, W = shape
    along, across = (pts[:, 1], pts[:, 0]) if horizontal else (pts[:, 0], pts[:, 1])
    if len(np.unique(along)) < 2:
        return None
    slope, intercept = np.polyfit(along.astype(np.float64), across.astype(np.float64), 1)
    spread = float(np.percentile(np.abs(across - (slope * along + intercept)), 95))
    half = int(min(RULE_MAX_THICKNESS_PX, max(1.0, spread))) + 1
    xs = np.arange(W if horizontal else H)
    centre = np.clip(np.round(slope * xs + intercept).astype(int), 0, (H if horizontal else W) - 1)
    return centre, half


def _coverage(thin: np.ndarray, band: tuple[np.ndarray, int], horizontal: bool, sl: slice) -> float:
    centre, half = band
    xs = np.arange(len(centre))[sl]
    hit = np.zeros(len(xs), dtype=bool)
    limit = (thin.shape[0] if horizontal else thin.shape[1]) - 1
    for off in range(-half, half + 1):
        rows = np.clip(centre[sl] + off, 0, limit)
        hit |= (thin[rows, xs] if horizontal else thin[xs, rows]) > 0
    return float(hit.mean()) if len(hit) else 0.0


def _bridge_dashes(thin: np.ndarray, horizontal: bool) -> np.ndarray:
    span = thin.shape[1] if horizontal else thin.shape[0]
    b = max(5, int(span * RULE_DASH_BRIDGE_FRAC))
    k = (b, 1) if horizontal else (1, b)
    return cv2.dilate(thin, cv2.getStructuringElement(cv2.MORPH_RECT, k))


def _is_page_rule(thin: np.ndarray, band: tuple[np.ndarray, int], horizontal: bool) -> bool:
    """A printed rule has ink along most of the fitted line AND reaches both page edges; a strike does not."""
    n = len(band[0])
    edge = max(1, int(RULE_EDGE_ZONE_FRAC * n))
    return (_coverage(thin, band, horizontal, slice(0, n)) >= RULE_MIN_COVERAGE
            and _coverage(thin, band, horizontal, slice(0, edge)) >= RULE_MIN_EDGE_COVERAGE
            and _coverage(thin, band, horizontal, slice(n - edge, n)) >= RULE_MIN_EDGE_COVERAGE)


def _already_painted(mask: np.ndarray, band: tuple[np.ndarray, int], horizontal: bool) -> bool:
    return _coverage(mask, band, horizontal, slice(0, len(band[0]))) > 0.9


def _paint(mask: np.ndarray, band: tuple[np.ndarray, int], horizontal: bool) -> None:
    centre, half = band
    xs = np.arange(len(centre))
    limit = (mask.shape[0] if horizontal else mask.shape[1]) - 1
    for off in range(-half, half + 1):
        rows = np.clip(centre + off, 0, limit)
        if horizontal:
            mask[rows, xs] = 255
        else:
            mask[xs, rows] = 255


def remove_rules(binary: np.ndarray, lenient: np.ndarray | None = None) -> np.ndarray:
    """Erase notebook rules (horizontal) and margin / grid rules (vertical)."""
    lenient = binary if lenient is None else lenient
    h_rules, h_band = _rule_mask(binary, lenient, horizontal=True)
    v_rules, v_band = _rule_mask(binary, lenient, horizontal=False)
    cleaned = cv2.bitwise_and(binary, cv2.bitwise_not(cv2.bitwise_or(h_rules, v_rules)))
    cleaned = _reconnect_across(cleaned, h_band, horizontal=True)
    return _reconnect_across(cleaned, v_band, horizontal=False)


def binarize_page(gray: np.ndarray) -> tuple[np.ndarray, int]:
    """Returns (clean ink mask, estimated line height in px)."""
    line_h = estimate_line_height(gray)
    binary, lenient = sauvola(gray, int(WINDOW_PER_LINE_HEIGHT * line_h))
    return remove_rules(binary, lenient), line_h
