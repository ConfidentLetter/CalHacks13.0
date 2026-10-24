"""Pixel-level helpers: ink density (empty-crop guard), crop hashing (incremental cache), zoom."""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

from transcribe.compat import REPO_ROOT, cfg

HASH_SIZE = (96, 24)  # (w, h) the crop is shrunk to before binarizing: lighting-insensitive
DEFAULT_EMPTY_INK_DENSITY = 0.004
ZOOM_MAX_LONG_SIDE = 1600


def resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def read_gray(path: str | Path) -> np.ndarray | None:
    p = resolve(path)
    if not p.exists():
        return None
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)


def ink_density(path: str | Path) -> float:
    """Fraction of dark pixels (Otsu). 0.0 for missing/blank crops."""
    gray = read_gray(path)
    if gray is None or gray.size == 0 or int(gray.min()) == int(gray.max()):
        return 0.0
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    density = float(np.count_nonzero(binary) / binary.size)
    # Otsu on near-blank paper splits noise into two halves; a real stroke is darker than the paper mean.
    if gray.std() < 6.0:
        return 0.0
    return density


def is_empty(density: float) -> bool:
    return density < float(cfg("transcribe.empty_ink_density", DEFAULT_EMPTY_INK_DENSITY))


def crop_hash(path: str | Path) -> str:
    """Stable hash of the ink pattern: resize to HASH_SIZE, blur, Otsu-binarize, sha1 of the bits."""
    gray = read_gray(path)
    if gray is None or gray.size == 0:
        return "empty"
    small = cv2.resize(gray, HASH_SIZE, interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (3, 3), 0)
    if int(small.min()) == int(small.max()) or small.std() < 6.0:
        return "blank"
    _, binary = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return hashlib.sha1(np.packbits(binary > 0).tobytes()).hexdigest()[:20]


def zoomed_copy(path: str | Path, factor: float = 3.0) -> Path:
    """Write <crop>_zoom.png at `factor`× (capped so the long side stays ≤ ZOOM_MAX_LONG_SIDE)."""
    src = resolve(path)
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        return src
    h, w = img.shape[:2]
    f = min(factor, ZOOM_MAX_LONG_SIDE / max(h, w, 1))
    f = max(f, 1.0)
    out_dir = REPO_ROOT / "runtime" / "debug" / "zoom"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}_{hashlib.sha1(str(src).encode()).hexdigest()[:8]}.png"
    cv2.imwrite(str(out), cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC))
    return out
