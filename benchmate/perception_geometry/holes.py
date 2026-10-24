"""Hole-blob detection in the warped board image (used by calibration refinement and wire masking)."""
from __future__ import annotations

import cv2
import numpy as np

from . import board

# Hole is ~1.0 mm square on real boards. Bounds in mm, applied in warped px.
HOLE_MIN_MM, HOLE_MAX_MM = 0.55, 1.9
HOLE_MIN_FILL = 0.55          # contour area / bbox area; printed letters are thin -> low fill
ADAPTIVE_BLOCK_PITCHES = 2.0
ADAPTIVE_C = 22
HOLE_MAX_SAT = 90              # HSV saturation above this = coloured (wire / PCB), not a hole


def hole_mask(warped_bgr: np.ndarray) -> np.ndarray:
    """Binary mask (255 = dark small blob candidates) from an adaptive threshold."""
    gray = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    block = int(ADAPTIVE_BLOCK_PITCHES * board.pitch_px()) | 1
    dark = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, ADAPTIVE_C)
    # holes are dark AND grey; a coloured wire is darker than the board in grayscale but saturated
    sat = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2HSV)[..., 1]
    return cv2.bitwise_and(dark, (sat < HOLE_MAX_SAT).astype(np.uint8) * 255)


def detect_hole_blobs(warped_bgr: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Centroids (N,2) of small, roughly square, well-filled dark blobs in warped px."""
    s = board.BOARD_CONFIG["px_per_mm"]
    lo, hi = HOLE_MIN_MM * s, HOLE_MAX_MM * s
    m = hole_mask(warped_bgr) if mask is None else mask
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return np.zeros((0, 2), np.float64)
    w = stats[1:, cv2.CC_STAT_WIDTH].astype(np.float64)
    h = stats[1:, cv2.CC_STAT_HEIGHT].astype(np.float64)
    area = stats[1:, cv2.CC_STAT_AREA].astype(np.float64)
    fill = area / np.maximum(w * h, 1)
    aspect = np.minimum(w, h) / np.maximum(w, h)
    keep = (w >= lo) & (w <= hi) & (h >= lo) & (h <= hi) & (fill >= HOLE_MIN_FILL) & (aspect >= 0.5)
    return centroids[1:][keep].astype(np.float64)


def hole_blob_mask(warped_bgr: np.ndarray, dilate_mm: float = 0.1) -> np.ndarray:
    """Mask of the detected hole blobs' own pixels (slightly dilated) — wire detection ignores them.
    Deliberately tight: a fat mask would cut wires that run between holes into fragments."""
    s = board.BOARD_CONFIG["px_per_mm"]
    lo, hi = HOLE_MIN_MM * s, HOLE_MAX_MM * s
    m = hole_mask(warped_bgr)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = np.zeros(m.shape, np.uint8)
    if n <= 1:
        return out
    w = stats[1:, cv2.CC_STAT_WIDTH].astype(np.float64)
    h = stats[1:, cv2.CC_STAT_HEIGHT].astype(np.float64)
    area = stats[1:, cv2.CC_STAT_AREA].astype(np.float64)
    fill = area / np.maximum(w * h, 1)
    keep = (w >= lo) & (w <= hi) & (h >= lo) & (h <= hi) & (fill >= HOLE_MIN_FILL)
    keep_ids = np.where(keep)[0] + 1
    out[np.isin(labels, keep_ids)] = 255
    k = max(1, int(round(dilate_mm * s))) * 2 + 1
    return cv2.dilate(out, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
