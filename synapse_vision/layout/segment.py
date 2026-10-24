"""``segment(dewarped_path)`` — the T2 entry point (see contracts/interfaces.md).

Returns ``{regions: [...], lines: [...]}`` in reading order.  Each line carries
``bbox, crop_path, context_crop_path, status_hint, ink_density`` (plus
``region_id`` and ``order`` for convenience).  Method chosen by
``layout.method`` in config: ``classical`` (default) or ``mock``.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from layout._compat import config_get, timed
from layout.crops import snapshot_id_from_path, write_all_crops
from layout.mock_layout import MOCK_PAGE_SIZE, mock_line_specs, mock_regions

VALID_STATUS_HINTS = ("active", "crossed_out", "unsure")


def load_page(dewarped_path: str) -> np.ndarray:
    """Read the dewarped page as BGR; an unreadable path yields a blank mock-sized page."""
    img = cv2.imread(str(dewarped_path), cv2.IMREAD_COLOR) if Path(dewarped_path).exists() else None
    if img is None:
        w, h = MOCK_PAGE_SIZE
        return np.full((h, w, 3), 255, dtype=np.uint8)
    return img


def _assemble(img: np.ndarray, snapshot_id: str, regions: list[dict], specs: list[dict]) -> dict:
    """Attach crops and ordering to line specs ``[{bbox, region_id, status_hint}]``."""
    crops = write_all_crops(img, [s["bbox"] for s in specs], snapshot_id)
    lines = [
        {
            "order": i,
            "region_id": spec["region_id"],
            "bbox": [float(v) for v in spec["bbox"]],
            "status_hint": spec["status_hint"] if spec["status_hint"] in VALID_STATUS_HINTS else "unsure",
            **crop,
        }
        for i, (spec, crop) in enumerate(zip(specs, crops))
    ]
    return {"regions": regions, "lines": lines}


def segment_mock(dewarped_path: str) -> dict:
    img = load_page(dewarped_path)
    return _assemble(img, snapshot_id_from_path(dewarped_path), mock_regions(), mock_line_specs())


RAW_PHOTO_SIZE_FACTOR = 1.25  # an image this much larger than T1's output long side is an undewarped camera frame
OUTPUT_SIDE_TOLERANCE = 0.03  # T1 output (dewarped or flat upload) has long side == page.output_long_side within this


def is_raw_photo(dewarped_path: str) -> bool:
    """T1 passes the untouched camera frame through when it finds no page (quality.ok=False, 'no_page').
    Its real outputs are portrait with long side ``page.output_long_side`` (flat uploads keep their
    orientation but are rescaled to that long side).  A far larger image, or a landscape one of any
    other size (a 1920x1080 webcam frame), is such a frame; segmenting it only produces illegible
    scraps for T3 to spend model calls on."""
    img = cv2.imread(str(dewarped_path), cv2.IMREAD_REDUCED_GRAYSCALE_8) if Path(dewarped_path).exists() else None
    if img is None:
        return False
    h, w = (8 * v for v in img.shape[:2])
    target = float(config_get("page.output_long_side", 2200))
    long_side = max(h, w)
    if long_side > RAW_PHOTO_SIZE_FACTOR * target:
        return True
    return w > h and abs(long_side - target) > OUTPUT_SIDE_TOLERANCE * target


def _segment_guarded(dewarped_path: str, info: dict) -> dict:
    """Run the classical segmenter; never raise (the demo must not go dark on one bad frame)."""
    try:
        if info.get("method") == "mock":
            return segment_mock(dewarped_path)
        if is_raw_photo(dewarped_path):
            info["skipped"] = "raw_photo"
            return {"regions": [], "lines": []}
        from layout.classical import segment_classical

        return segment_classical(dewarped_path)
    except Exception as exc:  # noqa: BLE001 - recorded in telemetry, empty layout returned
        info["error"] = f"{type(exc).__name__}: {exc}"
        return {"regions": [], "lines": []}


def segment(dewarped_path: str) -> dict:
    """{regions:[{id,type,bbox}], lines:[{bbox, crop_path, context_crop_path, status_hint, ink_density}]}
    in reading order. status_hint in {'active','crossed_out','unsure'}. crop_path = the line alone (2x upscale if small);
    context_crop_path = the line plus the line above and below (for parent-context reading)."""
    method = str(config_get("layout.method", "classical"))
    with timed("layout.segment", method=method) as info:
        result = _segment_guarded(dewarped_path, info)
        info["n_lines"] = len(result["lines"])
    return result
