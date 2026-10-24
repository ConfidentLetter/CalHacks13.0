from __future__ import annotations

import os
from pathlib import Path

import pytest

from capture.tests import synth

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _no_live_source(monkeypatch):
    """Tests never touch a camera: force SV_SOURCE to an upload path unless a test overrides it."""
    monkeypatch.delenv("SV_SOURCE", raising=False)


@pytest.fixture
def synth_photo(tmp_path) -> dict:
    sample = synth.render(1)
    path = synth.save(sample, tmp_path / "synth_001.jpg")
    return {"path": str(path), "sample": sample}


@pytest.fixture
def schema() -> dict:
    import json

    return json.loads((REPO_ROOT / "contracts" / "page_twin.schema.json").read_text())
