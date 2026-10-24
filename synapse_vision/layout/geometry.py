"""Pure bbox helpers.  All boxes are ``[x, y, w, h]`` in dewarped-page pixels."""
from __future__ import annotations

from typing import Sequence

BBox = Sequence[float]


def to_int_bbox(b: BBox) -> list[int]:
    x, y, w, h = b
    return [int(round(x)), int(round(y)), int(round(w)), int(round(h))]


def pad_bbox(b: BBox, pad: int) -> list[int]:
    x, y, w, h = to_int_bbox(b)
    return [x - pad, y - pad, w + 2 * pad, h + 2 * pad]


def union_bbox(boxes: Sequence[BBox]) -> list[int]:
    xs0 = [b[0] for b in boxes]
    ys0 = [b[1] for b in boxes]
    xs1 = [b[0] + b[2] for b in boxes]
    ys1 = [b[1] + b[3] for b in boxes]
    x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
    return [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]


def iou(a: BBox, b: BBox) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax0 + aw, bx0 + bw), min(ay0 + ah, by0 + bh)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def y_overlap(a: BBox, b: BBox) -> float:
    """Vertical overlap in pixels (0 if disjoint)."""
    top = max(a[1], b[1])
    bot = min(a[1] + a[3], b[1] + b[3])
    return max(0.0, bot - top)


def x_overlap(a: BBox, b: BBox) -> float:
    left = max(a[0], b[0])
    right = min(a[0] + a[2], b[0] + b[2])
    return max(0.0, right - left)
