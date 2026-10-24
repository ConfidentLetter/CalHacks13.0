"""Pure box arithmetic: tile -> original mapping and non-maximum suppression."""
from __future__ import annotations

from .owl import Detection


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax0 + aw, bx0 + bw), min(ay0 + ah, by0 + bh)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def to_original(det: Detection, tile: dict) -> Detection:
    """Map a detection in tile pixels back to original-frame pixels.
    T1's tile dict: {path, bbox:[x,y,w,h] (original px), scale (upscale factor of the saved tile)}."""
    scale = float(tile.get("scale") or 1.0)
    tx, ty = float(tile["bbox"][0]), float(tile["bbox"][1])
    x, y, w, h = det.bbox
    return Detection((tx + x / scale, ty + y / scale, w / scale, h / scale), det.score, det.label)


def nms(dets: list[Detection], iou_threshold: float) -> list[Detection]:
    """Greedy NMS across all labels (one physical part may fire several queries)."""
    kept: list[Detection] = []
    for d in sorted(dets, key=lambda d: d.score, reverse=True):
        if all(iou(d.bbox, k.bbox) < iou_threshold for k in kept):
            kept.append(d)
    return kept
