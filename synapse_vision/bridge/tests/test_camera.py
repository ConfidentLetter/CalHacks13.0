"""Camera endpoints with a synthetic frame source: latest, capture, MJPEG stream, probe caching."""
from __future__ import annotations

from bridge import camera


def test_latest_is_null_200_when_nothing(client):
    r = client.get("/api/camera/latest")
    assert r.status_code == 200 and r.json() is None


def test_capture_then_latest(client, fake_camera):
    snap = client.post("/api/camera/capture").json()
    assert snap["id"].startswith("still_") and snap["imageUrl"].startswith("/files/runtime/") and snap["capturedAt"]
    assert snap["deviceId"] == "webcam"
    latest = client.get("/api/camera/latest").json()
    assert latest["id"] == snap["id"]
    # the still is served by T4's /files route through the same process
    assert client.get(snap["imageUrl"]).status_code == 200


def test_latest_fresh_takes_new_still(client, fake_camera):
    a = client.get("/api/camera/latest?fresh=true").json()
    b = client.get("/api/camera/latest?fresh=true").json()
    assert a["id"] != b["id"]


def test_capture_without_camera_is_503_with_error(client, monkeypatch):
    def no_cam(source=None):
        raise camera.CameraError("webcam index 2 could not be opened")

    monkeypatch.setattr(camera, "take_still", no_cam)
    r = client.post("/api/camera/capture")
    assert r.status_code == 503 and "camera not available" in r.json()["error"]


def test_mjpeg_stream_delivers_frames(client, fake_camera):
    with client.stream("GET", "/api/camera/stream?max_frames=2") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("multipart/x-mixed-replace; boundary=frame")
        body = b"".join(r.iter_bytes())
    assert body.count(b"--frame\r\nContent-Type: image/jpeg") == 2
    assert b"\xff\xd8" in body  # JPEG SOI marker present
    assert camera.grabber.clients == 0


def test_stream_installs_frame_provider_for_t4_snapshot(client, fake_camera):
    from app import pipeline

    with client.stream("GET", "/api/camera/stream?max_frames=1") as r:
        b"".join(r.iter_bytes())
    assert camera.grabber.running  # stays alive for the idle window
    assert pipeline._frame_provider is not None
    camera.grabber.stop()
    assert pipeline._frame_provider is None


def test_probe_is_cached(env, monkeypatch):
    calls = []

    def once():
        calls.append(1)
        return True, "fake"

    monkeypatch.setattr(camera, "_probe_once", once)
    monkeypatch.setattr(camera, "_probe", {"at": 0.0, "value": False, "detail": ""})
    assert camera.probe_camera() is True
    assert camera.probe_camera() is True
    assert len(calls) == 1
    assert camera.probe_camera(force=True) is True and len(calls) == 2
