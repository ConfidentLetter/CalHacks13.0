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
    twin = transcribe.build_page_twin("mocks/page_mock_01.jpg")
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator(schema).validate(twin)
    assert twin_errors(twin) == []


def test_build_page_twin_fresh_stamps_and_verbatim_mistake():
    mock = load_mock_twin()
    a = transcribe.build_page_twin("x.jpg")
    b = transcribe.build_page_twin("x.jpg")
    assert a["snapshot_id"] != mock["snapshot_id"]
    assert a["snapshot_id"] != b["snapshot_id"]
    assert a["captured_at"] != mock["captured_at"]
    # The deliberate product-rule mistake must survive untouched.
    l1 = next(l for l in a["lines"] if l["id"] == "L1")
    assert l1["latex"] == "f'(x)=2x\\cdot\\cos x"


def test_transcribe_page_lines_have_no_temporal_fields_and_match_line_schema():
    lines = transcribe.transcribe_page("mocks/page_mock_01_dewarped.jpg", {"regions": [], "lines": []})
    assert lines, "stub must return mock-consistent lines"
    schema = json.loads(SCHEMA_PATH.read_text())
    line_schema = {**schema["properties"]["lines"]["items"], "$defs": schema["$defs"]}
    line_schema["required"] = [k for k in line_schema["required"] if k not in ("first_seen", "last_changed")]
    v = Draft202012Validator(line_schema)
    for line in lines:
        assert "first_seen" not in line and "last_changed" not in line
        v.validate(line)


@pytest.mark.parametrize("latex", ["x^{2}", "f'(x)=2x\\cdot\\cos x", "\\frac{1}{2}"])
def test_parse_ok_and_normalize_are_callable(latex):
    assert isinstance(transcribe.parse_ok(latex), bool)
    assert isinstance(transcribe.normalize_latex(latex), str)
