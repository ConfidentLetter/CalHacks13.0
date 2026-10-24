"""POST /api/camera/analyze: both request shapes, verbatim labels, prefilled statuses, graceful failure."""
from __future__ import annotations

import asyncio

from bridge.tests.conftest import TINY_JPEG_B64

PRODUCT_RULE_LINE = "f'(x)=2x\\cdot\\cos x"


def test_webcam_base64_runs_chain_and_judges(client, fake_llm, env):
    r = client.post("/api/camera/analyze", json={"image": {"source": "webcam", "mimeType": "image/jpeg",
                                                           "base64": TINY_JPEG_B64, "width": 1, "height": 1}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["snapshotId"].startswith("snap_") and body["analyzedAt"]
    assert body["summary"] == "Derivative of x^2 sin x: the product rule was not applied."
    assert body["topics"] == ["Derivatives", "Product rule"] and len(body["hints"]) == 1
    steps = body["steps"]
    assert [s["label"] for s in steps] == ["f(x)=x^{2}\\sin x", PRODUCT_RULE_LINE, "=2\\cos x", "f'(0)=2\\cdot 0\\cdot\\cos 0=0"]
    assert steps[1]["status"] == "error" and steps[1]["label"] == PRODUCT_RULE_LINE  # verbatim, judged wrong
    assert steps[2]["status"] == "unclear" and steps[2]["note"] == "crossed out"  # the model's verdict is ignored
    assert steps[0]["status"] == "unclear"
    # the still landed under runtime/uploads and the judge saw the verbatim lines, nothing rewritten
    from bridge import images

    assert any(p.suffix == ".jpg" for p in images.UPLOAD_DIR.iterdir())
    judge_call = next(c for c in fake_llm if c["stage"] == "bridge.judge")
    assert PRODUCT_RULE_LINE in judge_call["messages"][-1]["content"]
    assert "never rewrite" in judge_call["system"].lower()


def test_data_url_prefix_accepted(client):
    r = client.post("/api/camera/analyze", json={"image": {"source": "webcam", "base64": "data:image/jpeg;base64," + TINY_JPEG_B64}})
    assert r.status_code == 200 and len(r.json()["steps"]) == 4


def test_hardware_snapshot_id_path(client, fake_camera):
    snap = client.post("/api/camera/capture").json()
    r = client.post("/api/camera/analyze", json={"image": {"source": "hardware", "snapshotId": snap["id"]}})
    assert r.status_code == 200 and r.json()["stillId"] == snap["id"]


def test_unknown_snapshot_id_is_400_not_404(client):
    r = client.post("/api/camera/analyze", json={"image": {"source": "hardware", "snapshotId": "snap_nope"}})
    assert r.status_code == 400 and "unknown snapshotId" in r.json()["error"]


def test_missing_image_is_400(client):
    assert client.post("/api/camera/analyze", json={}).status_code == 400
    assert client.post("/api/camera/analyze", json={"image": {"source": "webcam", "base64": "@@@"}}).status_code == 400


def test_pipeline_failure_returns_200_with_failed_summary(client, monkeypatch):
    from app import server as vision_server

    async def boom(path, source="upload"):
        raise RuntimeError("camera exploded")

    monkeypatch.setattr(vision_server, "analyze", boom)
    r = client.post("/api/camera/analyze", json={"image": {"source": "webcam", "base64": TINY_JPEG_B64}})
    assert r.status_code == 200
    body = r.json()
    assert body["analysisFailed"] is True and body["steps"] == [] and "Analysis failed" in body["summary"]


def test_pipeline_timeout_returns_200(client, monkeypatch):
    from app import server as vision_server

    from bridge import analyze

    async def slow(path, source="upload"):
        await asyncio.sleep(5)

    monkeypatch.setattr(vision_server, "analyze", slow)
    monkeypatch.setattr(analyze, "DEFAULT_PIPELINE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(analyze, "DEFAULT_TOTAL_BUDGET_S", 9.0)
    r = client.post("/api/camera/analyze", json={"image": {"source": "webcam", "base64": TINY_JPEG_B64}})
    assert r.status_code == 200 and "longer than" in r.json()["summary"]


def test_judge_failure_keeps_verbatim_lines_unjudged(client, monkeypatch):
    from bridge import llm

    def fail(*a, **k):
        raise llm.LLMError("no key")

    monkeypatch.setattr(llm, "ask_json", fail)
    r = client.post("/api/camera/analyze", json={"image": {"source": "webcam", "base64": TINY_JPEG_B64}})
    body = r.json()
    assert r.status_code == 200 and body["analysisFailed"] is True
    assert [s["label"] for s in body["steps"]][1] == PRODUCT_RULE_LINE
    assert all(s["status"] == "unclear" for s in body["steps"])


def test_stored_twin_validates_schema_after_analyze(client):
    from app import pipeline, store

    client.post("/api/camera/analyze", json={"image": {"source": "webcam", "base64": TINY_JPEG_B64}})
    twin = store.latest()
    assert twin is not None and pipeline.validate(twin) == []


def test_steps_carry_recognition_fields_for_the_inspector(client):
    """H+9 relay (T6 UI): bbox, cropUrl, contextCropUrl, readings{page,line,reread,agree}, uncertainSpans, imageSize."""
    r = client.post("/api/camera/analyze", json={"image": {"source": "webcam", "base64": TINY_JPEG_B64}})
    body = r.json()
    assert body["imageSize"] == {"width": 1700, "height": 2200}
    step = body["steps"][1]
    assert step["bbox"] == [130.0, 320.0, 1100.0, 110.0]
    assert set(step["readings"]) >= {"page", "line", "reread", "agree"} and isinstance(step["readings"]["agree"], bool)
    assert step["readings"]["line"] == PRODUCT_RULE_LINE  # mock twin has no two-pass readings: line = final latex
    assert step["cropUrl"] is None and step["contextCropUrl"] is None  # mock has no crops
    assert body["steps"][2]["uncertainSpans"] == [{"start": 1, "end": 2, "alternatives": ["2", "z"]}]
    # T6 falls back to T4's /twin/{snapshotId} for the full twin: the id we return must resolve there
    twin = client.get(f"/twin/{body['snapshotId']}")
    assert twin.status_code == 200 and twin.json()["snapshot_id"] == body["snapshotId"]


def test_readings_from_a_two_pass_line():
    from bridge import tutor

    line = {"id": "L1", "order": 1, "latex": "a+b", "text": "a + b", "status": "active", "confidence": 0.9,
            "bbox": [1, 2, 3, 4], "crop_path": "runtime/crops/x/line_001.png", "context_crop_path": "runtime/crops/x/line_001_ctx.png",
            "readings": {"line": {"latex": "a+b", "text": "a + b"}, "page": {"latex": "a+b", "text": "a+b"}, "reread": None, "notes": []}}
    step = tutor.step_base(tutor.twin_lines({"lines": [line]})[0])
    assert step["readings"] == {"page": "a+b", "line": "a+b", "reread": None, "agree": True, "notes": []}
    assert step["cropUrl"] == "/files/runtime/crops/x/line_001.png" and step["contextCropUrl"].endswith("_ctx.png")
    disagree = {**line, "readings": {"line": {"latex": "a+b"}, "page": {"latex": "a-b"}, "reread": {"latex": "a+b"}, "notes": ["disagree"]}}
    step2 = tutor.step_base(tutor.twin_lines({"lines": [disagree]})[0])
    assert step2["readings"]["agree"] is False and step2["readings"]["reread"] == "a+b" and step2["readings"]["page"] == "a-b"
