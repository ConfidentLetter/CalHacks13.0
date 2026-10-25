"""Loose page crop for hand-held sheets T1 cannot outline (a corner or edge out of frame, fingers on it).

Find the sheet as the largest bright, low-saturation blob (it may touch the frame edges; no four-corner
requirement), cut thin bridges to other bright things (ceiling lights, white walls) with a large opening,
crop its bounding rectangle plus a small margin, and paint everything outside the sheet white so the
normal layout (T2) and transcription (T3) never see faces or the room. No perspective correction: boxes
are real per-line boxes in this crop's pixels, and quality.ok stays False (confidence capped as usual).
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from transcribe.compat import REPO_ROOT, cfg

MIN_AREA_FRACTION = 0.10
MAX_AREA_FRACTION = 0.97
MIN_SOLIDITY = 0.75      # sheet ≈ convex; room clutter is not
MARGIN_FRACTION = 0.015  # of the crop's long side
BRIGHT_ABS = 150
BRIGHT_REL = 25
MAX_SAT = 60


def paper_mask(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2].astype(np.float32)
    bg = cv2.blur(v, ((max(31, img.shape[1] // 12)) | 1,) * 2)
    otsu, _ = cv2.threshold(hsv[..., 2], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)  # grey paper in dim light
    bright = (v > min(BRIGHT_ABS, max(otsu, 90))) | (v > bg + BRIGHT_REL)
    mask = (bright & (hsv[..., 1] < MAX_SAT)).astype(np.uint8) * 255
    k = max(5, img.shape[1] // 120) | 1
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k * 3, k * 3), np.uint8))  # ink strokes → paper


def sheet_shape(img: np.ndarray) -> np.ndarray | None:
    """Binary mask of the sheet only, or None when nothing sheet-like is in the frame."""
    mask = paper_mask(img)
    k = max(15, min(mask.shape) // 9) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    core = cv2.erode(mask, kernel)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(core)
    if n <= 1:
        return None
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    shape = cv2.bitwise_and(cv2.dilate((lab == biggest).astype(np.uint8) * 255, kernel), mask)
    contours, _ = cv2.findContours(shape, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    area, frame = cv2.contourArea(c), float(mask.size)
    hull = cv2.convexHull(c)
    if not (MIN_AREA_FRACTION * frame <= area <= MAX_AREA_FRACTION * frame) or area / max(cv2.contourArea(hull), 1.0) < MIN_SOLIDITY:
        return None
    out = np.zeros(mask.shape, np.uint8)
    cv2.drawContours(out, [hull], -1, 255, thickness=-1)
    return out


def loose_page(frame_path: str) -> dict | None:
    """{path, width, height, bbox_in_frame} of the whitened sheet crop, or None."""
    src = Path(frame_path)
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        return None
    shape = sheet_shape(img)
    if shape is None:
        return None
    x, y, w, h = cv2.boundingRect(shape)
    m = int(round(MARGIN_FRACTION * max(w, h)))
    x0, y0 = max(0, x - m), max(0, y - m)
    x1, y1 = min(img.shape[1], x + w + m), min(img.shape[0], y + h + m)
    grown = cv2.dilate(shape, np.ones((2 * m + 1, 2 * m + 1), np.uint8)) if m > 0 else shape
    sheet = img.copy()
    sheet[grown == 0] = 255
    sheet = sheet[y0:y1, x0:x1]
    target = float(cfg("page.output_long_side", 2200))
    f = target / max(sheet.shape[:2])
    sheet = cv2.resize(sheet, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)
    out_dir = REPO_ROOT / "runtime" / "dewarped"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}_loose.png"
    cv2.imwrite(str(out), sheet)
    try:
        rel = str(out.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        rel = str(out)
    return {"path": rel, "width": int(sheet.shape[1]), "height": int(sheet.shape[0]),
            "bbox_in_frame": [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]}
