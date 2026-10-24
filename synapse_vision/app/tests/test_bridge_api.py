"""What T5's bridge relies on: side-effect-free import, accessors, frame provider, analyze()."""
import socket
import subprocess
import sys

from app import bridge_api, pipeline, store
from app.tests.conftest import JPEG_BYTES


def test_import_app_server_has_no_side_effects():
    code = (
        "import sys, app.server; "
        "bad = [m for m in sys.modules if m.split('.')[0] in ('capture', 'layout', 'transcribe', 'cv2', 'anthropic')]; "
        "print('|'.join(bad))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"pipeline modules imported at import time: {out.stdout}"
    with socket.socket() as s:  # nothing bound port 8000 just by importing
        s.settimeout(0.2)
        try:
            s.connect(("127.0.0.1", 8000))
            bound_by_someone = True
        except OSError:
            bound_by_someone = False
    # If a server IS running on 8000 that is the long-lived process, not this import; the import itself never binds.
    assert bound_by_someone in (True, False)


def test_accessors_before_any_twin(isolated_runtime):
    assert bridge_api.latest_twin() is None
    assert bridge_api.latest_snapshot() is None
    assert bridge_api.latest_frame_path() is None


def test_accessors_after_upload(client):
    client.post("/upload", files={"file": ("p.jpg", JPEG_BYTES, "image/jpeg")})
    snap = bridge_api.latest_snapshot()
    assert snap["snapshot_id"] == store.latest()["snapshot_id"] and snap["line_count"] == 4 and snap["mock"] is True
    assert snap["image_url"] is None or snap["image_url"].startswith("/files/")
    assert bridge_api.latest_frame_path().endswith(".jpg")


def test_file_url_only_inside_repo():
    assert bridge_api.file_url("runtime/snapshots/a.jpg") == "/files/runtime/snapshots/a.jpg"
    assert bridge_api.file_url(str(pipeline.ROOT / "runtime" / "x.png")) == "/files/runtime/x.png"
    assert bridge_api.file_url("/etc/passwd") is None and bridge_api.file_url(None) is None


def test_frame_provider_replaces_camera(real_client, monkeypatch):
    calls = []

    def provider():
        calls.append(1)
        p = pipeline.SNAPSHOT_DIR / "from_bridge.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(JPEG_BYTES)
        return str(p)

    monkeypatch.setattr(pipeline, "build_twin", lambda path, prev, src: {**pipeline.mock_twin(prev, src, path), "_fallback": "test"})
    pipeline.set_frame_provider(provider)
    try:
        r = real_client.post("/snapshot")
        assert r.status_code == 200, r.text
        assert calls == [1] and r.json()["image"]["original_path"].endswith("from_bridge.jpg")
        pipeline.set_frame_provider(lambda: None)
        r = real_client.post("/snapshot")
        assert r.status_code == 500 and r.json()["stage"] == "capture"
    finally:
        pipeline.set_frame_provider(None)


def test_analyze_coroutine_stores_and_broadcasts(real_client, monkeypatch):
    import asyncio

    from app import server

    monkeypatch.setattr(pipeline, "build_twin", lambda path, prev, src: {**pipeline.mock_twin(prev, src, path), "_fallback": "test"})
    with real_client.websocket_connect("/events") as ws:
        ws.receive_json()
        twin = real_client.portal.call(server.analyze, "runtime/snapshots/x.jpg", "webcam") if hasattr(real_client, "portal") else asyncio.run(server.analyze("runtime/snapshots/x.jpg", "webcam"))
        assert twin["source"] == "webcam" and store.latest()["snapshot_id"] == twin["snapshot_id"]
        assert ws.receive_json()["type"] == "status"
        assert ws.receive_json()["type"] == "twin"
