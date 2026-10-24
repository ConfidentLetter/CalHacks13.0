"""Zhang-Suen thinning in NumPy (no opencv-contrib needed)."""
from __future__ import annotations

import numpy as np

MAX_ITERATIONS = 100


def _neighbours(img: np.ndarray) -> list[np.ndarray]:
    """P2..P9 clockwise from the top, as padded-shifted views."""
    p = np.pad(img, 1)
    return [
        p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:], p[2:, 2:],
        p[2:, 1:-1], p[2:, :-2], p[1:-1, :-2], p[:-2, :-2],
    ]


def _iteration(img: np.ndarray, first: bool) -> np.ndarray:
    n = _neighbours(img)
    p2, p3, p4, p5, p6, p7, p8, p9 = n
    b = sum(n)
    seq = n + [n[0]]
    a = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8) for i in range(8))
    if first:
        cond = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
    else:
        cond = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
    remove = (img == 1) & (b >= 2) & (b <= 6) & (a == 1) & cond
    return img & ~remove


def skeletonize(binary: np.ndarray) -> np.ndarray:
    """uint8 mask (ink = nonzero) -> uint8 1-px-wide skeleton (ink = 255)."""
    img = (binary > 0).astype(np.uint8)
    for _ in range(MAX_ITERATIONS):
        before = img.sum()
        img = _iteration(_iteration(img, True), False)
        if img.sum() == before:
            break
    return img * 255
