"""Reading memory: upsert, history order, delete, bulk clear, screenshots, eventsToday."""
from __future__ import annotations

from bridge.tests.conftest import TINY_JPEG_B64

REC = {"id": "ext-lq2x8f-a1b2c3", "title": "Projectile motion — Wikipedia", "url": "https://en.wikipedia.org/wiki/Projectile_motion",
       "domain": "en.wikipedia.org", "startedAt": "2026-10-24T03:00:00Z", "timestamp": "2026-10-24T03:00:31Z",
       "durationSec": 412, "source": "extension", "text": "A projectile is..."}


def test_upsert_returns_record_and_updates_by_id(client):
    r = client.post("/api/reading", json=REC)
    assert r.status_code == 200 and r.json()["id"] == REC["id"] and r.json()["durationSec"] == 412
    r2 = client.post("/api/reading", json={**REC, "durationSec": 500, "timestamp": "2026-10-24T03:02:00Z"})
    assert r2.json()["durationSec"] == 500
    items = client.get("/api/reading/history").json()["items"]
    assert len(items) == 1 and items[0]["durationSec"] == 500 and items[0]["excerpt"] == "A projectile is..."


def test_history_newest_first_and_limit(client):
    for i in range(5):
        client.post("/api/reading", json={"id": f"r{i}", "url": f"https://x.test/{i}", "timestamp": f"2026-10-24T0{i}:00:00Z"})
    items = client.get("/api/reading/history?limit=3").json()["items"]
    assert [r["id"] for r in items] == ["r4", "r3", "r2"]
    assert items[0]["title"] == "https://x.test/4"  # title falls back to url


def test_delete_and_unknown_delete_are_200(client):
    client.post("/api/reading", json=REC)
    assert client.delete(f"/api/reading/{REC['id']}").json() == {"deleted": REC["id"]}
    assert client.delete("/api/reading/does-not-exist").status_code == 200
    assert client.get("/api/reading/history").json()["items"] == []


def test_bulk_clear_route_is_not_shadowed_by_id_route(client):
    client.post("/api/reading", json=REC)
    r = client.delete("/api/reading/history")
    assert r.status_code == 200 and r.json()["count"] == 1
    assert client.get("/api/reading/history").json()["items"] == []


def test_invalid_record_is_400(client):
    assert client.post("/api/reading", json={"title": "no id"}).status_code == 400
    assert client.post("/api/reading", json=[1, 2]).status_code == 400


def test_screenshot_saved_with_sidecar(client, env):
    shot = {"id": "shot-lq2x8f-ab12", "sessionId": REC["id"], "url": REC["url"], "title": "Week 4", "capturedAt": "2026-10-24T03:10:00Z",
            "mimeType": "image/jpeg", "width": 1, "height": 1, "imageBase64": TINY_JPEG_B64}
    r = client.post("/api/reading/screenshot", json=shot)
    assert r.status_code == 200 and r.json()["stored"] == shot["id"]
    assert (env / "reading" / "shots" / "shot-lq2x8f-ab12.jpg").exists()
    assert (env / "reading" / "shots" / "shot-lq2x8f-ab12.json").exists()
    assert client.post("/api/reading/screenshot", json={"id": "x"}).status_code == 400


def test_events_today_counts_only_today(client):
    from bridge.compat import now_iso

    client.post("/api/reading", json={"id": "old", "url": "https://a.test", "timestamp": "2020-01-01T00:00:00Z"})
    client.post("/api/reading", json={"id": "new", "url": "https://b.test", "timestamp": now_iso()})
    assert client.get("/api/status").json()["reading"]["eventsToday"] == 1
