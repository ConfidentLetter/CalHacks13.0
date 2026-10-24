"""Step 1: exact signatures, mock-consistent output, crops on disk, schema validation."""
import inspect
import json
import sys
from pathlib import Path

import cv2
import jsonschema
import numpy as np
import pytest

import layout
from layout import is_crossed_out, segment
from layout._compat import REPO_ROOT
from layout.mock_layout import load_mock_twin

SCHEMA = json.loads((REPO_ROOT / "contracts" / "page_twin.schema.json").read_text())


@pytest.fixture()
def blank_page(tmp_path: Path) -> str:
    img = np.full((2200, 1700, 3), 255, dtype=np.uint8)
    cv2.putText(img, "f(x) = x^2 sin x", (140, 220), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 2.5, (0, 0, 0), 4)
    p = tmp_path / "snap_test_01.png"
    cv2.imwrite(str(p), img)
    return str(p)


def test_signatures_match_contract():
    assert str(inspect.signature(segment, eval_str=True)) == "(dewarped_path: str) -> dict"
    assert str(inspect.signature(is_crossed_out, eval_str=True)) == "(crop_path: str) -> tuple[bool, float]"
    assert layout.segment is segment and layout.is_crossed_out is is_crossed_out


def test_segment_matches_mock_bboxes(blank_page, monkeypatch):
    seg_module = sys.modules["layout.segment"]
    monkeypatch.setattr(seg_module, "config_get", lambda k, d=None: "mock" if k == "layout.method" else d)
    out = segment(blank_page)
    mock = load_mock_twin()
    assert [r["bbox"] for r in out["regions"]] == [r["bbox"] for r in mock["regions"]]
    expected = sorted(mock["lines"], key=lambda l: l["order"])
    assert [l["bbox"] for l in out["lines"]] == [l["bbox"] for l in expected]
    assert [l["status_hint"] for l in out["lines"]] == ["active", "active", "crossed_out", "active"]


def test_segment_line_fields_and_crops_exist(blank_page):
    out = segment(blank_page)
    assert out["lines"], "segment must return lines"
    for i, line in enumerate(out["lines"]):
        assert set(line) >= {"bbox", "crop_path", "context_crop_path", "status_hint", "ink_density"}
        assert line["status_hint"] in {"active", "crossed_out", "unsure"}
        assert 0.0 <= line["ink_density"] <= 1.0
        for key in ("crop_path", "context_crop_path"):
            p = REPO_ROOT / line[key]
            assert p.exists() and "runtime/crops/snap_test_01" in line[key].replace("\\", "/")
            assert cv2.imread(str(p)) is not None
    orders = [l["order"] for l in out["lines"]]
    assert orders == list(range(len(orders)))


def test_segment_on_unreadable_path_never_raises(tmp_path):
    out = segment(str(tmp_path / "does_not_exist.jpg"))
    assert isinstance(out["regions"], list) and isinstance(out["lines"], list)


def test_segment_falls_back_to_empty_layout_when_segmenter_raises(blank_page, monkeypatch):
    import layout.classical as classical

    def boom(_path):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(classical, "segment_classical", boom)
    out = segment(blank_page)
    assert out == {"regions": [], "lines": []}


def test_crops_pad_out_of_bounds(tmp_path):
    from layout.crops import extract_padded

    img = np.zeros((50, 50), dtype=np.uint8)
    crop = extract_padded(img, [-20, -20, 100, 100])
    assert crop.shape == (100, 100)
    assert crop[0, 0] == 255 and crop[20, 20] == 0


def test_is_crossed_out_returns_tuple(blank_page):
    out = segment(blank_page)
    crossed, conf = is_crossed_out(str(REPO_ROOT / out["lines"][0]["crop_path"]))
    assert isinstance(crossed, bool) and 0.0 <= conf <= 1.0


def test_output_validates_against_page_twin_schema(blank_page):
    """Splice segment output into the mock twin and validate the result."""
    out = segment(blank_page)
    twin = json.loads(json.dumps(load_mock_twin()))
    twin["regions"] = out["regions"]
    template = twin["lines"][0]
    twin["lines"] = [
        {
            **template,
            "id": f"L{i}",
            "region_id": l.get("region_id", out["regions"][0]["id"]),
            "order": i,
            "bbox": l["bbox"],
            "status": "crossed_out" if l["status_hint"] == "crossed_out" else "active",
        }
        for i, l in enumerate(out["lines"])
    ]
    jsonschema.validate(twin, SCHEMA)
