"""Homography to a flat portrait page + lighting normalization."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from capture.compat import cfg
from capture.detect import order_corners, quad_angles_deg

LETTER_ASPECT = 11.0 / 8.5
A4_ASPECT = 297.0 / 210.0
ASPECT_SNAP_TOLERANCE = 0.03
ASPECT_CLAMP = (1.15, 1.60)
CLAHE_CLIP, CLAHE_GRID = 2.0, (8, 8)
PAPER_TARGET_LEVEL = 235.0   # flattened paper is pushed to this gray level (ink contrast for T2/T3)


@dataclass
class Dewarped:
    color: np.ndarray        # lighting-normalized BGR page
    gray: np.ndarray         # lighting-normalized grayscale page (CLAHE)
    raw_gray: np.ndarray     # warped gray before normalization (for blur/glare measurement)
    homography: np.ndarray   # 3x3 frame -> dewarped
    quad: np.ndarray         # ordered source corners used, TL TR BR BL
    aspect: float


# ----------------------------------------------------------------------------- aspect ratio

def _edge_lengths(quad: np.ndarray) -> tuple[float, float]:
    tl, tr, br, bl = quad
    width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2.0
    height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2.0
    return float(width), float(height)


def aspect_from_homography(quad: np.ndarray, frame_wh: tuple[int, int]) -> float | None:
    """Zhang's whiteboard-scanning estimate of the true height/width ratio of a rectangle seen in perspective."""
    w, h = frame_wh
    focal = float(cfg("page.focal_px_factor", 0.9)) * max(w, h)
    u0, v0 = w / 2.0, h / 2.0
    m = [np.array([x - u0, y - v0, focal], np.float64) for x, y in quad]  # TL, TR, BR, BL
    m1, m2, m3, m4 = m[0], m[1], m[3], m[2]                                 # Zhang's ordering: m1 TL, m2 TR, m3 BL, m4 BR
    k2 = np.dot(np.cross(m1, m4), m3) / max(1e-9, np.dot(np.cross(m2, m4), m3))
    k3 = np.dot(np.cross(m1, m4), m2) / max(1e-9, np.dot(np.cross(m3, m4), m2))
    n2, n3 = k2 * m2 - m1, k3 * m3 - m1
    if np.linalg.norm(n2) < 1e-6 or np.linalg.norm(n3) < 1e-6:
        return None
    ratio_sq = np.dot(n3, n3) / max(1e-9, np.dot(n2, n2))   # (height/width)^2 via the pinhole inverse
    if not np.isfinite(ratio_sq) or ratio_sq <= 0:
        return None
    return float(np.sqrt(ratio_sq))


def choose_aspect(quad: np.ndarray, frame_wh: tuple[int, int]) -> float:
    """Portrait aspect (long/short): homography estimate, else edge-length ratio; snap to Letter/A4 if within 3 %."""
    width, height = _edge_lengths(quad)
    est = aspect_from_homography(quad, frame_wh)
    if np.abs(quad_angles_deg(quad) - 90).max() < 0.5:     # axis-aligned rectangle: edge ratio is exact
        est = height / max(1e-6, width)
    if est is None or not (ASPECT_CLAMP[0] * 0.8 < est < ASPECT_CLAMP[1] * 1.25 or ASPECT_CLAMP[0] * 0.8 < 1 / est < ASPECT_CLAMP[1] * 1.25):
        est = height / max(1e-6, width)
    est = est if est >= 1.0 else 1.0 / est
    for known in (LETTER_ASPECT, A4_ASPECT):
        if abs(est - known) / known <= ASPECT_SNAP_TOLERANCE:
            return known
    return float(np.clip(est, *ASPECT_CLAMP))


# ----------------------------------------------------------------------------- orientation

def to_portrait(quad: np.ndarray) -> np.ndarray:
    """If the page lies landscape in the frame, rotate the correspondence so the output is portrait.
    page.landscape_top = left|right says which frame edge is the top of the page (default left)."""
    quad = order_corners(quad)
    width, height = _edge_lengths(quad)
    if width <= height * 1.05:
        return quad
    tl, tr, br, bl = quad
    if str(cfg("page.landscape_top", "left")).lower() == "right":
        return np.array([tr, br, bl, tl], np.float32)
    return np.array([bl, tl, tr, br], np.float32)


# ----------------------------------------------------------------------------- lighting

def normalize_lighting(color: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Divide by a heavily blurred background (flattens shading), then CLAHE on gray. Returns (color, gray)."""
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    quarter = cv2.resize(gray, (max(8, gray.shape[1] // 4), max(8, gray.shape[0] // 4)), interpolation=cv2.INTER_AREA)
    sigma = max(4.0, max(quarter.shape) / 40.0)
    background = cv2.GaussianBlur(cv2.medianBlur(quarter, 11), (0, 0), sigma)
    background = cv2.resize(background, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    background = np.maximum(background, 1.0)
    gain = np.clip(PAPER_TARGET_LEVEL / background, 0.5, 4.0)
    flat_color = np.clip(color.astype(np.float32) * gain[:, :, None], 0, 255).astype(np.uint8)
    flat_gray = np.clip(gray.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=CLAHE_GRID)
    return flat_color, clahe.apply(flat_gray)


# ----------------------------------------------------------------------------- warp

def output_size(aspect: float) -> tuple[int, int]:
    long_side = int(cfg("page.output_long_side", 2200))
    return int(round(long_side / aspect)), long_side


def dewarp(img: np.ndarray, quad: np.ndarray, flat: bool = False) -> Dewarped:
    """flat=True: the quad is the whole frame (scan/upload) — keep its orientation and aspect, just rescale."""
    if flat:
        quad = order_corners(quad)
        width, height = _edge_lengths(quad)
        aspect = choose_aspect(quad, (img.shape[1], img.shape[0])) if height >= width else 1.0 / choose_aspect(quad, (img.shape[1], img.shape[0]))
        long_side = int(cfg("page.output_long_side", 2200))
        out_w, out_h = (int(round(long_side / aspect)), long_side) if aspect >= 1 else (long_side, int(round(long_side * aspect)))
    else:
        quad = to_portrait(quad)
        aspect = choose_aspect(quad, (img.shape[1], img.shape[0]))
        out_w, out_h = output_size(aspect)
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], np.float32)
    homography = cv2.getPerspectiveTransform(quad.astype(np.float32), dst)
    warped = cv2.warpPerspective(img, homography, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    raw_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    color, gray = normalize_lighting(warped)
    return Dewarped(color, gray, raw_gray, homography, quad, aspect)
