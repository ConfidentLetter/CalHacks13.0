"""Uploaded PDF screenshots reach Claude as real image content blocks, never as metadata only."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from bridge.tests.conftest import TINY_JPEG_B64


def _shot(client, shot_id, *, page=None, doc="doc-ch15", age_h=0.0):
    captured = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat()
    body = {"id": shot_id, "kind": "pdf", "title": "ch15_final.pdf", "url": "https://canvas.edu/files/ch15_final.pdf",
            "documentId": doc, "pageNumber": page, "capturedAt": captured, "mimeType": "image/jpeg",
            "imageBase64": TINY_JPEG_B64}
    assert client.post("/api/reading/screenshot", json=body).status_code == 200


def _last_user_content(fake_llm):
    return fake_llm[-1]["messages"][-1]["content"]


def test_chat_attaches_uploaded_screenshot_as_image_block(client, fake_llm):
    _shot(client, "pdf-a", page=30)
    r = client.post("/api/chat", json={"message": "Explain the PDF page I'm reading"})
    assert r.status_code == 200
    content = _last_user_content(fake_llm)
    images = [b for b in content if b["type"] == "image"]
    assert len(images) == 1
    src = images[0]["source"]
    assert src["type"] == "base64" and src["media_type"] == "image/jpeg"
    assert base64.b64decode(src["data"])[:2] == b"\xff\xd8"  # real JPEG bytes, not a path or filename
    assert any("SCREENSHOT 1" in b.get("text", "") and "page 30" in b.get("text", "") for b in content)
    assert any(s["type"] == "screenshot" and s["id"] == "pdf-a" for s in r.json()["sources"])


def test_tutor_message_endpoint_also_sends_images(client, fake_llm):
    _shot(client, "pdf-b")
    r = client.post("/api/tutor/message", data={"message": "Quiz me on chapter 15", "sessionId": "s1"})
    assert r.status_code == 200
    assert any(b["type"] == "image" for b in _last_user_content(fake_llm))


def test_no_screenshots_says_so_and_sends_no_image(client, fake_llm):
    r = client.post("/api/chat", json={"message": "Explain the PDF page I'm reading"})
    assert r.status_code == 200
    content = _last_user_content(fake_llm)
    assert isinstance(content, str) and "PDF SCREENSHOTS: none available" in content
    assert not any(s["type"] == "screenshot" for s in r.json()["sources"])


def test_selection_limits_count_prefers_latest_document_and_named_page(client, fake_llm):
    from bridge import tutor

    _shot(client, "old-doc", doc="doc-other", age_h=0.5)
    for i, page in enumerate([1, 2, 3, 31, 5]):
        _shot(client, f"p{i}", page=page)
    r = client.post("/api/chat", json={"message": "what is on page 31?"})
    texts = [b["text"] for b in _last_user_content(fake_llm) if b["type"] == "text"]
    assert sum(b["type"] == "image" for b in _last_user_content(fake_llm)) == tutor.MAX_SCREENSHOTS
    assert "page 31" in texts[1]  # the named page is SCREENSHOT 1
    used = [s["id"] for s in r.json()["sources"] if s["type"] == "screenshot"]
    assert len(used) == tutor.MAX_SCREENSHOTS and "old-doc" not in used


def test_stale_and_unreadable_screenshots_are_not_sent(client, fake_llm, env):
    _shot(client, "stale", age_h=48)
    _shot(client, "broken")
    (env / "reading" / "shots" / "broken.jpg").write_bytes(b"not an image")
    client.post("/api/chat", json={"message": "Explain the PDF"})
    assert isinstance(_last_user_content(fake_llm), str)  # nothing usable → honest "none available"


def test_model_failure_is_surfaced_not_claimed(client, monkeypatch):
    from bridge import llm

    def fail(*a, **k):
        raise llm.LLMError("model call failed: APIStatusError")

    monkeypatch.setattr(llm, "ask_json", fail)
    _shot(client, "pdf-c")
    r = client.post("/api/chat", json={"message": "Explain the PDF"})
    assert r.status_code == 502 and "Pip could not answer" in r.json()["error"]


def test_screenshot_list_returns_metadata_without_bytes_or_paths(client):
    _shot(client, "pdf-d", page=7)
    items = client.get("/api/reading/screenshots").json()["items"]
    assert items[0]["id"] == "pdf-d" and items[0]["pageNumber"] == 7
    assert "imageBase64" not in items[0] and "path" not in items[0]
