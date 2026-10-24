"""Board calibration: ArUco markers (or clicked corners) -> homography, refined on the hole grid.

The returned homography maps ORIGINAL image pixels -> warped board pixels (BOARD_CONFIG px/mm).
"""
from __future__ import annotations

import math
import time

import cv2
import numpy as np

from . import board
from .holes import detect_hole_blobs
from .telemetry import log
from .warp import as_matrix, to_original, to_warped, warp_image

MARKER_IDS = (0, 1, 2, 3)
CACHE_MOVE_PX = 3.0              # recompute when any marker moved more than this
_cache: list[tuple[np.ndarray, list[list[float]]]] = []     # (marker centres (4,2) in original px, H)
_corner_cache: dict[tuple, list[list[float]]] = {}


class CalibrationError(Exception):
    """Raised when neither ArUco markers nor clicked corners give a usable homography."""


# ----------------------------------------------------------------------------- markers

def _aruco_detector() -> "cv2.aruco.ArucoDetector":
    adict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(adict, params)


def detect_markers(img_bgr: np.ndarray) -> dict[int, tuple[float, float]]:
    """Marker id -> centre in original px, for ids 0-3 only."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = _aruco_detector().detectMarkers(gray)
    found: dict[int, tuple[float, float]] = {}
    if ids is None:
        return found
    for quad, mid in zip(corners, ids.ravel()):
        mid = int(mid)
        if mid in MARKER_IDS and mid not in found:
            c = quad.reshape(4, 2).mean(axis=0)
            found[mid] = (float(c[0]), float(c[1]))
    return found


def _homography_from_markers(centres: dict[int, tuple[float, float]]) -> np.ndarray:
    s = board.BOARD_CONFIG["px_per_mm"]
    src = np.array([centres[i] for i in MARKER_IDS], np.float64)
    dst = np.array([board.BOARD_CONFIG["markers"][i] for i in MARKER_IDS], np.float64) * s
    H, _ = cv2.findHomography(src, dst, 0)
    if H is None:
        raise CalibrationError("Marker positions are degenerate; re-tape the markers at the four corners.")
    return H / H[2, 2]


def _homography_from_corners(corners) -> np.ndarray:
    pts = np.asarray(corners, np.float64).reshape(-1, 2)
    if pts.shape != (4, 2):
        raise CalibrationError("Need exactly 4 clicked corners (TL, TR, BR, BL).")
    dst = np.array([board.hole_px(h) for h in board.BOARD_CONFIG["click_corner_holes"]], np.float64)
    H, _ = cv2.findHomography(pts, dst, 0)
    if H is None:
        raise CalibrationError("Clicked corners are degenerate; click the four corner holes again.")
    return H / H[2, 2]


# ----------------------------------------------------------------------------- grid refinement

def _cluster_1d(values: np.ndarray, tol: float) -> list[tuple[float, int]]:
    """Histogram-peak clustering of 1-D values (robust to small per-row spread). (centre, count) per cluster."""
    centres, counts, _ = _cluster_axis(values, tol)
    return list(zip(centres.tolist(), counts.tolist()))


def _cluster_axis(values: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cluster 1-D values around smoothed-histogram peaks at least ~1.7*tol apart.
    Returns (centres, counts, label per value; -1 = unassigned)."""
    n = values.size
    if n == 0:
        return np.zeros(0), np.zeros(0, int), np.zeros(0, int)
    lo, hi = float(values.min()) - 2 * tol, float(values.max()) + 2 * tol
    hist, edges = np.histogram(values, bins=np.arange(lo, hi + 1.0, 1.0))
    sigma = max(1.0, 0.25 * tol)
    k = np.exp(-0.5 * (np.arange(-3 * sigma, 3 * sigma + 1) / sigma) ** 2)
    sm = np.convolve(hist.astype(np.float64), k / k.sum(), mode="same")
    centres_px = (edges[:-1] + edges[1:]) / 2
    # local maxima
    peaks = np.where((sm[1:-1] > sm[:-2]) & (sm[1:-1] >= sm[2:]) & (sm[1:-1] > 0.3))[0] + 1
    # non-maximum suppression at ~1.7*tol separation, strongest first
    order = peaks[np.argsort(-sm[peaks])]
    kept: list[int] = []
    for pk in order:
        if all(abs(centres_px[pk] - centres_px[q]) >= 1.7 * tol for q in kept):
            kept.append(int(pk))
    if not kept:
        return np.zeros(0), np.zeros(0, int), np.full(n, -1)
    pk_pos = np.sort(centres_px[kept])
    d = np.abs(values[:, None] - pk_pos[None, :])
    label = d.argmin(axis=1)
    label[d.min(axis=1) > tol] = -1
    centres, counts = [], []
    for i in range(pk_pos.size):
        sel = values[label == i]
        centres.append(float(sel.mean()) if sel.size else float(pk_pos[i]))
        counts.append(int(sel.size))
    return np.array(centres), np.array(counts), label


def _detilt(pts: np.ndarray, pitch: float, axis: int, centre: tuple[float, float]) -> tuple[float, np.ndarray]:
    """Small rotation (radians) that makes rows (axis=1) or columns (axis=0) sharpest; returns the rotated coordinate.
    Marker misplacement leaves a residual perspective that tilts the hole lattice by a degree or two."""
    cx, cy = centre
    x, y = pts[:, 0] - cx, pts[:, 1] - cy
    bw = pitch / 8
    best_th, best_score, best_v = 0.0, -1.0, None
    for th in np.deg2rad(np.linspace(-4, 4, 41)):
        v = (y * math.cos(th) - x * math.sin(th) + cy) if axis == 1 else (x * math.cos(th) + y * math.sin(th) + cx)
        hist, _ = np.histogram(v, bins=np.arange(v.min(), v.max() + bw, bw))
        score = float((hist.astype(np.float64) ** 2).sum())
        if score > best_score:
            best_th, best_score, best_v = th, score, v
    return best_th, best_v


def _match_row_pattern(row_centres: list[float], pitch: float, tol: float) -> list[float] | None:
    """Find 10 consecutive row centres with spacing [1,1,1,1,gap,1,1,1,1] pitches."""
    gap = board.BOARD_CONFIG["channel_gap_pitches"]
    pattern = np.array([1, 1, 1, 1, gap, 1, 1, 1, 1], np.float64) * pitch
    best, best_err = None, float("inf")
    for i in range(len(row_centres) - 9):
        seq = np.array(row_centres[i:i + 10])
        err = np.abs(np.diff(seq) - pattern)
        if err.max() <= tol and err.mean() < best_err:
            best, best_err = list(seq), err.mean()
    return best


def _model_hole_px() -> tuple[np.ndarray, list[str]]:
    ids = list(board.iter_holes())
    return np.array([board.hole_px(h) for h in ids], np.float64), ids


def _median_error(points_w: np.ndarray, model: np.ndarray) -> float:
    from scipy.spatial import cKDTree
    if points_w.shape[0] == 0:
        return float("inf")
    d, _ = cKDTree(model).query(points_w, k=1)
    return float(np.median(d))


def _walk_columns(col_x: np.ndarray, pitch: float, start: int) -> list[tuple[int, int]]:
    """Walk right from cluster `start`, stepping ~1 observed pitch, skipping columns hidden by components.
    Returns (relative column index, cluster index) pairs."""
    chain = [(0, start)]
    step, i, rel = pitch, start, 0
    while True:
        found = None
        for k in range(1, 26):
            target = col_x[i] + k * step
            if target > col_x[-1] + 0.3 * pitch:
                break
            tol_k = (0.25 + 0.02 * k) * pitch
            cand = np.where(np.abs(col_x - target) <= tol_k)[0]
            cand = cand[cand > i]
            if cand.size:
                j = int(cand[np.abs(col_x[cand] - target).argmin()])
                found = (k, j)
                break
        if found is None:
            break
        k, j = found
        if k == 1:
            step = 0.7 * step + 0.3 * (col_x[j] - col_x[i])
        rel += k
        chain.append((rel, j))
        i = j
    return chain


def _number_columns(col_x: np.ndarray, col_n: np.ndarray, pitch: float) -> dict[int, int] | None:
    """cluster index -> absolute column number (1..63), using a gap-tolerant chain walk, trimming
    printed-label columns (few blobs) at the ends, and the model prior for the absolute offset."""
    cfg = board.BOARD_CONFIG
    n_cols = cfg["n_cols"]
    ox = cfg["origin_mm"][0] * cfg["px_per_mm"]
    region = np.where((col_x >= ox - 3 * pitch) & (col_x <= ox + (n_cols + 2) * pitch))[0]
    if region.size < 10:
        return None
    best_chain: list[tuple[int, int]] = []
    for start in region[:4]:                         # try the few leftmost starts, keep the longest chain
        chain = _walk_columns(col_x, pitch, int(start))
        if len(chain) > len(best_chain):
            best_chain = chain
    if len(best_chain) < 10:
        return None
    # trim: more than 63 columns means printed letters got through -> drop the end with fewer blobs
    while best_chain[-1][0] - best_chain[0][0] >= n_cols:
        if col_n[best_chain[0][1]] <= col_n[best_chain[-1][1]]:
            best_chain = best_chain[1:]
        else:
            best_chain = best_chain[:-1]
    base = best_chain[0][0]
    span = best_chain[-1][0] - base
    x_start = col_x[best_chain[0][1]]
    # absolute offset: first chain column = c0; pick c0 whose model position is nearest the observed start
    best_c0, best_cost = None, float("inf")
    for c0 in range(1, n_cols - span + 1):
        cost = abs(x_start - (ox + (c0 - 1) * pitch)) / pitch
        if c0 == 1 and col_n[best_chain[0][1]] >= 6:
            cost -= 0.5                                # a full column at the left end is probably column 1
        if c0 + span == n_cols and col_n[best_chain[-1][1]] >= 6:
            cost -= 0.5
        if cost < best_cost:
            best_c0, best_cost = c0, cost
    if best_c0 is None or best_cost > 3.0:
        return None
    return {j: best_c0 + (rel - base) for rel, j in best_chain}


def _correspondences_by_pattern(blobs: np.ndarray, pitch: float) -> tuple[np.ndarray, np.ndarray] | None:
    """Assign blobs to model holes via row-pattern + column-chain matching. Returns (blob_px, model_px)."""
    cfg = board.BOARD_CONFIG
    tol = 0.35 * pitch
    W, Hh = board.warped_size_px()
    centre = (W / 2, Hh / 2)
    _, yv = _detilt(blobs, pitch, axis=1, centre=centre)
    row_c, row_n, _ = _cluster_axis(yv, tol)
    rows = [float(c) for c, n in zip(row_c, row_n) if n >= 15]
    matched = _match_row_pattern(rows, pitch, tol)
    if matched is None:
        return None
    letters = cfg["letters_top_to_bottom"]
    row_y = np.array(matched)
    d_row = np.abs(yv[:, None] - row_y[None, :])
    row_idx = d_row.argmin(axis=1)
    in_rows = d_row.min(axis=1) <= tol
    pts, row_idx = blobs[in_rows], row_idx[in_rows]
    if pts.shape[0] < 30:
        return None
    _, xv = _detilt(pts, pitch, axis=0, centre=centre)
    col_c, col_n, col_label = _cluster_axis(xv, tol)
    keep = col_n >= 3
    if keep.sum() < 10:
        return None
    col_x, col_n = col_c[keep], col_n[keep].astype(np.float64)
    remap = {old: new for new, old in enumerate(np.where(keep)[0])}
    numbering = _number_columns(col_x, col_n, pitch)
    if numbering is None:
        return None
    ok = np.array([lab in remap and remap[lab] in numbering for lab in col_label])
    pts, row_idx, col_label = pts[ok], row_idx[ok], col_label[ok]
    model = np.array([board.hole_px(f"{letters[r]}{numbering[remap[lab]]}") for r, lab in zip(row_idx, col_label)],
                     np.float64)
    return pts, model


def _correspondences_by_nearest(blobs: np.ndarray, model: np.ndarray, pitch: float) -> tuple[np.ndarray, np.ndarray]:
    from scipy.spatial import cKDTree
    d, idx = cKDTree(model).query(blobs, k=1)
    keep = d <= 0.45 * pitch
    return blobs[keep], model[idx[keep]]


def _fit_correction(src: np.ndarray, dst: np.ndarray, pitch: float) -> np.ndarray | None:
    """Homography warped(observed) -> warped(model) from matched points; None if too few / unstable."""
    if src.shape[0] < 12:
        return None
    Hc, inl = cv2.findHomography(src, dst, cv2.RANSAC, 0.3 * pitch)
    if Hc is None or inl is None or inl.sum() < 12:
        return None
    Hc = Hc / Hc[2, 2]
    # sanity: the correction must be small over the hole area (corner holes move < 4 pitches)
    corners = np.array([board.hole_px(h) for h in board.BOARD_CONFIG["click_corner_holes"]], np.float64)
    moved = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), Hc).reshape(-1, 2)
    if np.linalg.norm(moved - corners, axis=1).max() > 4 * pitch:
        return None
    return Hc


def refine_on_grid(img_bgr: np.ndarray, H: np.ndarray) -> tuple[np.ndarray, dict]:
    """Refine H so detected hole blobs land on model holes. Accepts only if the median error drops."""
    pitch = board.pitch_px()
    model, _ = _model_hole_px()
    warped = warp_image(img_bgr, H)
    blobs = detect_hole_blobs(warped)
    stats = {"blobs": int(blobs.shape[0]), "err_before_px": _median_error(blobs, model), "method": "none"}
    if blobs.shape[0] < 40:
        stats["err_after_px"] = stats["err_before_px"]
        return H, stats

    H_cur, err_cur, method = H, stats["err_before_px"], "none"
    pts_cur = blobs
    corr = _correspondences_by_pattern(blobs, pitch)
    if corr is not None:
        Hc = _fit_correction(corr[0], corr[1], pitch)
        if Hc is not None:
            cand = cv2.perspectiveTransform(blobs.reshape(-1, 1, 2), Hc).reshape(-1, 2)
            err = _median_error(cand, model)
            if err < err_cur:
                H_cur, err_cur, pts_cur, method = Hc @ H, err, cand, "pattern"
    # polish with nearest-neighbour iterations. As a fallback (pattern failed) only when the initial
    # error is already well under half a pitch, otherwise ICP would confidently lock onto the wrong column.
    if method == "none" and err_cur > 0.3 * pitch:
        stats.update(err_after_px=err_cur, method="none")
        return H, stats
    for _ in range(3):
        src, dst = _correspondences_by_nearest(pts_cur, model, pitch)
        Hc = _fit_correction(src, dst, pitch)
        if Hc is None:
            break
        cand = cv2.perspectiveTransform(pts_cur.reshape(-1, 1, 2), Hc).reshape(-1, 2)
        err = _median_error(cand, model)
        if err >= err_cur - 0.02:
            break
        H_cur, err_cur, pts_cur = Hc @ H_cur, err, cand
        method = method if method == "pattern" else "icp"
    stats.update(err_after_px=err_cur, method=method)
    return H_cur / H_cur[2, 2], stats


# ----------------------------------------------------------------------------- public API

def _cached_for_markers(centres: dict[int, tuple[float, float]]) -> list[list[float]] | None:
    pts = np.array([centres[i] for i in MARKER_IDS])
    for cached_pts, H in _cache:
        if np.linalg.norm(cached_pts - pts, axis=1).max() <= CACHE_MOVE_PX:
            return H
    return None


def _remember(centres: dict[int, tuple[float, float]], H: list[list[float]]) -> None:
    pts = np.array([centres[i] for i in MARKER_IDS])
    _cache.append((pts, H))
    del _cache[:-8]


def clear_cache() -> None:
    _cache.clear()
    _corner_cache.clear()


def calibrate(frame_path: str, corners: list[tuple[float, float]] | None = None) -> list[list[float]]:
    """3x3 homography: original image pixels -> warped board image. corners = 4 clicked points
    (TL, TR, BR, BL); if None, detect ArUco markers ids 0-3. Raises CalibrationError if neither works."""
    t0 = time.perf_counter()
    img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if img is None:
        raise CalibrationError(f"Cannot read frame {frame_path}")

    found = detect_markers(img)
    source = "markers"
    if len(found) == 4:
        cached = _cached_for_markers(found)
        if cached is not None:
            log("calibrate", (time.perf_counter() - t0) * 1000, source="cache")
            return cached
        H0 = _homography_from_markers(found)
    elif corners is not None:
        key = tuple(tuple(float(v) for v in c) for c in corners)
        if key in _corner_cache:
            log("calibrate", (time.perf_counter() - t0) * 1000, source="cache")
            return _corner_cache[key]
        H0 = _homography_from_corners(corners)
        source = "corners"
    else:
        missing = sorted(set(MARKER_IDS) - set(found))
        raise CalibrationError(
            f"Only {len(found)} of 4 markers visible (missing ids {missing}). "
            "Move the camera so all four corner markers are in view, or click the four corner holes.")

    H, stats = refine_on_grid(img, H0)
    if not np.all(np.isfinite(H)):
        raise CalibrationError("Calibration produced a non-finite homography; check marker placement.")
    out = [[float(v) for v in row] for row in H]
    if source == "markers":
        _remember(found, out)
    else:
        _corner_cache[key] = out
    log("calibrate", (time.perf_counter() - t0) * 1000, source=source, **stats)
    return out


def pixel_to_hole(x: float, y: float, homography) -> str | None:
    """Original-image pixel -> hole id like 'J15', or rail id 'RAIL_TOP_PLUS' etc. None if off-board."""
    cfg = board.BOARD_CONFIG
    wx, wy = to_warped([(x, y)], homography)[0]
    if not (math.isfinite(wx) and math.isfinite(wy)):
        return None
    mx, my = wx / cfg["px_per_mm"], wy / cfg["px_per_mm"]
    hole, dist = board.nearest_hole_mm(mx, my)
    if dist <= cfg["snap_tolerance_pitches"] * cfg["pitch_mm"]:
        return hole
    return board.rail_at_mm(mx, my)


def hole_to_pixel(hole: str, homography) -> tuple[float, float]:
    """Inverse of pixel_to_hole: centre of a hole in original-image pixels (T2 uses it to lay out pins)."""
    px = to_original([board.hole_px(hole)], homography)[0]
    return float(px[0]), float(px[1])


def snap_distance_px(x: float, y: float, homography) -> tuple[str | None, float]:
    """Hole (or rail) at an original pixel plus the snap distance in warped px (rails: 0)."""
    cfg = board.BOARD_CONFIG
    wx, wy = to_warped([(x, y)], homography)[0]
    mx, my = wx / cfg["px_per_mm"], wy / cfg["px_per_mm"]
    hole, dist_mm = board.nearest_hole_mm(mx, my)
    if dist_mm <= cfg["snap_tolerance_pitches"] * cfg["pitch_mm"]:
        return hole, dist_mm * cfg["px_per_mm"]
    rail = board.rail_at_mm(mx, my)
    return rail, 0.0 if rail else dist_mm * cfg["px_per_mm"]


def make_identity() -> list[list[float]]:
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


_ = as_matrix  # re-exported for convenience
