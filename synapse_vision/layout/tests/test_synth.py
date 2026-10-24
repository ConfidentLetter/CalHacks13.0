"""Step 2: synthetic pages have consistent ground truth and validate against the schema."""
import json

import jsonschema
import numpy as np
import pytest

from layout._compat import REPO_ROOT
from layout.geometry import y_overlap
from layout.mock_layout import load_mock_twin
from layout.tests.synth import INK_LUMA_MAX, PAGE_H, PAGE_W, render_demo_page, render_page

SCHEMA = json.loads((REPO_ROOT / "contracts" / "page_twin.schema.json").read_text())


@pytest.mark.parametrize("seed", list(range(1, 13)))
def test_page_ground_truth_is_consistent(seed):
    page = render_page(seed)
    assert page.image.shape == (PAGE_H, PAGE_W, 3)
    assert 4 <= len(page.lines) <= 13
    assert [l.order for l in page.lines] == list(range(len(page.lines)))
    gray = page.image.mean(axis=2)
    main = [l for l in page.lines if l.region != "margin"]
    for l in page.lines:
        x, y, w, h = l.bbox
        assert 0 <= x and 0 <= y and x + w <= PAGE_W and y + h <= PAGE_H
        assert w > 20 and h > 10
        assert (gray[y: y + h, x: x + w] < INK_LUMA_MAX).any(), "bbox must contain ink"
    for a, b in zip(main, main[1:]):
        assert b.bbox[1] >= a.bbox[1], "main column is top-to-bottom"
        assert y_overlap(a.bbox, b.bbox) <= 0.15 * min(a.bbox[3], b.bbox[3]), "consecutive lines barely overlap"
    assert 1 <= sum(l.crossed_out for l in page.lines) <= 2
    assert page.lines[0].region == "problem" and not page.lines[0].crossed_out


def test_render_is_deterministic():
    a, b = render_page(7), render_page(7)
    assert np.array_equal(a.image, b.image)
    assert [l.as_dict() for l in a.lines] == [l.as_dict() for l in b.lines]


def test_options_are_honoured():
    page = render_page(3, n_lines=5, ruled=True, pencil=True, n_crossed=2, margin_note=True)
    assert page.ruled and page.pencil
    assert sum(l.crossed_out for l in page.lines) == 2
    assert page.lines[-1].region == "margin"
    assert len([l for l in page.lines if l.region != "margin"]) == 5


def test_demo_page_layout():
    page = render_demo_page()
    assert [l.crossed_out for l in page.lines] == [False, False, True, False]
    assert page.lines[0].region == "problem"


def test_save_roundtrip(tmp_path):
    img_path, gt_path = render_page(5).save(tmp_path)
    assert img_path.exists() and gt_path.exists()
    gt = json.loads(gt_path.read_text())
    assert gt["seed"] == 5 and len(gt["lines"]) >= 4


def test_ground_truth_validates_against_schema():
    page = render_page(9)
    twin = json.loads(json.dumps(load_mock_twin()))
    template = twin["lines"][0]
    twin["regions"] = [{"id": "R0", "type": "problem", "bbox": page.lines[0].bbox}, {"id": "R1", "type": "work", "bbox": [0, 0, PAGE_W, PAGE_H]}]
    twin["lines"] = [{**template, "id": f"L{i}", "region_id": "R0" if l.region == "problem" else "R1", "order": l.order,
                      "bbox": l.bbox, "status": "crossed_out" if l.crossed_out else "active"} for i, l in enumerate(page.lines)]
    jsonschema.validate(twin, SCHEMA)
