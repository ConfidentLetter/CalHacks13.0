"""Quality gate: is this dewarped page good enough to transcribe? Honest flags, never a silent pass."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from capture.compat import cfg
from capture.detect import quad_angles_deg

BLOCKING_ISSUES = ("no_page", "partial_page", "blur", "hand_in_frame")
BLUR_MEASURE_LONG_SIDE = 1100
SKIN_CR_RANGE, SKIN_CB_RANGE, SKIN_Y_RANGE = (135, 175), (85, 130), (80, 235)
SKIN_MEASURE_LONG_SIDE = 480.0
SKIN_BLOB_KERNEL_FRACTION = 0.03     # of page width: strokes of red ink vanish, fingers survive
PAGE_ERODE_FRACTION = 0.012          # keep the desk just outside the page out of the skin count
DEFAULTS = {
    "page.blur_threshold": 80,
    "page.glare_fraction_max": 0.04,
    "page.glare_pixel_min": 250,
    "page.dark_median_max": 70,
    "page.skew_max_deg": 35,
    "page.hand_fraction_max": 0.03,
    "page.edge_margin_fraction": 0.01,
    "page.min_ink_fraction_for_blur": 0.002,
}


def _get(key: str):
    return cfg(key, DEFAULTS[key])


@dataclass
class Quality:
    ok: bool = True
    issues: list[str] = field(default_factory=list)
    blur_score: float = 0.0
    glare_fraction: float = 0.0
    extras: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"ok": bool(self.ok), "issues": list(self.issues),
                "blur_score": float(round(self.blur_score, 2)), "glare_fraction": float(round(self.glare_fraction, 4))}


def ink_mask(gray: np.ndarray) -> np.ndarray:
    """Binary ink (255) from a normalized gray page."""
    block = max(31, (min(gray.shape) // 20) | 1)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 12)


def blur_score(raw_gray: np.ndarray, norm_gray: np.ndarray) -> tuple[float, float]:
    """Variance of Laplacian on the lighting-normalized gray (so faint pencil and dark exposures score like
    dark ink), measured around ink only (a blank page is not 'blurry'), at a fixed 1100 px long side so the
    number is resolution-independent. Synthetic bench: sharp >= ~1800, Gaussian sigma 4-6 blur <= ~1200.
    Returns (score, ink_fraction)."""
    scale = BLUR_MEASURE_LONG_SIDE / max(norm_gray.shape)
    small_norm = cv2.resize(norm_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else norm_gray
    lap = cv2.Laplacian(small_norm, cv2.CV_64F, ksize=3)
    ink = ink_mask(small_norm)
    ink_fraction = float(cv2.countNonZero(ink)) / ink.size
    near_ink = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) > 0
    if near_ink.sum() < 500:
        return float(lap.var()), ink_fraction
    return float(lap[near_ink].var()), ink_fraction


GLARE_BACKGROUND_SIGMA_FRACTION = 1 / 6   # of the long side: wide enough that a lamp blob stays above it
GLARE_BACKGROUND_MARGIN = 10


def glare_fraction(raw_gray: np.ndarray) -> float:
    """Fraction of the page that is saturated AND clearly brighter than its wide surroundings.
    Plain white paper (a scan, a bright exposure) is uniform, so it is not glare; a lamp reflection is."""
    sat_level = int(_get("page.glare_pixel_min"))
    scale = 400.0 / max(raw_gray.shape)
    small = cv2.resize(raw_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else raw_gray
    saturated = small >= sat_level
    if not saturated.any():
        return 0.0
    sigma = max(4.0, GLARE_BACKGROUND_SIGMA_FRACTION * max(small.shape))
    background = cv2.GaussianBlur(small.astype(np.float32), (0, 0), sigma)
    return float((saturated & (background < sat_level - GLARE_BACKGROUND_MARGIN)).mean())


def skin_fraction_in_page(frame: np.ndarray, quad: np.ndarray | None) -> float:
    """Fraction of the page polygon (slightly dilated; whole frame if quad is None) covered by skin-toned pixels."""
    h, w = frame.shape[:2]
    scale = SKIN_MEASURE_LONG_SIDE / max(h, w)
    small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame
    page = np.zeros(small.shape[:2], np.uint8)
    if quad is None:
        page[:] = 255
        page_w = small.shape[1]
    else:
        q = quad * (small.shape[1] / w)
        cv2.fillConvexPoly(page, q.astype(np.int32), 255)
        page_w = float(max(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3])))
        erode = max(3, int(page_w * PAGE_ERODE_FRACTION)) | 1
        page = cv2.erode(page, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode, erode)))
    ycrcb = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
    skin = cv2.inRange(ycrcb, (SKIN_Y_RANGE[0], SKIN_CR_RANGE[0], SKIN_CB_RANGE[0]), (SKIN_Y_RANGE[1], SKIN_CR_RANGE[1], SKIN_CB_RANGE[1]))
    blob = max(5, int(page_w * SKIN_BLOB_KERNEL_FRACTION)) | 1
    skin = cv2.morphologyEx(skin, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (blob, blob)))
    area = max(1, cv2.countNonZero(page))
    return float(cv2.countNonZero(cv2.bitwise_and(skin, page))) / area


def touches_frame_edge(quad: np.ndarray, frame_wh: tuple[int, int]) -> bool:
    w, h = frame_wh
    m = float(_get("page.edge_margin_fraction"))
    x, y = quad[:, 0], quad[:, 1]
    return bool((x <= w * m).any() or (y <= h * m).any() or (x >= w * (1 - m)).any() or (y >= h * (1 - m)).any())


def assess(frame: np.ndarray, quad: np.ndarray | None, raw_gray: np.ndarray | None, norm_gray: np.ndarray | None,
           flat: bool = False) -> Quality:
    """Build the quality block. `quad` None means no page was found; the frame itself is then measured.
    flat=True: the page IS the frame (scan/upload), so touching the frame edge is not a partial page."""
    q = Quality()
    if quad is None:
        q.issues.append("no_page")
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        q.blur_score, _ = blur_score(gray, gray)
        q.glare_fraction = glare_fraction(gray)
        if float(np.percentile(gray, 99)) < float(_get("page.dark_median_max")):
            q.issues.append("too_dark")           # nothing bright anywhere, not even a page
        skin = skin_fraction_in_page(frame, None)
        q.extras = {"skin_fraction": round(skin, 4)}
        if skin > float(_get("page.hand_fraction_max")):
            q.issues.append("hand_in_frame")
        q.ok = False
        return q

    assert raw_gray is not None and norm_gray is not None
    q.blur_score, ink_fraction = blur_score(raw_gray, norm_gray)
    q.glare_fraction = glare_fraction(raw_gray)
    q.extras = {"ink_fraction": round(ink_fraction, 5), "median": float(np.median(raw_gray))}

    if not flat and touches_frame_edge(quad, (frame.shape[1], frame.shape[0])):
        q.issues.append("partial_page")
    if q.blur_score < float(_get("page.blur_threshold")) and ink_fraction >= float(_get("page.min_ink_fraction_for_blur")):
        q.issues.append("blur")
    if q.glare_fraction > float(_get("page.glare_fraction_max")):
        q.issues.append("glare")
    if q.extras["median"] < float(_get("page.dark_median_max")):
        q.issues.append("too_dark")
    skin = skin_fraction_in_page(frame, quad)
    q.extras["skin_fraction"] = round(skin, 4)
    if skin > float(_get("page.hand_fraction_max")):
        q.issues.append("hand_in_frame")
    if float(np.abs(quad_angles_deg(quad) - 90).max()) > float(_get("page.skew_max_deg")):
        q.issues.append("skew_extreme")
    q.ok = not any(issue in BLOCKING_ISSUES for issue in q.issues)
    return q
