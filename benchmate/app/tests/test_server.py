"""Tests for app.server (Step 4) in mock mode with FastAPI's TestClient."""
import json
import os
import time

import pytest

os.environ["BM_MOCK"] = "1"
os.environ["BM_NO_CAMERA"] = "1"
os.environ["BM_SERIAL_REPLAY_INTERVAL"] = "0.05"
os.environ.setdefault("BM_RUNTIME_DIR", f"/tmp/benchmate_test_runtime_{os.getpid()}")

from fastapi.testclient import TestClient  # noqa: E402

from app import modules, server  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def recv_until(ws, predicate, timeout=5.0):
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        msg = ws.receive_json()
        seen.append(msg)
        if predicate(msg):
            return msg, seen
    raise AssertionError(f"no matching message; saw types {[m['type'] for m in seen]}")


def test_index_and_healthz(client):
    r = client.get("/")
    assert r.status_code == 200 and "BenchMate" in r.text
    h = client.get("/healthz").json()
    assert h["ok"] is True and h["mock"] is True and h["serial"]["mode"] == "replay"


def test_frame_jpg_and_stream(client):
    deadline = time.time() + 3
    r = client.get("/frame.jpg")
    while r.status_code == 503 and time.time() < deadline:
        time.sleep(0.05)
        r = client.get("/frame.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    with client.stream("GET", "/stream") as s:
        assert s.headers["content-type"].startswith("multipart/x-mixed-replace")
        buf = b""
        for chunk in s.iter_bytes():
            buf += chunk
            if buf.count(b"--frame") >= 2:
                break
    assert b"Content-Type: image/jpeg" in buf


def test_post_read_validates_and_records(client, monkeypatch):
    seen = []
    monkeypatch.setattr(modules, "record_read", lambda url, text, s: seen.append((url, s)))
    assert client.post("/read", json={"url": "https://x/bme280.pdf", "text": "VDD max 3.6V", "seconds": 42}).json() == {"ok": True}
    assert seen == [("https://x/bme280.pdf", 42.0)]
    assert client.post("/read", json={"url": "", "seconds": 1}).status_code == 422
    assert client.post("/read", json={"seconds": -1}).status_code == 422


def test_api_profiles_state_telemetry(client):
    profiles = client.get("/api/profiles").json()
    assert {p["part_id"] for p in profiles} >= {"bme280", "esp32-devkitc"}
    state = client.get("/api/state").json()
    assert state["mock"] is True and "budget_ms" in state
    assert isinstance(client.get("/api/telemetry?n=5").json(), list)


def test_websocket_full_mock_demo_flow(client):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["mock"] is True

        ws.send_json({"type": "mock", "scenario": "sda_swapped"})
        twin_msg, _ = recv_until(ws, lambda m: m["type"] == "twin" and m["twin"].get("_mock_scenario") == "sda_swapped", timeout=60)
        assert modules.validation_error(modules.TWIN_VALIDATOR, twin_msg["twin"]) is None
        # first call into reasoning/knowledge may import torch etc.: allow a long first wait
        diag_msg, _ = recv_until(ws, lambda m: m["type"] == "diagnosis" and m["diagnosis"]["frame_id"] == twin_msg["twin"]["frame_id"], timeout=60)
        assert modules.validation_error(modules.DIAGNOSIS_VALIDATOR, diag_msg["diagnosis"]) is None
        assert diag_msg["diagnosis"]["mode"] == "proactive"

        ws.send_json({"type": "ask", "question": "why isn't the sensor reading?"})
        ans, _ = recv_until(ws, lambda m: m["type"] == "diagnosis" and m["diagnosis"]["mode"] == "answer", timeout=60)
        assert ans["diagnosis"]["question"] == "why isn't the sensor reading?"

        serial_msg, _ = recv_until(ws, lambda m: m["type"] == "serial", timeout=3)
        assert serial_msg["line"]

        ws.send_json({"type": "confirm", "element_id": "w_yellow_1", "answer": True})
        recv_until(ws, lambda m: m["type"] == "status" and m["stage"] == "confirm")

        ws.send_json({"type": "calibrate", "corners": [[0, 0], [1, 0], [1, 1], [0, 1]]})
        recv_until(ws, lambda m: m["type"] == "status" and m["stage"] == "calibrate" and m.get("ok"))

        ws.send_text("this is not json")
        err, _ = recv_until(ws, lambda m: m["type"] == "status" and "bad JSON" in m.get("error", ""))

        ws.send_json({"type": "nonsense"})
        err, _ = recv_until(ws, lambda m: m["type"] == "status" and "unknown message type" in m.get("error", ""))

        ws.send_json({"type": "ping"})  # still alive after errors
        recv_until(ws, lambda m: m["type"] == "status" and m["stage"] == "pong")


def test_json_safe_strips_non_finite_numbers():
    msg = {"a": float("inf"), "b": [1.5, float("nan"), {"c": -float("inf")}], "d": "ok", "e": 3}
    out = json.loads(json.dumps(server.json_safe(msg)))
    assert out == {"a": None, "b": [1.5, None, {"c": None}], "d": "ok", "e": 3}
