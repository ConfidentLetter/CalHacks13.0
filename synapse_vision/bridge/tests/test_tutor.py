"""/api/chat and /api/tutor/*: context gating, sources, requestId echo, voice 501 vs STT path, judge rules."""
from __future__ import annotations

from bridge import tutor
from bridge.tests.conftest import MOCK_TWIN, TINY_JPEG, TINY_JPEG_B64

READING = {"id": "ext-1", "title": "Product rule — Wikipedia", "url": "https://en.wikipedia.org/wiki/Product_rule",
           "source": "extension", "text": "SECRET PAGE TEXT the student did not share"}


def _seed_twin(client):
    client.post("/api/camera/analyze", json={"image": {"source": "webcam", "base64": TINY_JPEG_B64}})


def test_chat_reply_and_sources(client, fake_llm):
    _seed_twin(client)
    client.post("/api/reading", json=READING)
    r = client.post("/api/chat", json={"message": "Did I make a mistake?", "history": [],
                                       "includeNotebook": True, "includeReading": True, "includeReadingText": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"].startswith("Look at your line") and body["petExpression"] == "curious"
    kinds = [s["type"] for s in body["sources"]]
    assert kinds == ["notebook", "reading"]
    assert body["sources"][0]["imageUrl"].startswith("/files/")
    prompt = fake_llm[-1]["messages"][-1]["content"]
    assert "f'(x)=2x\\cdot\\cos x" in prompt and "titles only" in prompt
    assert "SECRET PAGE TEXT" not in prompt  # consent not given


def test_chat_includes_text_only_with_consent(client, fake_llm):
    client.post("/api/reading", json=READING)
    client.post("/api/chat", json={"message": "hi", "includeReadingText": True})
    assert "SECRET PAGE TEXT" in fake_llm[-1]["messages"][-1]["content"]


def test_chat_toggles_off_drop_context(client, fake_llm):
    _seed_twin(client)
    client.post("/api/reading", json=READING)
    r = client.post("/api/chat", json={"message": "hi", "includeNotebook": False, "includeReading": False})
    assert r.json()["sources"] == []
    prompt = fake_llm[-1]["messages"][-1]["content"]
    assert "no readable page available" in prompt and "no recent pages" in prompt


def test_chat_with_image_analyses_it_first(client, fake_llm):
    r = client.post("/api/chat", json={"message": "check this", "image": {"source": "webcam", "base64": TINY_JPEG_B64}})
    assert r.status_code == 200 and r.json()["sources"][0]["type"] == "notebook"


def test_chat_history_is_passed_alternating(client, fake_llm):
    history = [{"role": "assistant", "content": "dropped leading"}, {"role": "user", "content": "a"},
               {"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}]
    client.post("/api/chat", json={"message": "d", "history": history})
    roles = [m["role"] for m in fake_llm[-1]["messages"]]
    assert roles == ["user", "assistant", "user"]


def test_chat_requires_message_and_reports_llm_failure(client, monkeypatch):
    assert client.post("/api/chat", json={}).status_code == 400
    from bridge import llm

    def fail(*a, **k):
        raise llm.LLMError("quota")

    monkeypatch.setattr(llm, "ask_json", fail)
    r = client.post("/api/chat", json={"message": "x"})
    assert r.status_code == 502 and "quota" in r.json()["error"]


def test_tutor_message_echoes_request_id_and_keeps_history(client, fake_llm):
    form = {"message": "Where did I go wrong?", "sessionId": "s-abc", "requestId": "r-1"}
    r = client.post("/api/tutor/message", data=form, files={"image": ("notebook.jpg", TINY_JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requestId"] == "r-1" and body["replyAudioUrl"] is None and body["transcript"] == form["message"]
    assert body["petExpression"] in tutor.PET_EXPRESSIONS and body["replyText"]
    r2 = client.post("/api/tutor/message", data={**form, "requestId": "r-2"})
    assert r2.json()["requestId"] == "r-2"
    roles = [m["role"] for m in fake_llm[-1]["messages"]]
    assert roles[:2] == ["user", "assistant"]  # previous turn remembered per sessionId
    assert client.post("/api/tutor/message", data={"sessionId": "s", "requestId": "r"}).status_code == 400


def test_tutor_voice_501_when_stt_unavailable(client):
    r = client.post("/api/tutor/voice", data={"sessionId": "s", "requestId": "r-9", "audioMimeType": "audio/webm"},
                    files={"audio": ("question.webm", b"\x1aE\xdf\xa3 fake", "audio/webm")})
    assert r.status_code == 501 and r.json() == {"error": "voice not built yet"}


def test_tutor_voice_transcribes_when_stt_available(client, monkeypatch, fake_llm):
    from bridge import stt

    monkeypatch.setattr(stt, "available", lambda: True)
    monkeypatch.setattr(stt, "transcribe", lambda audio, mime=None, filename=None: "where did I go wrong")
    r = client.post("/api/tutor/voice", data={"sessionId": "s", "requestId": "r-9", "audioMimeType": "audio/webm;codecs=opus"},
                    files={"audio": ("question.webm", b"\x1aE\xdf\xa3 fake", "audio/webm")})
    assert r.status_code == 200, r.text
    assert r.json()["transcript"] == "where did I go wrong" and r.json()["requestId"] == "r-9"


# ---------------------------------------------------------------------- judge rules (pure functions)

def test_prefilled_rules_never_reach_the_model(fake_llm, monkeypatch):
    twin = {**MOCK_TWIN, "lines": [dict(l) for l in MOCK_TWIN["lines"]]}
    twin["lines"][3] = {**twin["lines"][3], "confidence": 0.3}
    out = tutor.judge_twin(twin)
    by_id = {s["id"]: s for s in out["steps"]}
    assert by_id["L2"]["status"] == "unclear" and by_id["L2"]["note"] == "crossed out"
    assert by_id["L3"]["status"] == "unclear" and "low transcription confidence" in by_id["L3"]["note"]
    assert by_id["L1"]["status"] == "error" and by_id["L1"]["label"] == "f'(x)=2x\\cdot\\cos x"


def test_empty_twin_has_no_steps_and_no_model_call(fake_llm):
    out = tutor.judge_twin({**MOCK_TWIN, "lines": [], "_error": "no_page"})
    assert out["steps"] == [] and "no_page" in out["summary"] and fake_llm == []


def test_prompts_never_ask_to_correct_the_transcription():
    forbidden = ("correct the latex", "clean up", "the student meant", "fix the line", "rewrite the line")
    for text in (tutor.JUDGE_SYSTEM, tutor.CHAT_SYSTEM):
        low = text.lower()
        assert not any(w in low for w in forbidden), text


def test_hand_held_estimated_positions_reach_the_dashboard():
    """T3's hand-held fallback marks rows as estimated; the step must carry that so the UI draws no boxes."""
    from bridge.tutor import step_base, twin_lines

    twin = {"lines": [
        {"id": "L1", "order": 0, "latex": "x=1", "confidence": 0.4, "bbox": [0, 10, 800, 40], "bbox_estimated": True},
        {"id": "L2", "order": 1, "latex": "y=2", "confidence": 0.9, "bbox": [100, 300, 200, 40]},
    ]}
    steps = [step_base(l) for l in twin_lines(twin)]
    assert [s["bboxEstimated"] for s in steps] == [True, False]
