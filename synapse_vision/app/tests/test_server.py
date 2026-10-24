import json

from app import pipeline, store
from app.tests.conftest import JPEG_BYTES


def test_mock_twin_validates_against_schema():
    twin = pipeline.mock_twin()
    assert pipeline.validate(twin) == []
    assert twin["snapshot_id"].startswith("snap_mock_")
    raw = json.loads(pipeline.MOCK_PATH.read_text())
    assert twin["snapshot_id"] != raw["snapshot_id"]
    assert twin["captured_at"] != raw["captured_at"]
    assert twin["lines"] == raw["lines"]  # content untouched, verbatim


def test_twin_latest_in_mock_mode(client):
    r = client.get("/twin/latest")
    assert r.status_code == 200
    twin = r.json()
    assert pipeline.validate(twin) == []
    assert twin["source"] == "mock"
    assert any(l["status"] == "crossed_out" for l in twin["lines"])


def test_snapshot_then_get_by_id(client):
    r = client.post("/snapshot")
    assert r.status_code == 200, r.text
    twin = r.json()
    assert pipeline.validate(twin) == []
    assert twin["_fallback"] == "SV_MOCK=1"
    r2 = client.get(f"/twin/{twin['snapshot_id']}")
    assert r2.status_code == 200 and r2.json()["snapshot_id"] == twin["snapshot_id"]
    assert client.get("/twin/latest").json()["snapshot_id"] == twin["snapshot_id"]
    assert twin["snapshot_id"] in client.get("/twins").json()["snapshot_ids"]
    assert (store.TWINS_DIR / f"{twin['snapshot_id']}.json").exists()


def test_unknown_twin_404(client):
    r = client.get("/twin/does_not_exist")
    assert r.status_code == 404 and r.json()["type"] == "status"
    assert client.get("/twin/../../etc/passwd").status_code in (404, 403)


def test_upload_stores_file_and_returns_twin(client):
    r = client.post("/upload", files={"file": ("page.jpg", JPEG_BYTES, "image/jpeg")})
    assert r.status_code == 200, r.text
    twin = r.json()
    assert twin["source"] == "upload"
    assert "/snapshots/upload_" in twin["image"]["original_path"] or twin["image"]["original_path"].startswith("runtime/snapshots/upload_")
    assert (pipeline.SNAPSHOT_DIR / twin["image"]["original_path"].split("/")[-1]).exists()
    assert pipeline.validate(twin) == []


def test_upload_without_file_is_status_error(client):
    r = client.post("/upload")
    assert r.status_code == 500
    body = r.json()
    assert body["type"] == "status" and body["stage"] == "upload" and "file" in body["error"]


def test_events_order_twin_then_line_events(client):
    with client.websocket_connect("/events") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["mock"] is True
        client.post("/snapshot")
        msgs = []
        while True:
            m = ws.receive_json()
            msgs.append(m)
            if m.get("type") == "status" and m.get("phase") == "done":
                break
        types = [m["type"] for m in msgs]
        assert types[0] == "status" and msgs[0]["phase"] == "start"
        assert types[1] == "twin"
        assert "line_added" in types and "line_crossed_out" in types
        added = next(m for m in msgs if m["type"] == "line_added")
        assert added["line"]["id"] == "L3" and "latex" in added["line"]
        crossed = next(m for m in msgs if m["type"] == "line_crossed_out")
        assert crossed["line"]["status"] == "crossed_out"


def test_status_and_telemetry_routes(client):
    client.post("/snapshot")
    s = client.get("/status").json()
    assert s["mock"] is True and s["latest_snapshot_id"]
    t = client.get("/telemetry?limit=10").json()["records"]
    assert any(r["stage"] == "pipeline.snapshot_to_twin" for r in t)


def test_watch_is_noop_in_mock_mode(client):
    r = client.post("/watch", json={"on": True})
    assert r.status_code == 200 and r.json()["on"] is False
    assert client.get("/watch").json()["on"] is False


def test_files_route_restricts_to_servable_dirs(client):
    assert client.get("/files/mocks/page_twin_product_rule.json").status_code == 200
    assert client.get("/files/contracts/interfaces.md").status_code == 403
    assert client.get("/files/../etc/passwd").status_code in (403, 404)


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200 and "<" in r.text


def test_real_mode_latest_before_first_snapshot_serves_flagged_mock(real_client):
    r = real_client.get("/twin/latest")
    assert r.status_code == 200 and "no real twin yet" in r.json()["_fallback"] and r.json()["source"] == "mock"
    assert store.latest() is None  # not persisted as if it were real


def test_real_mode_without_transcribe_falls_back_to_mock(real_client, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "transcribe":
            raise ImportError("not ready")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    r = real_client.post("/upload", files={"file": ("p.jpg", JPEG_BYTES, "image/jpeg")})
    assert r.status_code == 200, r.text
    assert "unavailable" in r.json()["_fallback"]


def test_real_mode_pipeline_error_is_reported_not_fatal(real_client, monkeypatch):
    def boom(path, previous, source):
        raise pipeline.PipelineError("transcribe", "model exploded")

    monkeypatch.setattr(pipeline, "build_twin", boom)
    with real_client.websocket_connect("/events") as ws:
        ws.receive_json()
        r = real_client.post("/upload", files={"file": ("p.jpg", JPEG_BYTES, "image/jpeg")})
        assert r.status_code == 500
        assert r.json() == {"type": "status", "stage": "transcribe", "error": "model exploded", "ok": False}
        seen = [ws.receive_json() for _ in range(2)]
        assert any(m.get("error") == "model exploded" for m in seen)
    # still serving afterwards
    assert real_client.get("/status").status_code == 200


def test_real_mode_snapshot_without_capture_reports_capture_stage(real_client, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("capture"):
            raise ImportError("no camera code yet")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    r = real_client.post("/snapshot")
    assert r.status_code == 500 and r.json()["stage"] == "capture"
