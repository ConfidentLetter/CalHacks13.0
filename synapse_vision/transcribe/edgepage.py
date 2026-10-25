"""Sheet that fills the frame but touches its edge (phone held close, a corner cut off by the frame or desk).

T1's quad finder only trusts outlines that sit on Canny edges, and there is no edge where the sheet meets
the frame border, so it reports no_page. Here, when the bright sheet blob covers enough of the frame, we
ask T1's finder again with the edge check relaxed, keep that quad only if it agrees with the blob, and
flatten with T1's own dewarp. The result is a normal dewarped page: T2 and the per-line path run unchanged.
quality.ok stays False (the caller keeps T1's issues), so confidence is still capped.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from transcribe.compat import REPO_ROOT, cfg
from transcribe.loosepage import sheet_shape

MIN_SHEET_FRACTION = 0.40  # the sheet must fill this much of the frame
MIN_QUAD_IOU = 0.80        # T1's relaxed quad must agree with the sheet blob this well


def _quad_mask(quad: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    m = np.zeros(shape, np.uint8)
    cv2.fillConvexPoly(m, quad.astype(np.int32), 255)
    return m


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = cv2.countNonZero(cv2.bitwise_and(a, b))
    union = cv2.countNonZero(cv2.bitwise_or(a, b))
    return inter / union if union else 0.0


def _blob_quad(sheet: np.ndarray) -> np.ndarray | None:
    contours, _ = cv2.findContours(sheet, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    peri = cv2.arcLength(c, True)
    for eps in (0.02, 0.03, 0.05):
        approx = cv2.approxPolyDP(c, eps * peri, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype(np.float32)
    return None


def edge_page_quad(img: np.ndarray) -> np.ndarray | None:
    """Four corners of a frame-filling sheet, or None."""
    sheet = sheet_shape(img)
    if sheet is None or cv2.countNonZero(sheet) < float(cfg("transcribe.edge_page_min_fraction", MIN_SHEET_FRACTION)) * sheet.size:
        return None
    try:
        from capture.detect import find_page_quad

        quad = find_page_quad(img, require_edges=False).quad
    except Exception:  # noqa: BLE001 - T1 missing or raising: use the blob outline
        quad = None
    for cand in (quad, _blob_quad(sheet)):
        if cand is not None and _iou(_quad_mask(np.asarray(cand, np.float32), sheet.shape), sheet) >= MIN_QUAD_IOU:
            return np.asarray(cand, np.float32)
    return None


def edge_page(frame_path: str) -> dict | None:
    """{dewarped_path, width, height, quad} written next to T1's outputs, or None when this is not such a sheet."""
    src = Path(frame_path)
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        return None
    quad = edge_page_quad(img)
    if quad is None:
        return None
    try:
        from capture.dewarp import dewarp

        dw = dewarp(img, quad)
    except Exception:  # noqa: BLE001
        return None
    out_dir = REPO_ROOT / "runtime" / "dewarped"
    out_dir.mkdir(parents=True, exist_ok=True)
    color = out_dir / f"{src.stem}_edge.jpg"
    cv2.imwrite(str(color), dw.color, [cv2.IMWRITE_JPEG_QUALITY, 95])
    cv2.imwrite(str(out_dir / f"{src.stem}_edge_gray.png"), dw.gray)  # T2 prefers <stem>_gray.png for ink masks
    try:
        rel = str(color.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        rel = str(color)
    return {"dewarped_path": rel, "width": int(dw.color.shape[1]), "height": int(dw.color.shape[0]),
            "quad": dw.quad.tolist()}
