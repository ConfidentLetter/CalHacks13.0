import os
from pathlib import Path

import pytest

from app import pipeline, store, telemetry


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    """Point the store, telemetry and snapshot dir at a temp folder; no camera, no model."""
    monkeypatch.setattr(store, "TWINS_DIR", tmp_path / "twins")
    monkeypatch.setattr(telemetry, "TELEMETRY_PATH", tmp_path / "telemetry.jsonl")
    monkeypatch.setattr(pipeline, "SNAPSHOT_DIR", tmp_path / "snapshots")
    store.reset()
    return tmp_path


@pytest.fixture
def mock_mode(isolated_runtime, monkeypatch):
    monkeypatch.setenv("SV_MOCK", "1")
    return isolated_runtime


@pytest.fixture
def client(mock_mode):
    from starlette.testclient import TestClient

    from app.server import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def real_client(isolated_runtime, monkeypatch):
    monkeypatch.delenv("SV_MOCK", raising=False)
    from starlette.testclient import TestClient

    from app.server import app

    with TestClient(app) as c:
        yield c


JPEG_BYTES = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")  # tiny valid-ish JPEG header
