"""Step 3: classical segmentation vs synthetic ground truth.

Targets (prompts/T2_layout.md): >= 95 % of GT lines matched at IoU >= 0.6, no merged
lines, exact reading order on >= 95 % of pages.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import jsonschema
import pytest

from layout._compat import REPO_ROOT
from layout.classical import detect_lines
from layout.geometry import iou
from layout.mock_layout import load_mock_twin
from layout.tests.synth import render_demo_page, render_page

SCHEMA = json.loads((REPO_ROOT / "contracts" / "page_twin.schema.json").read_text())
SEEDS = list(range(1, 31))
IOU_MATCH = 0.6
MERGE_COVER = 0.5  # a predicted box covering this much of two GT boxes is a merge


@dataclass
class PageScore:
    seed: int
    n_gt: int
    matched: int
    merges: int
    order_exact: bool
    n_pred: int


def _cover(pred, gt) -> float:
    """Fraction of gt area inside pred."""
    ix0, iy0 = max(pred[0], gt[0]), max(pred[1], gt[1])
    ix1, iy1 = min(pred[0] + pred[2], gt[0] + gt[2]), min(pred[1] + pred[3], gt[1] + gt[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    return inter / max(1, gt[2] * gt[3])


def score_page(seed: int) -> PageScore:
    page = render_page(seed)
    _, specs = detect_lines(page.image)
    preds = [s["bbox"] for s in specs]
    gts = [l.bbox for l in page.lines]
    pairs = sorted(((iou(p, g), pi, gi) for pi, p in enumerate(preds) for gi, g in enumerate(gts)), reverse=True)
    used_p, used_g, match = set(), set(), {}
    for score, pi, gi in pairs:
        if score < IOU_MATCH or pi in used_p or gi in used_g:
            continue
        used_p.add(pi); used_g.add(gi); match[pi] = gi
    merges = sum(1 for p in preds if sum(_cover(p, g) >= MERGE_COVER for g in gts) >= 2)
    gt_orders = [page.lines[match[pi]].order for pi in sorted(match)]
    order_exact = gt_orders == sorted(gt_orders) and len(match) == len(gts)
    return PageScore(seed, len(gts), len(match), merges, order_exact, len(preds))


@pytest.fixture(scope="module")
def scores() -> list[PageScore]:
    return [score_page(s) for s in SEEDS]


def test_line_recall_at_least_95_percent(scores):
    total = sum(s.n_gt for s in scores)
    matched = sum(s.matched for s in scores)
    bad = [(s.seed, s.matched, s.n_gt, s.n_pred) for s in scores if s.matched < s.n_gt]
    assert matched / total >= 0.95, f"recall {matched}/{total}; misses (seed, matched, gt, pred): {bad}"


def test_no_merged_lines(scores):
    merged = [(s.seed, s.merges) for s in scores if s.merges]
    assert not merged, f"merged lines on pages {merged}"


def test_reading_order_exact_on_95_percent_of_pages(scores):
    ok = sum(s.order_exact for s in scores)
    wrong = [s.seed for s in scores if not s.order_exact]
    assert ok / len(scores) >= 0.95, f"order wrong on seeds {wrong}"


def test_demo_page_four_lines_in_order():
    page = render_demo_page()
    regions, specs = detect_lines(page.image)
    assert len(specs) == 4
    assert all(iou(s["bbox"], l.bbox) >= IOU_MATCH for s, l in zip(specs, page.lines))
    assert regions[0]["type"] == "problem" and specs[0]["region_id"] == regions[0]["id"]


def test_margin_note_gets_margin_region():
    page = render_page(3, n_lines=5, margin_note=True)
    regions, specs = detect_lines(page.image)
    margin = [r for r in regions if r["type"] == "margin"]
    assert len(margin) == 1
    note = page.lines[-1]
    assert any(iou(s["bbox"], note.bbox) >= IOU_MATCH and s["region_id"] == margin[0]["id"] for s in specs)


def test_ruled_and_pencil_pages_still_segment():
    page = render_page(11, n_lines=6, ruled=True, pencil=True, margin_note=False)
    _, specs = detect_lines(page.image)
    assert len(specs) == len(page.lines)


def _count_matched(page, img) -> tuple[int, int]:
    _, specs = detect_lines(img)
    matched = sum(any(iou(s["bbox"], l.bbox) >= IOU_MATCH for s in specs) for l in page.lines)
    return matched, len(specs)


def test_graph_paper_grid_is_ignored():
    import cv2
    from layout.tests.synth import PAGE_H, PAGE_W

    page = render_page(5, ruled=False, margin_note=False)
    img = page.image.copy()
    for xx in range(40, PAGE_W, 42):
        cv2.line(img, (xx, 0), (xx, PAGE_H), (225, 210, 200), 1)
    for yy in range(30, PAGE_H, 42):
        cv2.line(img, (0, yy), (PAGE_W, yy), (225, 210, 200), 1)
    assert _count_matched(page, img) == (len(page.lines), len(page.lines))


@pytest.mark.parametrize("bleed_gray", [218, 200, 185])
def test_bleed_through_from_back_of_page_is_ignored(bleed_gray):
    import cv2
    import numpy as np

    page = render_page(6, ruled=False, margin_note=False)
    ghost = cv2.flip(render_page(9, ruled=False, margin_note=False).image, 1).mean(axis=2) < 160
    img = page.image.copy()
    faint = img.copy()
    faint[ghost] = (bleed_gray, bleed_gray - 2, bleed_gray - 4)
    img = np.where(page.image.mean(axis=2, keepdims=True) < 200, page.image, faint).astype(np.uint8)
    assert _count_matched(page, img) == (len(page.lines), len(page.lines))


def test_dark_dewarp_border_slivers_are_ignored():
    import cv2
    from layout.tests.synth import PAGE_H, PAGE_W

    page = render_page(8, ruled=False, margin_note=False)
    img = page.image.copy()
    cv2.rectangle(img, (0, 0), (7, PAGE_H), (40, 40, 40), -1)            # left sliver
    cv2.rectangle(img, (PAGE_W - 5, 300), (PAGE_W, PAGE_H), (60, 60, 60), -1)  # partial right sliver
    cv2.rectangle(img, (0, PAGE_H - 9), (PAGE_W, PAGE_H), (50, 50, 50), -1)    # bottom sliver
    assert _count_matched(page, img) == (len(page.lines), len(page.lines))


def test_dashed_rules_after_clahe_are_ignored():
    """Dewarp + JPEG + CLAHE turn printed rules into dark dashes; they must not become lines."""
    import cv2
    from layout.tests.synth import PAGE_H, PAGE_W

    page = render_page(14, ruled=False, margin_note=False)
    img = page.image.copy()
    for yy in range(160, PAGE_H, 142):
        for xx in range(0, PAGE_W, 60):
            if (xx // 60 + yy) % 3:  # broken rule: 2 dashes of 3
                cv2.line(img, (xx, yy), (xx + 40, yy), (200, 196, 206), 2)
    gray = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    _, specs = detect_lines(img, gray)
    matched = sum(any(iou(s["bbox"], l.bbox) >= IOU_MATCH for s in specs) for l in page.lines)
    assert (matched, len(specs)) == (len(page.lines), len(page.lines))


def test_segment_output_validates_against_schema(tmp_path):
    import cv2
    from layout import segment

    page = render_demo_page()
    p = tmp_path / "synth_demo.png"
    cv2.imwrite(str(p), page.image)
    out = segment(str(p))
    twin = json.loads(json.dumps(load_mock_twin()))
    template = twin["lines"][0]
    twin["regions"] = out["regions"]
    twin["lines"] = [{**template, "id": f"L{i}", "region_id": l["region_id"], "order": i, "bbox": l["bbox"],
                      "status": "crossed_out" if l["status_hint"] == "crossed_out" else "active"} for i, l in enumerate(out["lines"])]
    jsonschema.validate(twin, SCHEMA)
    assert (REPO_ROOT / "runtime" / "debug" / "layout_synth_demo.png").exists()
