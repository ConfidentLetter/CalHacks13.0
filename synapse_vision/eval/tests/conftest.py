import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app import pipeline, store, telemetry
from eval import label_helper
from eval import truth as T


def make_page(path: Path, w: int = 850, h: int = 1100) -> None:
    """A synthetic white page with a few dark 'lines' of ink (enough for wiring tests)."""
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    for i, y in enumerate((150, 320, 460, 600)):
        d.rectangle([130, y, 130 + 400 + 80 * i, y + 60], outline="black", width=6)
    img.save(path, quality=90)


@pytest.fixture
def testset(tmp_path, monkeypatch):
    """A temp testset with two photos and no truth files, wired into eval.truth and the server."""
    ts = tmp_path / "testset"
    ts.mkdir()
    make_page(ts / "1.jpg")
    make_page(ts / "2.jpg")
    monkeypatch.setattr(T, "TESTSET_DIR", ts)
    monkeypatch.setattr(T, "ROOT", tmp_path)
    monkeypatch.setattr(label_helper.T, "TESTSET_DIR", ts)
    monkeypatch.setattr(store, "TWINS_DIR", tmp_path / "twins")
    monkeypatch.setattr(telemetry, "TELEMETRY_PATH", tmp_path / "telemetry.jsonl")
    monkeypatch.setattr(pipeline, "SNAPSHOT_DIR", tmp_path / "snapshots")
    store.reset()
    return ts


@pytest.fixture
def mock_truth():
    twin = pipeline.mock_twin(source="upload", original_path="eval/testset/1.jpg")
    return T.truth_from_twin(twin, "eval/testset/1.jpg")


@pytest.fixture
def client(testset, monkeypatch):
    monkeypatch.setenv("SV_MOCK", "1")
    from starlette.testclient import TestClient

    from app.server import app

    with TestClient(app) as c:
        yield c
