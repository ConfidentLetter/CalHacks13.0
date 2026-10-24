"""Bridge tests: T4's app in SV_MOCK mode (vision chain = mocks/page_twin_product_rule.json), Claude mocked,
camera never opened, every runtime path under tmp_path."""
from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
MOCK_TWIN = json.loads((ROOT / "mocks" / "page_twin_product_rule.json").read_text(encoding="utf-8"))
# A real, decodable 8x8 JPEG (so the still is a valid image for every decoder, not just the magic-byte check).
import cv2  # noqa: E402

TINY_JPEG = bytes(cv2.imencode(".jpg", np.full((8, 8, 3), 200, dtype=np.uint8))[1])
TINY_JPEG_B64 = base64.b64encode(TINY_JPEG).decode("ascii")

JUDGE_REPLY = {
    "summary": "Derivative of x^2 sin x: the product rule was not applied.",
    "topics": ["Derivatives", "Product rule"],
    "steps": [
        {"id": "L0", "status": "unclear", "note": "Problem statement."},
        {"id": "L1", "status": "error", "note": "Differentiating a product needs both terms."},
        {"id": "L2", "status": "correct", "note": "SHOULD BE IGNORED: crossed out"},
        {"id": "L3", "status": "error", "note": "Built on the line above."},
    ],
    "hints": ["Recall (uv)' = u'v + uv'."],
}
CHAT_REPLY = {"reply": "Look at your line f'(x)=2x\\cdot\\cos x — what rule applies to a product?", "petExpression": "curious"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated runtime for T4's store/pipeline/telemetry and the bridge's store/uploads/stills; mock vision."""
    from app import pipeline, store, telemetry

    from bridge import camera, images, tutor
    from bridge import store as bstore

    monkeypatch.setenv("SV_MOCK", "1")
    monkeypatch.setenv("SV_CAMERA_PROBE", "0")
    monkeypatch.setenv("SV_STT", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setenv("SV_SOURCE", "webcam")  # tests never depend on config/vision.yaml capture.source
    monkeypatch.setattr(store, "TWINS_DIR", tmp_path / "twins")
    monkeypatch.setattr(pipeline, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(telemetry, "TELEMETRY_PATH", tmp_path / "telemetry.jsonl")
    monkeypatch.setattr(bstore, "READING_DIR", tmp_path / "reading")
    monkeypatch.setattr(bstore, "_default", None)
    # Stills must live inside the repo so T4's /files/ route can serve them (file_url refuses outside paths).
    scratch = ROOT / "runtime" / "_test_bridge"
    monkeypatch.setattr(images, "UPLOAD_DIR", scratch / "uploads")
    monkeypatch.setattr(camera, "SNAPSHOT_DIR", scratch / "snapshots")
    store.reset()
    images.reset_index()
    tutor.sessions.clear()
    yield tmp_path
    camera.grabber.stop()
    camera.grabber.reader = None
    shutil.rmtree(scratch, ignore_errors=True)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the one Anthropic call; records what it was asked so tests can assert on the prompt."""
    from bridge import llm

    calls: list[dict] = []

    def ask_json(system, messages, schema, *, stage, max_tokens=2048, timeout_s=None):
        calls.append({"system": system, "messages": messages, "stage": stage})
        return json.loads(json.dumps(JUDGE_REPLY if stage == "bridge.judge" else CHAT_REPLY))

    monkeypatch.setattr(llm, "ask_json", ask_json)
    return calls


@pytest.fixture
def client(env, fake_llm):
    from starlette.testclient import TestClient

    from bridge.server import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_camera(env):
    """A synthetic frame source so the grabber never touches hardware."""
    from bridge import camera

    frame = np.full((48, 64, 3), 200, dtype=np.uint8)
    frame[10:20, 10:30] = 0
    camera.grabber.reader = lambda: frame.copy()
    return frame
