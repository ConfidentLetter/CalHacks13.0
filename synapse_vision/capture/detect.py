"""Find the page quad in a camera frame: contour search (edges + thresholds) with an ArUco-mat fallback."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from capture.compat import cfg

DETECT_LONG_SIDE = 1000
ARUCO_DICT = cv2.aruco.DICT_4X4_50
ARUCO_IDS_TL_TR_BR_BL = (0, 1, 2, 3)
MIN_RECTANGULARITY = 0.80
MAX_PAGE_AREA_FRACTION = 0.92        # a quad covering the whole frame is the frame, not a page
MIN_INSIDE_OUTSIDE_CONTRAST = 8.0    # paper must be brighter than the ring just outside it (stretched gray levels)
APPROX_EPS_STEPS = (0.02, 0.03, 0.045, 0.06, 0.08)
FLAT_BORDER_FRACTION = 0.02          # outer ring inspected for "no desk visible"
FLAT_BRIGHT_LEVEL = 150              # gray above this counts as paper
FLAT_BRIGHT_FRACTION_MIN = 0.80      # of the whole frame
FLAT_BORDER_BRIGHT_FRACTION_MIN = 0.90
FLAT_PAPER_SATURATION_MAX = 40       # mean HSV saturation of the bright pixels


@dataclass
class PageDetection:
    quad: np.ndarray | None          # (4, 2) float32, frame pixels, TL TR BR BL — None if no page found
    method: str                      # 'edges' | 'threshold' | 'aruco' | 'none'
    score: float = 0.0
    mat_quad: np.ndarray | None = None  # ArUco mat corners when the fallback was used


# ----------------------------------------------------------------------------- geometry helpers

def order_corners(pts: np.ndarray) -> np.ndarray:
    """Return the 4 points as TL, TR, BR, BL (image coordinates, y down)."""
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)


def quad_angles_deg(quad: np.ndarray) -> np.ndarray:
    """Interior angle at each corner, degrees."""
    q = np.asarray(quad, np.float32).reshape(4, 2)
    out = []
    for i in range(4):
        a, b, c = q[i - 1], q[i], q[(i + 1) % 4]
        v1, v2 = a - b, c - b
        cosang = float(np.dot(v1, v2) / max(1e-6, np.linalg.norm(v1) * np.linalg.norm(v2)))
        out.append(float(np.degrees(np.arccos(np.clip(cosang, -1.0, 1.0)))))
    return np.array(out)


def rectangularity(quad: np.ndarray) -> float:
    """1.0 for a perfect rectangle: contour area over its minimum-area bounding rectangle, times an angle term."""
    q = np.asarray(quad, np.float32).reshape(4, 2)
    area = abs(cv2.contourArea(q))
    (_, (rw, rh), _) = cv2.minAreaRect(q)
    fill = area / max(1e-6, rw * rh)
    angle_term = 1.0 - float(np.abs(quad_angles_deg(q) - 90).mean()) / 90.0
    return float(fill * angle_term)


# ----------------------------------------------------------------------------- quad candidates

def _quads_from_mask(mask: np.ndarray, min_area: float) -> list[np.ndarray]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    quads: list[np.ndarray] = []
    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue
        hull = cv2.convexHull(c)
        peri = cv2.arcLength(hull, True)
        for eps in APPROX_EPS_STEPS:
            approx = cv2.approxPolyDP(hull, eps * peri, True)
            if len(approx) == 4:
                quads.append(approx.reshape(4, 2).astype(np.float32))
                break
    return quads


def _edge_mask(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 120)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    return cv2.dilate(closed, kernel, iterations=1)


def _threshold_masks(gray: np.ndarray) -> list[np.ndarray]:
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    block = max(51, (min(gray.shape) // 4) | 1)
    adaptive = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, -5)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    return [cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel, iterations=2) for m in (otsu, adaptive)]


def _inside_outside_contrast(gray: np.ndarray, quad: np.ndarray) -> float:
    """Mean gray just inside the quad minus mean gray in a ring just outside it."""
    h, w = gray.shape
    ring = max(4, int(0.015 * max(h, w)))
    inner, outer = np.zeros((h, w), np.uint8), np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(inner, quad.astype(np.int32), 255)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * ring + 1, 2 * ring + 1))
    outer = cv2.subtract(cv2.dilate(inner, kernel), inner)
    inner_band = cv2.subtract(inner, cv2.erode(inner, kernel))
    if cv2.countNonZero(outer) < 50 or cv2.countNonZero(inner_band) < 50:
        return 0.0
    return float(cv2.mean(gray, inner_band)[0] - cv2.mean(gray, outer)[0])


def _best_quad(candidates: list[tuple[np.ndarray, str]], gray: np.ndarray, require_contrast: bool = True) -> PageDetection:
    frame_area = float(gray.shape[0] * gray.shape[1])
    best = PageDetection(None, "none")
    for quad, method in candidates:
        rect = rectangularity(quad)
        if rect < MIN_RECTANGULARITY:
            continue
        area_frac = abs(cv2.contourArea(quad)) / frame_area
        if area_frac > MAX_PAGE_AREA_FRACTION:
            continue
        if require_contrast and _inside_outside_contrast(gray, quad) < MIN_INSIDE_OUTSIDE_CONTRAST:
            continue
        score = rect * (0.6 + 0.4 * min(1.0, area_frac / 0.5))
        if score > best.score:
            best = PageDetection(order_corners(quad), method, score)
    return best


def _edge_fill_fraction(edge_mask: np.ndarray, quad: np.ndarray) -> float:
    """How much of the quad's boundary coincides with detected edges (0..1)."""
    boundary = np.zeros_like(edge_mask)
    cv2.polylines(boundary, [quad.astype(np.int32)], True, 255, 3)
    hits = cv2.countNonZero(cv2.bitwise_and(boundary, edge_mask))
    return hits / max(1, cv2.countNonZero(boundary))


def _stretched_gray(bgr: np.ndarray) -> np.ndarray:
    """Gray with a 1st-99th percentile contrast stretch so dark or washed-out exposures still show edges."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    lo, hi = np.percentile(gray, (1, 99))
    if hi - lo < 10:
        return gray
    return np.clip((gray.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)


def find_page_quad(img: np.ndarray, min_area_fraction: float | None = None, require_edges: bool = True) -> PageDetection:
    """Largest, most rectangular 4-point convex contour from edge and threshold maps. Coordinates in `img` pixels.
    require_edges=False trusts threshold quads even where Canny found no edge (used inside a known ArUco mat)."""
    h, w = img.shape[:2]
    scale = DETECT_LONG_SIDE / max(h, w)
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else img
    scale = small.shape[1] / w
    gray = _stretched_gray(small)
    min_area = float(small.shape[0] * small.shape[1]) * float(cfg("page.min_page_area_fraction", 0.25) if min_area_fraction is None else min_area_fraction)

    edge_mask = _edge_mask(gray)
    candidates = [(q, "edges") for q in _quads_from_mask(edge_mask, min_area)]
    for mask in _threshold_masks(gray):
        candidates += [(q, "threshold") for q in _quads_from_mask(mask, min_area)]
    # Threshold quads are only trusted when their outline mostly sits on real edges (rejects "whole bright desk").
    if require_edges:
        candidates = [(q, m) for q, m in candidates if m == "edges" or _edge_fill_fraction(edge_mask, q) > 0.5]
    det = _best_quad(candidates, gray, require_contrast=require_edges)
    if det.quad is not None:
        det.quad = refine_corners(img, det.quad / scale)
    return det


# ----------------------------------------------------------------------------- sub-pixel refinement

def _line_from_band(edges: np.ndarray, p: np.ndarray, q: np.ndarray, band: int) -> tuple[np.ndarray, np.ndarray] | None:
    """Fit a line to edge pixels within `band` px of segment p-q. Returns (point, direction) or None."""
    h, w = edges.shape
    x0, y0 = np.clip(np.floor(np.minimum(p, q) - band), 0, [w - 1, h - 1]).astype(int)
    x1, y1 = np.clip(np.ceil(np.maximum(p, q) + band), 0, [w - 1, h - 1]).astype(int)
    roi = edges[y0:y1 + 1, x0:x1 + 1]
    ys, xs = np.nonzero(roi)
    if len(xs) < 20:
        return None
    pts = np.stack([xs + x0, ys + y0], axis=1).astype(np.float32)
    d = q - p
    n = np.array([-d[1], d[0]]) / max(1e-6, np.linalg.norm(d))
    dist = np.abs((pts - p) @ n)
    along = ((pts - p) @ d) / max(1e-6, np.dot(d, d))
    keep = (dist <= band) & (along > 0.05) & (along < 0.95)
    if keep.sum() < 20:
        return None
    vx, vy, cx, cy = cv2.fitLine(pts[keep], cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    return np.array([cx, cy], np.float32), np.array([vx, vy], np.float32)


def _intersect(l1: tuple[np.ndarray, np.ndarray], l2: tuple[np.ndarray, np.ndarray]) -> np.ndarray | None:
    p1, d1 = l1
    p2, d2 = l2
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 1e-6:
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cross
    return p1 + t * d1


def refine_corners(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Snap each page edge to a line fitted through full-resolution Canny pixels; intersect for sub-pixel corners."""
    quad = order_corners(quad)
    gray = _stretched_gray(img)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    diag = float(np.linalg.norm(quad[0] - quad[2]))
    band = int(max(6, min(30, diag * 0.012)))
    lines = [_line_from_band(edges, quad[i], quad[(i + 1) % 4], band) for i in range(4)]
    refined = quad.copy()
    for i in range(4):
        before, after = lines[i - 1], lines[i]
        if before is None or after is None:
            continue
        pt = _intersect(before, after)
        if pt is not None and np.linalg.norm(pt - quad[i]) < band * 2.5:
            refined[i] = pt
    return refined


# ----------------------------------------------------------------------------- ArUco fallback

def find_aruco_mat(img: np.ndarray) -> np.ndarray | None:
    """Inner corners of markers 0..3 (TL, TR, BR, BL of the mat). None unless all four are visible."""
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICT), cv2.aruco.DetectorParameters())
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return None
    found = {int(i): c.reshape(4, 2) for i, c in zip(ids.ravel(), corners)}
    if not all(i in found for i in ARUCO_IDS_TL_TR_BR_BL):
        return None
    # Marker corners come as TL,TR,BR,BL in the marker's own orientation; take the one pointing INWARD
    # (diagonally opposite the outer corner) so the markers themselves stay outside the dewarped page.
    mat = np.array([found[0][2], found[1][3], found[2][0], found[3][1]], np.float32)
    return order_corners(mat)


def looks_like_flat_page(img: np.ndarray) -> bool:
    """True for an already-flat page that fills the frame (a scan, an upload, a page larger than the view):
    bright low-saturation paper nearly everywhere, including the outer border, so no desk is visible."""
    h, w = img.shape[:2]
    scale = 400.0 / max(h, w)
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else img
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    bright = gray >= FLAT_BRIGHT_LEVEL
    if bright.mean() < FLAT_BRIGHT_FRACTION_MIN:
        return False
    b = max(2, int(FLAT_BORDER_FRACTION * max(small.shape[:2])))
    ring = np.ones(gray.shape, bool)
    ring[b:-b, b:-b] = False
    if bright[ring].mean() < FLAT_BORDER_BRIGHT_FRACTION_MIN:
        return False
    saturation = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[:, :, 1]
    return float(saturation[bright].mean()) <= FLAT_PAPER_SATURATION_MAX


def frame_quad(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)


def detect_page(img: np.ndarray) -> PageDetection:
    """Page quad by contours (a page brighter than its surroundings); else a flat full-frame page
    (scan/upload: bright paper to every border) is the frame itself; else, if page.use_aruco_fallback,
    dewarp the ArUco mat and search inside it."""
    det = find_page_quad(img)
    if det.quad is not None:
        return det
    if looks_like_flat_page(img):
        return PageDetection(frame_quad(img), "flat", 1.0)
    if not cfg("page.use_aruco_fallback", True):
        return det
    mat = find_aruco_mat(img)
    if mat is None:
        return PageDetection(None, "none")
    mw = int(max(np.linalg.norm(mat[1] - mat[0]), np.linalg.norm(mat[2] - mat[3])))
    mh = int(max(np.linalg.norm(mat[3] - mat[0]), np.linalg.norm(mat[2] - mat[1])))
    dst = np.array([[0, 0], [mw - 1, 0], [mw - 1, mh - 1], [0, mh - 1]], np.float32)
    h_mat = cv2.getPerspectiveTransform(mat, dst)
    flat = cv2.warpPerspective(img, h_mat, (mw, mh))
    inner = find_page_quad(flat, min_area_fraction=0.15, require_edges=False)
    if inner.quad is None:
        return PageDetection(mat, "aruco", 0.5, mat_quad=mat)
    back = cv2.perspectiveTransform(inner.quad.reshape(1, 4, 2), np.linalg.inv(h_mat)).reshape(4, 2)
    return PageDetection(order_corners(back), "aruco", inner.score, mat_quad=mat)
