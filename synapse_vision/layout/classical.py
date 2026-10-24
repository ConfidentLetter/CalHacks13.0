"""Classical line segmentation (``layout.method: classical``)."""
from __future__ import annotations

import cv2
import numpy as np

from layout._compat import REPO_ROOT, config_get, timed
from layout.binarize import binarize_page, to_gray
from layout.components import drop_faint_components, find_components, fuse_fractions, median_component_size, speck_area
from layout.crops import snapshot_id_from_path, write_all_crops
from layout.crossed_out import is_crossed_out
from layout.debug import write_debug_overlay
from layout.lines import drop_noise_lines, group_into_lines, median_line_height, merge_duplicates, merge_fragments, split_columns
from layout.order import order_and_regionize

UNSURE_MIN_CONF = 0.4


def status_hint_for(crop_path: str) -> str:
    try:
        crossed, conf = is_crossed_out(str(REPO_ROOT / crop_path))
    except Exception:  # noqa: BLE001 - one odd crop must not empty the whole page
        return "unsure"
    min_conf = float(config_get("layout.crossed_out_min_conf", 0.6))
    if crossed and conf >= min_conf:
        return "crossed_out"
    if conf >= UNSURE_MIN_CONF:
        return "unsure"
    return "active"


def detect_lines(img: np.ndarray) -> tuple[list[dict], list[dict]]:
    """Image -> (regions, ordered line specs [{bbox, region_id}]). No crops, no files."""
    gray = to_gray(img)
    H, W = gray.shape
    with timed("layout.binarize"):
        binary, _ = binarize_page(gray)
    with timed("layout.components") as info:
        comps = drop_faint_components(find_components(binary), gray, binary)
        med_char_w, med_comp_h = median_component_size(comps)
        comps = fuse_fractions(comps, binary, med_char_w, med_comp_h, W)
        info["n_components"] = len(comps)
    with timed("layout.group") as info:
        lines = group_into_lines(comps, med_char_w)
        med_line_h = max(median_line_height(lines), float(config_get("layout.min_line_height_px", 28)))
        lines = merge_fragments(lines, med_line_h, med_char_w)
        lines = split_columns(lines, med_line_h, med_char_w, W)
        lines = merge_duplicates(lines)
        lines = drop_noise_lines(lines, speck_area(binary.shape))
        info["n_lines"] = len(lines)
    return order_and_regionize(lines, med_char_w, med_line_h, W)


def segment_classical(dewarped_path: str) -> dict:
    from layout.segment import load_page  # local import: segment.py imports this module lazily

    img = load_page(dewarped_path)
    snapshot_id = snapshot_id_from_path(dewarped_path)
    regions, specs = detect_lines(img)
    with timed("layout.crops", n_lines=len(specs)):
        crops = write_all_crops(img, [s["bbox"] for s in specs], snapshot_id, groups=[s["region_id"] for s in specs])
    with timed("layout.crossed_out", n_lines=len(specs)):
        lines = [
            {"order": i, "region_id": s["region_id"], "bbox": [float(v) for v in s["bbox"]],
             "status_hint": status_hint_for(c["crop_path"]), **c}
            for i, (s, c) in enumerate(zip(specs, crops))
        ]
    result = {"regions": regions, "lines": lines}
    write_debug_overlay(img, result, snapshot_id)
    return result
