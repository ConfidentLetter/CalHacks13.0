"""Step 1 stub — one tile covering the whole frame. Density-balanced strips land in Step 4."""
from __future__ import annotations

from .telemetry import timed


@timed("tile")
def tile(frame_path: str, homography, max_tiles: int = 6) -> list[dict]:
    import cv2
    img = cv2.imread(frame_path)
    if img is None:
        raise FileNotFoundError(frame_path)
    h, w = img.shape[:2]
    return [{"path": frame_path, "bbox": [0.0, 0.0, float(w), float(h)], "scale": 1.0}]
