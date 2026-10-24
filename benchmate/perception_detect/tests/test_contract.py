"""Step 1: every contract function exists with the exact signature and output validates."""
import inspect
import json

import perception_detect as pd
from perception_detect.schema import validate_twin


def _sig(fn):
    """Signature with string annotations resolved (modules use `from __future__ import annotations`)."""
    return inspect.signature(fn, eval_str=True)


def _positional(fn):
    return [p.name for p in _sig(fn).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]


def test_public_functions_exist_with_contract_signatures():
    # register(part_id: str, row_index: int, pixel: tuple[float, float]) -> None (+ optional kw-only extras)
    assert _positional(pd.register) == ["part_id", "row_index", "pixel"]
    assert _sig(pd.register).return_annotation is None
    # detect_components(frame_path: str, tiles: list[dict] | None = None) -> list[dict] (+ kw-only extras)
    assert _positional(pd.detect_components) == ["frame_path", "tiles"]
    assert _sig(pd.detect_components).parameters["tiles"].default is None
    assert _sig(pd.detect_components).return_annotation == list[dict]
    assert str(_sig(pd.normalize_part)) == "(label_text: str) -> str | None"
    assert str(_sig(pd.build_twin)) == "(frame_path: str) -> dict"


def test_build_twin_validates_against_schema(tmp_path):
    twin = pd.build_twin(str(tmp_path / "missing.jpg"))
    assert validate_twin(twin) == []


def test_build_twin_has_fresh_frame_id_and_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv("BM_MOCK", "1")
    mock = json.loads((pd.twin.MOCK_TWIN_OK_PATH).read_text())
    a = pd.build_twin(str(tmp_path / "a.jpg"))
    (tmp_path / "b.jpg").write_bytes(b"different bytes")
    b = pd.build_twin(str(tmp_path / "b.jpg"))
    assert a["frame_id"] != mock["frame_id"]
    assert a["timestamp"] != mock["timestamp"]
    assert a["frame_id"] != b["frame_id"]
    assert a["components"] == mock["components"]
    assert a["nets"] == mock["nets"]


def test_detect_components_items_validate_inside_twin(tmp_path, monkeypatch):
    comps = pd.detect_components(str(tmp_path / "x.jpg"))   # nothing registered -> no components
    twin = {**pd.build_twin(str(tmp_path / "x.jpg")), "components": comps}
    assert validate_twin(twin) == [] and comps == []
    monkeypatch.setenv("BM_MOCK", "1")
    comps = pd.detect_components(str(tmp_path / "x.jpg"))
    assert validate_twin({**twin, "components": comps}) == []
    assert {c["part_id"] for c in comps} == {"esp32-devkitc", "bme280"}
