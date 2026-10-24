"""Classical line segmentation (``layout.method: classical``)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from layout._compat import REPO_ROOT, config_get, timed
from layout.binarize import binarize_page, to_gray
from layout.components import (drop_faint_components, drop_isolated_specks, drop_rule_slivers, drop_texture_specks,
                               find_components_with_labels,
                               fuse_fractions, ink_mask,
                               median_component_size, speck_area, split_tall_components)
from layout.crops import snapshot_id_from_path, write_all_crops
from layout.crossed_out import is_crossed_out
from layout.debug import write_debug_overlay
from layout.lines import (drop_noise_lines, group_into_lines, median_line_height, merge_adjacent, merge_duplicates,
                          merge_fragments, split_columns)
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


def gray_sibling(dewarped_path: str) -> np.ndarray | None:
    """T1 writes ``<stem>_gray.png`` next to the colour page (lighting-flattened + CLAHE); prefer it for ink masks."""
    p = Path(dewarped_path)
    for cand in (p.with_name(p.stem + "_gray.png"), p.with_name(p.stem + "_gray.jpg")):
        if cand.exists():
            g = cv2.imread(str(cand), cv2.IMREAD_GRAYSCALE)
            if g is not None:
                return g
    return None


def detect_lines(img: np.ndarray, gray: np.ndarray | None = None) -> tuple[list[dict], list[dict]]:
    """Image -> (regions, ordered line specs [{bbox, region_id}]). No crops, no files."""
    gray = to_gray(img) if gray is None or gray.shape[:2] != img.shape[:2] else gray
    H, W = gray.shape
    with timed("layout.binarize"):
        binary, _ = binarize_page(gray)
    with timed("layout.components") as info:
        comps, labels = find_components_with_labels(binary)
        comps = drop_faint_components(comps, gray, binary)
        med_char_w, med_comp_h = median_component_size(comps)
        comps = drop_rule_slivers(drop_texture_specks(comps, med_char_w, med_comp_h), med_char_w, med_comp_h, W)
        comps = drop_isolated_specks(comps, med_char_w, med_comp_h)
        comps, tall = split_tall_components(comps, med_comp_h)
        clean = ink_mask(labels, comps)   # bleed-through, texture and drawings no longer confuse the fraction probes
        comps = fuse_fractions(comps, clean, med_char_w, med_comp_h, W)
        info["n_components"], info["n_tall"] = len(comps), len(tall)
    with timed("layout.group") as info:
        lines = group_into_lines(comps, med_char_w, med_comp_h)
        med_line_h = max(median_line_height(lines), float(config_get("layout.min_line_height_px", 28)))
        lines = merge_fragments(lines, med_line_h, med_char_w, med_comp_h)
        lines = merge_adjacent(lines, med_char_w)
        lines = split_columns(lines, med_line_h, med_char_w, W)
        lines = merge_duplicates(lines)
        lines = drop_noise_lines(lines, speck_area(binary.shape), float(config_get("layout.min_line_height_px", 28)))
        info["n_lines"] = len(lines)
    return order_and_regionize(lines, med_char_w, med_line_h, W, drawings=[t.bbox for t in tall])


def segment_classical(dewarped_path: str) -> dict:
    from layout.segment import load_page  # local import: segment.py imports this module lazily

    img = load_page(dewarped_path)
    snapshot_id = snapshot_id_from_path(dewarped_path)
    regions, specs = detect_lines(img, gray_sibling(dewarped_path))
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
