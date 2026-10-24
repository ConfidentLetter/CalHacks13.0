"""T1 — detect_and_dewarp + tile (contracts/interfaces.md). Never raises on a bad photo."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from capture.compat import absolute, log, repo_relative, runtime_dir, timed
from capture.detect import PageDetection, detect_page
from capture.dewarp import Dewarped, dewarp
from capture.quality import Quality, assess
from capture.tiling import tile  # noqa: F401  (re-exported: contracts list tile() under capture/page.py)

DEWARPED_DIR = "dewarped"
DEBUG_DIR = "debug"
IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def _result(dewarped_path: str, width: int, height: int, homography, quality: Quality, **extra) -> dict:
    return {"dewarped_path": dewarped_path, "width": int(width), "height": int(height),
            "homography": [[float(v) for v in row] for row in np.asarray(homography, dtype=float).tolist()],
            "quality": quality.as_dict(), **extra}


def _unreadable(snapshot_path: str) -> dict:
    quality = Quality(ok=False, issues=["no_page"])
    return _result(repo_relative(snapshot_path) if Path(snapshot_path).exists() else snapshot_path, 0, 0, IDENTITY, quality,
                   detection={"method": "none", "quad": None})


def _save_outputs(stem: str, dw: Dewarped) -> tuple[str, str]:
    out_dir = runtime_dir(DEWARPED_DIR)
    color_path = out_dir / f"{stem}_dewarped.jpg"
    gray_path = out_dir / f"{stem}_dewarped_gray.png"
    cv2.imwrite(str(color_path), dw.color, [cv2.IMWRITE_JPEG_QUALITY, 95])
    cv2.imwrite(str(gray_path), dw.gray)
    return repo_relative(color_path), repo_relative(gray_path)


def _debug_image(stem: str, frame: np.ndarray, det: PageDetection, dw: Dewarped | None, quality: Quality, ms: float) -> str | None:
    """runtime/debug/page_<stem>.png: detected corners | dewarped page | quality numbers."""
    try:
        panel_h = 700
        left = frame.copy()
        if det.mat_quad is not None:
            cv2.polylines(left, [det.mat_quad.astype(np.int32)], True, (255, 160, 0), max(2, frame.shape[1] // 400))
        if det.quad is not None:
            cv2.polylines(left, [det.quad.astype(np.int32)], True, (0, 255, 0), max(2, frame.shape[1] // 300))
            for i, (x, y) in enumerate(det.quad):
                cv2.circle(left, (int(x), int(y)), max(4, frame.shape[1] // 150), (0, 0, 255), -1)
                cv2.putText(left, "TL TR BR BL".split()[i], (int(x) + 8, int(y) - 8), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        left = cv2.resize(left, (int(left.shape[1] * panel_h / left.shape[0]), panel_h))
        if dw is not None:
            mid = cv2.resize(dw.color, (int(dw.color.shape[1] * panel_h / dw.color.shape[0]), panel_h))
        else:
            mid = np.zeros((panel_h, int(panel_h / 1.3), 3), np.uint8)
        right = np.full((panel_h, 420, 3), 30, np.uint8)
        lines = [f"method: {det.method}", f"ok: {quality.ok}", f"issues: {', '.join(quality.issues) or '-'}",
                 f"blur_score: {quality.blur_score:.1f}", f"glare_fraction: {quality.glare_fraction:.4f}",
                 *(f"{k}: {v}" for k, v in quality.extras.items()),
                 f"aspect: {dw.aspect:.3f}" if dw else "", f"out: {dw.color.shape[1]}x{dw.color.shape[0]}" if dw else "",
                 f"time: {ms:.0f} ms"]
        for i, text in enumerate(l for l in lines if l):
            color = (80, 80, 255) if text.startswith("issues") and quality.issues else (230, 230, 230)
            cv2.putText(right, text, (12, 36 + i * 34), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
        path = runtime_dir(DEBUG_DIR) / f"page_{stem}.png"
        cv2.imwrite(str(path), np.hstack([left, mid, right]))
        return repo_relative(path)
    except Exception:  # debug output must never break the pipeline
        return None


def detect_and_dewarp(snapshot_path: str) -> dict:
    """{dewarped_path, width, height, homography, quality:{ok, issues, blur_score, glare_fraction}}.
    Finds the paper (page quad or ArUco fallback), flattens to a fixed aspect, normalizes lighting.
    Never raises on a bad photo: returns quality.ok=False with issues."""
    t0 = time.perf_counter()
    with timed("capture.page") as info:
        try:
            frame = cv2.imread(str(absolute(snapshot_path)), cv2.IMREAD_COLOR)
        except cv2.error:
            frame = None
        if frame is None or frame.size == 0:
            info["ok"] = False
            return _unreadable(snapshot_path)
        stem = Path(snapshot_path).stem
        try:
            with timed("capture.detect"):
                det = detect_page(frame)
            if det.quad is None:
                quality = assess(frame, None, None, None)
                _debug_image(stem, frame, det, None, quality, (time.perf_counter() - t0) * 1000)
                info["ok"] = False
                return _result(repo_relative(snapshot_path), frame.shape[1], frame.shape[0], IDENTITY, quality,
                               detection={"method": det.method, "quad": None})
            flat = det.method == "flat"
            with timed("capture.dewarp"):
                dw = dewarp(frame, det.quad, flat=flat)
            with timed("capture.quality"):
                quality = assess(frame, dw.quad, dw.raw_gray, dw.gray, flat=flat)
            color_path, gray_path = _save_outputs(stem, dw)
        except Exception as exc:  # noqa: BLE001 - contract: never raise
            log("capture.page_error", (time.perf_counter() - t0) * 1000, error=f"{type(exc).__name__}: {exc}")
            quality = Quality(ok=False, issues=["no_page"])
            return _result(repo_relative(snapshot_path), frame.shape[1], frame.shape[0], IDENTITY, quality,
                           detection={"method": "error", "quad": None, "error": f"{type(exc).__name__}: {exc}"})
        debug_path = _debug_image(stem, frame, det, dw, quality, (time.perf_counter() - t0) * 1000)
        info.update(ok=quality.ok, issues=",".join(quality.issues), method=det.method)
        return _result(color_path, dw.color.shape[1], dw.color.shape[0], dw.homography, quality,
                       dewarped_gray_path=gray_path, debug_path=debug_path,
                       detection={"method": det.method, "quad": dw.quad.tolist(), "aspect": dw.aspect})
