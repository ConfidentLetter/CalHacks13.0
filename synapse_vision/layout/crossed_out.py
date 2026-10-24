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
FAINT_MIN_SEPARATION = 50        # gray levels between ink and a lighter "rule" class
FAINT_RULE_MIN_RUN_FRAC = 0.3    # a faint horizontal run this long (of crop width) is a printed rule
MIN_INK_PIXELS = 30
TEXTURE_MIN_PIECES = 25          # ink made of at least this many pieces ...
TEXTURE_MAX_PIECE_AREA = 4.0     # ... whose median area is below this x stroke thickness^2 is halftone shading, not writing
MIDDLE_BAND = (0.25, 0.75)       # a strike's midpoint lies in this vertical band of the ink ...
ENDPOINT_BAND = (0.05, 0.95)     # ... and its ends stay inside this one (tilted strikes)
STRIKE_MIN_CONTINUITY = 0.9      # ink present along this fraction of the stroke (letter chains have gaps)
STRAIGHT_MAX_ANGLE_DEG = 18.0
MIN_SPAN_FRAC = 0.45             # below this a stroke is not even a weak candidate
FULL_SPAN_FRAC = 0.8             # at/above this span the span term saturates
HOUGH_MIN_LEN_FRAC = 0.25        # of ink width, per segment (segments are chained by collinearity)
HOUGH_GAP_FRAC = 0.06
COLLINEAR_TOL_PX = 6
CROSSING_PROBE_MARGIN_PX = 3     # skip the stroke's own anti-aliased edge ...
CROSSING_PROBE_PX = 4            # ... then look this far beyond it for other ink
FULL_CREDIT_CROSSINGS = 4
MIN_CROSSINGS_FOR_STRIKE = 2     # fewer -> looks like a fraction bar / underline, confidence capped
CAPPED_CONF = 0.35
SOLID_BAND_SPAN = 0.6            # a long stroke through ONE unbroken band of ink (a short bold word whose
SOLID_BAND_MAX_GAP_ROWS = 1      # letters touch) counts as crossed even with a single crossing run; a fraction
                                 # shows empty rows between numerator, bar and denominator
ZIGZAG_MIN_SEGMENTS = 6
ZIGZAG_ANGLE_DEG = (20.0, 75.0)
ZIGZAG_MIN_SPAN_FRAC = 0.6
ZIGZAG_MIN_LEN_FRAC = 0.25       # of ink height
ZIGZAG_HOUGH_THRESHOLD = 6
ZIGZAG_HOUGH_GAP = 4
ZIGZAG_MIN_COVERAGE = 0.85       # a zig-zag strike leaves almost no empty column in the middle band
ZIGZAG_MIN_ALTERNATIONS = 3
CONF_BASE, CONF_SPAN, CONF_CROSS = 0.3, 0.5, 0.2


def _load_ink(crop_path: str) -> np.ndarray | None:
    img = cv2.imread(str(crop_path), cv2.IMREAD_GRAYSCALE)
    if img is None or img.size == 0 or img.min() == img.max():
        return None
    _, ink = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return _drop_faint_rules(img, ink)


def _drop_faint_rules(gray: np.ndarray, ink: np.ndarray) -> np.ndarray:
    """Printed rules are much lighter than pen/pencil: split the dark pixels a second time and
    drop the lighter class where it forms long horizontal runs (a rule through the crop)."""
    dark = gray[ink > 0]
    if dark.size < MIN_INK_PIXELS:
        return ink
    t2, _ = cv2.threshold(dark.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    heavy, light = dark[dark < t2], dark[dark >= t2]
    if heavy.size == 0 or light.size == 0 or light.mean() - heavy.mean() < FAINT_MIN_SEPARATION:
        return ink
    faint = ((gray >= t2) & (ink > 0)).astype(np.uint8) * 255
    run = max(8, int(FAINT_RULE_MIN_RUN_FRAC * gray.shape[1]))
    rules = cv2.morphologyEx(faint, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (run, 1)))
    rules = cv2.dilate(rules, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    return cv2.bitwise_and(ink, cv2.bitwise_not(cv2.bitwise_and(rules, faint)))


def _ink_bbox(ink: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(ink > 0)
    if len(xs) < MIN_INK_PIXELS:
        return None
    x0, x1 = np.percentile(xs, INK_PERCENTILE)
    y0, y1 = np.percentile(ys, INK_PERCENTILE)
    return int(x0), int(y0), int(x1 - x0) + 1, int(y1 - y0) + 1


def _stroke_thickness(ink: np.ndarray, skel: np.ndarray) -> float:
    return float(np.count_nonzero(ink)) / max(1.0, float(np.count_nonzero(skel)))


def _hough(skel: np.ndarray, min_len: int, max_gap: int, threshold: int | None = None) -> list[tuple[int, int, int, int]]:
    threshold = max(10, min_len // 2) if threshold is None else threshold
    seg = cv2.HoughLinesP(skel, 1, np.pi / 180, threshold=threshold, minLineLength=min_len, maxLineGap=max_gap)
    return [tuple(int(v) for v in s) for s in np.asarray(seg).reshape(-1, 4)] if seg is not None else []


def _angle_deg(s: tuple[int, int, int, int]) -> float:
    return math.degrees(math.atan2(s[3] - s[1], s[2] - s[0]))


Segment = tuple[int, int, int, int]


def _chain_collinear(segments: list[Segment]) -> list[tuple[Segment, list[Segment]]]:
    """Merge near-horizontal segments lying on the same line: [(straight stroke, its ordered pieces)]."""
    strokes: list[list[Segment]] = []
    segments = [s if s[0] <= s[2] else (s[2], s[3], s[0], s[1]) for s in segments]  # left-to-right
    for s in sorted(segments):
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
        pieces = [s if s[0] <= s[2] else (s[2], s[3], s[0], s[1]) for s in group]
        pieces.sort()
        pts = [(s[0], s[1]) for s in pieces] + [(s[2], s[3]) for s in pieces]
        left, right = min(pts), max(pts)
        out.append(((left[0], left[1], right[0], right[1]), pieces))
    return out


def _ink_along(ink: np.ndarray, seg: Segment, reach: int) -> tuple[int, int]:
    """(points with ink within ``reach`` px perpendicular, points sampled) along a segment."""
    x0, y0, x1, y1 = seg
    length = max(1.0, math.hypot(x1 - x0, y1 - y0))
    nx, ny = -(y1 - y0) / length, (x1 - x0) / length
    H, W = ink.shape
    hits, n = 0, max(1, int(length))
    for t in np.linspace(0, 1, n):
        px, py = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
        for d in range(-reach, reach + 1):
            qx, qy = int(round(px + d * nx)), int(round(py + d * ny))
            if 0 <= qx < W and 0 <= qy < H and ink[qy, qx]:
                hits += 1
                break
    return hits, n


def _continuity(ink: np.ndarray, pieces: list[Segment], thickness: float) -> float:
    """Ink presence along the Hough pieces AND the connectors between them (letter chains have empty connectors)."""
    reach = int(math.ceil(thickness / 2)) + 2
    path = list(pieces)
    for a, b in zip(pieces, pieces[1:]):
        if b[0] > a[2]:
            path.append((a[2], a[3], b[0], b[1]))
    hits = n = 0
    for seg in path:
        h, k = _ink_along(ink, seg, reach)
        hits, n = hits + h, n + k
    return hits / max(1, n)


def _crossings(ink: np.ndarray, stroke: tuple[int, int, int, int], thickness: float) -> int:
    """How many times other ink touches the stroke on BOTH sides along its length."""
    x0, y0, x1, y1 = stroke
    length = max(1.0, math.hypot(x1 - x0, y1 - y0))
    nx, ny = -(y1 - y0) / length, (x1 - x0) / length  # unit normal
    d0 = int(math.ceil(thickness / 2)) + CROSSING_PROBE_MARGIN_PX
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
    elo, ehi = y + ENDPOINT_BAND[0] * h, y + ENDPOINT_BAND[1] * h
    for stroke, pieces in _chain_collinear(segments):
        sx0, sy0, sx1, sy1 = stroke
        span = (sx1 - sx0) / max(1, w)
        mid_ok = lo <= (sy0 + sy1) / 2 <= hi and elo <= sy0 <= ehi and elo <= sy1 <= ehi
        if span < MIN_SPAN_FRAC or not mid_ok:
            continue
        span_term = min(1.0, (span - MIN_SPAN_FRAC) / (FULL_SPAN_FRAC - MIN_SPAN_FRAC))
        crossings = _crossings(ink, stroke, thickness)
        if crossings == 1 and span >= SOLID_BAND_SPAN and _solid_band(ink, stroke, bbox):
            crossings = MIN_CROSSINGS_FOR_STRIKE
        conf = CONF_BASE + CONF_SPAN * span_term + CONF_CROSS * min(1.0, crossings / FULL_CREDIT_CROSSINGS)
        if crossings < MIN_CROSSINGS_FOR_STRIKE or _continuity(ink, pieces, thickness) < STRIKE_MIN_CONTINUITY:
            conf = min(conf, CAPPED_CONF)  # fraction bar, underline, or a chain of letter bars
        best = max(best, conf)
    return best


def _solid_band(ink: np.ndarray, stroke: tuple[int, int, int, int], bbox: tuple[int, int, int, int]) -> bool:
    """True when the rows of the ink bbox above the stroke's span form one unbroken band (letters), not
    numerator / bar / denominator separated by empty rows."""
    x, y, w, h = bbox
    rows = (ink[y:y + h, max(x, stroke[0]):min(x + w, stroke[2]) + 1] > 0).any(axis=1)
    idx = np.flatnonzero(rows)
    if len(idx) < 2:
        return False
    gaps = np.diff(idx) - 1
    return int(gaps.max()) <= SOLID_BAND_MAX_GAP_ROWS


def _band_coverage(ink: np.ndarray, bbox: tuple[int, int, int, int], x_range: tuple[int, int] | None = None) -> float:
    """Fraction of columns (across the ink width, or ``x_range``) that carry ink inside the middle band."""
    x, y, w, h = bbox
    lo, hi = int(y + MIDDLE_BAND[0] * h), int(y + MIDDLE_BAND[1] * h)
    x0, x1 = x_range if x_range else (x, x + w)
    band = ink[lo:hi, x0:x1]
    return float((band > 0).any(axis=0).mean()) if band.size else 0.0


def _zigzag_conf(ink: np.ndarray, skel: np.ndarray, bbox: tuple[int, int, int, int]) -> float:
    x, y, w, h = bbox
    lo, hi = y + MIDDLE_BAND[0] * h, y + MIDDLE_BAND[1] * h
    diag = []
    for s in _hough(skel, max(6, int(ZIGZAG_MIN_LEN_FRAC * h)), ZIGZAG_HOUGH_GAP, ZIGZAG_HOUGH_THRESHOLD):
        a = abs(_angle_deg(s))
        if ZIGZAG_ANGLE_DEG[0] <= a <= ZIGZAG_ANGLE_DEG[1] and lo <= (s[1] + s[3]) / 2 <= hi:
            diag.append(s)
    if len(diag) < ZIGZAG_MIN_SEGMENTS:
        return 0.0
    diag.sort(key=lambda s: (s[0] + s[2]) / 2)
    signs = [np.sign((s[3] - s[1]) * (s[2] - s[0])) for s in diag]
    alternations = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    zx0, zx1 = min(min(s[0], s[2]) for s in diag), max(max(s[0], s[2]) for s in diag)
    span = (zx1 - zx0) / max(1, w)
    if span < ZIGZAG_MIN_SPAN_FRAC or alternations < ZIGZAG_MIN_ALTERNATIONS:
        return 0.0
    if _band_coverage(ink, bbox, (zx0, zx1)) < ZIGZAG_MIN_COVERAGE:
        return 0.0  # letters with diagonals but gaps between them, not one continuous zig-zag
    return min(1.0, 0.5 + 0.3 * min(1.0, (span - ZIGZAG_MIN_SPAN_FRAC) / 0.3) + 0.2 * min(1.0, alternations / 10))


def _is_halftone(ink: np.ndarray, thickness: float) -> bool:
    """Shaded blocks of a printed figure: many tiny ink specks instead of a few letter-sized pieces."""
    n, _, stats, _ = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8), connectivity=8)
    if n - 1 < TEXTURE_MIN_PIECES:
        return False
    areas = stats[1:, cv2.CC_STAT_AREA]
    return float(np.median(areas)) <= TEXTURE_MAX_PIECE_AREA * max(1.0, thickness) ** 2


def crossed_out_confidence(ink: np.ndarray) -> float:
    bbox = _ink_bbox(ink)
    if bbox is None:
        return 0.0
    skel = skeletonize(ink)
    if _is_halftone(ink, _stroke_thickness(ink, skel)):
        return 0.0
    return max(_straight_strike_conf(ink, skel, bbox), _zigzag_conf(ink, skel, bbox))


def is_crossed_out(crop_path: str) -> tuple[bool, float]:
    """Classical check (strike-through stroke over the ink); returns (crossed, confidence)."""
    from layout._compat import config_get, timed

    with timed("layout.is_crossed_out") as info:
        ink = _load_ink(crop_path) if Path(crop_path).exists() else None
        conf = round(float(crossed_out_confidence(ink)), 3) if ink is not None else 0.0
        min_conf = float(config_get("layout.crossed_out_min_conf", 0.6))
        info["conf"] = conf
    return conf >= min_conf, conf
