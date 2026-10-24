"""Step 1: every T3 function exists with the contract signature and the stub twin validates."""
import inspect
import json

import pytest
from jsonschema import Draft202012Validator

import transcribe
from transcribe.schema import SCHEMA_PATH, load_mock_twin, twin_errors


def _sig(fn):
    return str(inspect.signature(fn, eval_str=True))


def test_signatures_match_contract():
    assert _sig(transcribe.transcribe_page) == "(dewarped_path: str, layout: dict, previous_twin: dict | None = None) -> list[dict]"
    assert _sig(transcribe.normalize_latex) == "(latex: str) -> str"
    assert _sig(transcribe.parse_ok) == "(latex: str) -> bool"
    assert _sig(transcribe.build_page_twin) == "(snapshot_path: str, previous_twin: dict | None = None) -> dict"


def test_build_page_twin_validates_against_schema():
    twin = transcribe.build_page_twin("mocks/page_mock_01.jpg")  # file absent: quality no_page, blank crops, no model calls
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator(schema).validate(twin)
    assert twin_errors(twin) == []


def test_mock_twin_backup_has_fresh_stamps_and_verbatim_mistake():
    from transcribe.twin import mock_twin

    mock = load_mock_twin()
    a = mock_twin("x.jpg")
    b = mock_twin("x.jpg")
    assert a["snapshot_id"] != mock["snapshot_id"]
    assert a["snapshot_id"] != b["snapshot_id"]
    assert a["captured_at"] != mock["captured_at"]
    # The deliberate product-rule mistake must survive untouched.
    l1 = next(l for l in a["lines"] if l["id"] == "L1")
    assert l1["latex"] == "f'(x)=2x\\cdot\\cos x"


def test_build_page_twin_on_missing_photo_never_raises():
    twin = transcribe.build_page_twin("runtime/snapshots/does_not_exist.jpg")
    assert twin_errors(twin) == []
    assert twin["quality"]["ok"] is False
    assert all(l["confidence"] <= 0.4 for l in twin["lines"])


def test_transcribe_page_empty_layout_makes_no_lines_and_no_model_calls():
    assert transcribe.transcribe_page("mocks/page_mock_01_dewarped.jpg", {"regions": [], "lines": []}) == []


@pytest.mark.parametrize("latex", ["x^{2}", "f'(x)=2x\\cdot\\cos x", "\\frac{1}{2}"])
def test_parse_ok_and_normalize_are_callable(latex):
    assert isinstance(transcribe.parse_ok(latex), bool)
    assert isinstance(transcribe.normalize_latex(latex), str)
