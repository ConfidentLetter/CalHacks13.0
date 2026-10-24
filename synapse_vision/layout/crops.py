"""Line crops and parent-context crops (Wiwynn "parent-page retrieval" idea).

``crop_path``          = the line alone, padded, 2x upscaled when short.
``context_crop_path``  = same horizontal span plus N neighbouring lines above and
                         below, target line outlined so the reader knows which
                         line is being asked about.
Crops are written under ``runtime/crops/<snapshot>/``; out-of-bounds boxes are
padded with white instead of being clipped so every crop has the requested size.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from layout._compat import REPO_ROOT, config_get
from layout.geometry import BBox, pad_bbox, to_int_bbox, union_bbox

CROP_PAD_PX = 12
UPSCALE_BELOW_HEIGHT_PX = 60
UPSCALE_FACTOR = 2
WHITE = 255
CONTEXT_OUTLINE_BGR = (0, 140, 255)  # orange: visible on white paper and dark ink
CONTEXT_OUTLINE_THICKNESS = 2


def crops_dir(snapshot_id: str) -> Path:
    d = REPO_ROOT / "runtime" / "crops" / snapshot_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot_id_from_path(path: str) -> str:
    return Path(path).stem or "snapshot"


def extract_padded(img: np.ndarray, bbox: BBox) -> np.ndarray:
    """Crop ``bbox`` from ``img``; regions outside the image are filled white."""
    x, y, w, h = to_int_bbox(bbox)
    w, h = max(1, w), max(1, h)
    H, W = img.shape[:2]
    channels = () if img.ndim == 2 else (img.shape[2],)
    out = np.full((h, w, *channels), WHITE, dtype=img.dtype)
    sx0, sy0 = max(0, x), max(0, y)
    sx1, sy1 = min(W, x + w), min(H, y + h)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y : sy1 - y, sx0 - x : sx1 - x] = img[sy0:sy1, sx0:sx1]
    return out


def ink_density(gray_crop: np.ndarray) -> float:
    """Fraction of dark pixels in a grayscale crop (Otsu threshold)."""
    if gray_crop.size == 0:
        return 0.0
    if gray_crop.ndim == 3:
        gray_crop = cv2.cvtColor(gray_crop, cv2.COLOR_BGR2GRAY)
    if gray_crop.min() == gray_crop.max():
        return 0.0
    _, binary = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return float(np.count_nonzero(binary) / binary.size)


def write_line_crop(img: np.ndarray, bbox: BBox, out_path: Path) -> np.ndarray:
    crop = extract_padded(img, pad_bbox(bbox, CROP_PAD_PX))
    if crop.shape[0] < UPSCALE_BELOW_HEIGHT_PX:
        crop = cv2.resize(crop, None, fx=UPSCALE_FACTOR, fy=UPSCALE_FACTOR, interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(str(out_path), crop)
    return crop


def write_context_crop(img: np.ndarray, line_bboxes: Sequence[BBox], index: int, out_path: Path) -> np.ndarray:
    """Crop line ``index`` together with ``layout.context_lines`` neighbours, target outlined."""
    n_ctx = int(config_get("layout.context_lines", 1))
    lo, hi = max(0, index - n_ctx), min(len(line_bboxes), index + n_ctx + 1)
    neighbours = [line_bboxes[i] for i in range(lo, hi)]
    target = to_int_bbox(line_bboxes[index])
    span = union_bbox([target, [target[0], neighbours[0][1], target[2], 1], [target[0], neighbours[-1][1] + neighbours[-1][3] - 1, target[2], 1]])
    region = pad_bbox(span, CROP_PAD_PX)
    crop = extract_padded(img, region)
    if crop.ndim == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    tx, ty = target[0] - region[0], target[1] - region[1]
    cv2.rectangle(crop, (tx - 4, ty - 4), (tx + target[2] + 4, ty + target[3] + 4), CONTEXT_OUTLINE_BGR, CONTEXT_OUTLINE_THICKNESS)
    cv2.imwrite(str(out_path), crop)
    return crop


def write_all_crops(img: np.ndarray, line_bboxes: Sequence[BBox], snapshot_id: str) -> list[dict]:
    """Write line + context crops for every bbox; returns [{crop_path, context_crop_path, ink_density}]."""
    out_dir = crops_dir(snapshot_id)
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    results: list[dict] = []
    for i, bbox in enumerate(line_bboxes):
        crop_path = out_dir / f"line_{i:03d}.png"
        ctx_path = out_dir / f"line_{i:03d}_ctx.png"
        write_line_crop(img, bbox, crop_path)
        write_context_crop(img, line_bboxes, i, ctx_path)
        results.append(
            {
                "crop_path": str(crop_path.relative_to(REPO_ROOT)),
                "context_crop_path": str(ctx_path.relative_to(REPO_ROOT)),
                "ink_density": round(ink_density(extract_padded(gray, bbox)), 4),
            }
        )
    return results
