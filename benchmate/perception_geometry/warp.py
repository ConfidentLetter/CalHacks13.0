"""Point / image transforms between the original camera frame and the warped board frame."""
from __future__ import annotations

import cv2
import numpy as np

from . import board


def as_matrix(homography) -> np.ndarray:
    H = np.asarray(homography, dtype=np.float64)
    if H.shape != (3, 3):
        raise ValueError(f"homography must be 3x3, got {H.shape}")
    return H


def to_warped(points, homography) -> np.ndarray:
    """Original pixels (N,2) -> warped board pixels (N,2)."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, as_matrix(homography)).reshape(-1, 2)


def to_original(points, homography) -> np.ndarray:
    """Warped board pixels (N,2) -> original pixels (N,2)."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, np.linalg.inv(as_matrix(homography))).reshape(-1, 2)


def warp_image(img: np.ndarray, homography, border=(0, 0, 0)) -> np.ndarray:
    """Original frame -> warped top-down board image at BOARD_CONFIG px/mm."""
    w, h = board.warped_size_px()
    return cv2.warpPerspective(img, as_matrix(homography), (w, h), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def read_frame(frame_path: str) -> np.ndarray:
    img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"cannot read frame: {frame_path}")
    return img
