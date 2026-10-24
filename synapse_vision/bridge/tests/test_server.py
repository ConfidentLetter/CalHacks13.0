"""The bridge process: CORS, T4's routes still served, status shape, body size, error shape."""
from __future__ import annotations

import base64
import os


def test_cors_header_for_dashboard_origin(client):
    r = client.get("/api/status", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_preflight(client):
    r = client.options("/api/camera/analyze", headers={"Origin": "http://127.0.0.1:5173",
                                                      "Access-Control-Request-Method": "POST",
                                                      "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert "POST" in r.headers.get("access-control-allow-methods", "")


def test_t4_twin_latest_still_served(client):
    r = client.get("/twin/latest")
    assert r.status_code == 200
    assert r.json()["lines"][1]["latex"] == "f'(x)=2x\\cdot\\cos x"


def test_t4_status_and_upload_still_served(client):
    assert client.get("/status").status_code == 200
    r = client.post("/upload", files={"file": ("p.jpg", b"\xff\xd8\xff\xe0" + b"0" * 32, "image/jpeg")})
    assert r.status_code == 200 and r.json()["snapshot_id"].startswith("snap_")


def test_status_shape(client):
    s = client.get("/api/status").json()
    assert s["ok"] is True and s["version"]
    assert s["camera"]["connected"] is False  # probe disabled in tests
    assert s["camera"]["streamUrl"] == "/api/camera/stream" and s["camera"]["streamType"] == "mjpeg"
    assert s["reading"]["eventsToday"] == 0
    assert s["ai"]["available"] is True and s["ai"]["model"] == (os.environ.get("SV_TUTOR_MODEL") or os.environ.get("SV_MODEL") or "claude-sonnet-5-5")


def test_three_megabyte_json_body_is_accepted(client):
    """No 413: a 3 MB body reaches the handler (it is rejected as 'not an image', which proves it was parsed)."""
    blob = base64.b64encode(os.urandom(3 * 1024 * 1024)).decode("ascii")
    r = client.post("/api/camera/analyze", json={"image": {"source": "webcam", "base64": blob}})
    assert r.status_code == 400
    assert "JPEG" in r.json()["error"]


def test_bad_json_gives_error_shape_not_422(client):
    r = client.post("/api/reading", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and "error" in r.json()


def test_unknown_api_route_is_404_only_for_truly_missing_paths(client):
    assert client.get("/api/nope").status_code == 404
