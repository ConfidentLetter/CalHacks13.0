"""``is_crossed_out(crop_path)`` — classical strike-through detection.

Skeletonize the crop's ink, then look for
  (a) a long, nearly straight stroke (Hough on the skeleton) spanning most of the ink's
      width through its vertical middle and *crossing* other ink many times, or
  (b) a dense zig-zag: many alternating diagonal segments in that band;
  two parallel strokes (double strike) simply score as the better of the two.
Fraction bars (ink above and below but no crossings, partial span) and underlines
(below the ink, not through its middle) must not trigger.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from layout.skeleton import skeletonize

INK_PERCENTILE = (1.0, 99.0)     # robust ink bbox
MIN_INK_PIXELS = 30
MIDDLE_BAND = (0.2, 0.8)         # strike must pass through this vertical band of the ink
STRAIGHT_MAX_ANGLE_DEG = 18.0
MIN_SPAN_FRAC = 0.45             # below this a stroke is not even a weak candidate
FULL_SPAN_FRAC = 0.8             # at/above this span the span term saturates
HOUGH_MIN_LEN_FRAC = 0.25        # of ink width, per segment (segments are chained by collinearity)
HOUGH_GAP_FRAC = 0.06
COLLINEAR_TOL_PX = 6
CROSSING_PROBE_PX = 3            # look this far beyond the stroke's own thickness for other ink
FULL_CREDIT_CROSSINGS = 4
MIN_CROSSINGS_FOR_STRIKE = 2     # fewer -> looks like a fraction bar / underline, confidence capped
CAPPED_CONF = 0.35
ZIGZAG_MIN_SEGMENTS = 6
ZIGZAG_ANGLE_DEG = (20.0, 75.0)
ZIGZAG_MIN_SPAN_FRAC = 0.6
ZIGZAG_MIN_LEN_FRAC = 0.35       # of ink height
CONF_BASE, CONF_SPAN, CONF_CROSS = 0.3, 0.5, 0.2


def _load_ink(crop_path: str) -> np.ndarray | None:
    img = cv2.imread(str(crop_path), cv2.IMREAD_GRAYSCALE)
    if img is None or img.size == 0 or img.min() == img.max():
        return None
    _, ink = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return ink


def _ink_bbox(ink: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(ink > 0)
    if len(xs) < MIN_INK_PIXELS:
        return None
    x0, x1 = np.percentile(xs, INK_PERCENTILE)
    y0, y1 = np.percentile(ys, INK_PERCENTILE)
    return int(x0), int(y0), int(x1 - x0) + 1, int(y1 - y0) + 1


def _stroke_thickness(ink: np.ndarray, skel: np.ndarray) -> float:
    return float(np.count_nonzero(ink)) / max(1.0, float(np.count_nonzero(skel)))


def _hough(skel: np.ndarray, min_len: int, max_gap: int) -> list[tuple[int, int, int, int]]:
    seg = cv2.HoughLinesP(skel, 1, np.pi / 180, threshold=max(10, min_len // 2), minLineLength=min_len, maxLineGap=max_gap)
    return [tuple(int(v) for v in s) for s in np.asarray(seg).reshape(-1, 4)] if seg is not None else []


def _angle_deg(s: tuple[int, int, int, int]) -> float:
    return math.degrees(math.atan2(s[3] - s[1], s[2] - s[0]))


def _chain_collinear(segments: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Merge near-horizontal segments lying on the same line into one long stroke."""
    strokes: list[list[tuple[int, int, int, int]]] = []
    for s in sorted(segments, key=lambda s: min(s[0], s[2])):
        for group in strokes:
            ref = group[0]
            dy = (ref[3] - ref[1]) / max(1, ref[2] - ref[0])
            pred = ref[1] + dy * (s[0] - ref[0])
            if abs(pred - s[1]) <= COLLINEAR_TOL_PX and abs(_angle_deg(ref) - _angle_deg(s)) <= 6:
                group.append(s)
                break
        else:
            strokes.append([s])
    out = []
    for group in strokes:
        pts = [(s[0], s[1]) for s in group] + [(s[2], s[3]) for s in group]
        left, right = min(pts), max(pts)
        out.append((left[0], left[1], right[0], right[1]))
    return out


def _crossings(ink: np.ndarray, stroke: tuple[int, int, int, int], thickness: float) -> int:
    """How many times other ink touches the stroke on BOTH sides along its length."""
    x0, y0, x1, y1 = stroke
    length = max(1.0, math.hypot(x1 - x0, y1 - y0))
    nx, ny = -(y1 - y0) / length, (x1 - x0) / length  # unit normal
    d0 = int(round(thickness / 2)) + 1
    H, W = ink.shape
    both = []
    for t in np.linspace(0, 1, int(length)):
        px, py = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
        hit = [False, False]
        for side, sign in enumerate((1, -1)):
            for d in range(d0, d0 + CROSSING_PROBE_PX + 1):
                qx, qy = int(round(px + sign * d * nx)), int(round(py + sign * d * ny))
                if 0 <= qx < W and 0 <= qy < H and ink[qy, qx]:
                    hit[side] = True
                    break
        both.append(hit[0] and hit[1])
    arr = np.array(both, dtype=np.int8)
    return int(np.count_nonzero(np.diff(np.concatenate([[0], arr])) == 1))


def _straight_strike_conf(ink: np.ndarray, skel: np.ndarray, bbox: tuple[int, int, int, int]) -> float:
    x, y, w, h = bbox
    thickness = _stroke_thickness(ink, skel)
    segments = [s for s in _hough(skel, max(8, int(HOUGH_MIN_LEN_FRAC * w)), max(2, int(HOUGH_GAP_FRAC * w)))
                if abs(_angle_deg(s)) <= STRAIGHT_MAX_ANGLE_DEG]
    best = 0.0
    lo, hi = y + MIDDLE_BAND[0] * h, y + MIDDLE_BAND[1] * h
    for stroke in _chain_collinear(segments):
        sx0, sy0, sx1, sy1 = stroke
        span = (sx1 - sx0) / max(1, w)
        if span < MIN_SPAN_FRAC or not (lo <= sy0 <= hi and lo <= sy1 <= hi):
            continue
        span_term = min(1.0, (span - MIN_SPAN_FRAC) / (FULL_SPAN_FRAC - MIN_SPAN_FRAC))
        crossings = _crossings(ink, stroke, thickness)
        conf = CONF_BASE + CONF_SPAN * span_term + CONF_CROSS * min(1.0, crossings / FULL_CREDIT_CROSSINGS)
        if crossings < MIN_CROSSINGS_FOR_STRIKE:
            conf = min(conf, CAPPED_CONF)
        best = max(best, conf)
    return best


def _zigzag_conf(skel: np.ndarray, bbox: tuple[int, int, int, int]) -> float:
    x, y, w, h = bbox
    lo, hi = y + MIDDLE_BAND[0] * h, y + MIDDLE_BAND[1] * h
    diag = []
    for s in _hough(skel, max(6, int(ZIGZAG_MIN_LEN_FRAC * h)), 3):
        a = abs(_angle_deg(s))
        if ZIGZAG_ANGLE_DEG[0] <= a <= ZIGZAG_ANGLE_DEG[1] and lo <= (s[1] + s[3]) / 2 <= hi:
            diag.append(s)
    if len(diag) < ZIGZAG_MIN_SEGMENTS:
        return 0.0
    diag.sort(key=lambda s: (s[0] + s[2]) / 2)
    signs = [np.sign((s[3] - s[1]) * (s[2] - s[0])) for s in diag]
    alternations = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    span = (max(max(s[0], s[2]) for s in diag) - min(min(s[0], s[2]) for s in diag)) / max(1, w)
    if span < ZIGZAG_MIN_SPAN_FRAC or alternations < ZIGZAG_MIN_SEGMENTS - 2:
        return 0.0
    return min(1.0, 0.5 + 0.3 * min(1.0, (span - ZIGZAG_MIN_SPAN_FRAC) / 0.3) + 0.2 * min(1.0, alternations / 10))


def crossed_out_confidence(ink: np.ndarray) -> float:
    bbox = _ink_bbox(ink)
    if bbox is None:
        return 0.0
    skel = skeletonize(ink)
    return max(_straight_strike_conf(ink, skel, bbox), _zigzag_conf(skel, bbox))


def is_crossed_out(crop_path: str) -> tuple[bool, float]:
    """Classical check (strike-through stroke over the ink); returns (crossed, confidence)."""
    from layout._compat import config_get, timed

    with timed("layout.is_crossed_out") as info:
        ink = _load_ink(crop_path) if Path(crop_path).exists() else None
        conf = round(float(crossed_out_confidence(ink)), 3) if ink is not None else 0.0
        min_conf = float(config_get("layout.crossed_out_min_conf", 0.6))
        info["conf"] = conf
    return conf >= min_conf, conf
