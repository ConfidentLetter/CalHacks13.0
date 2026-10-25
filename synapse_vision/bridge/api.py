"""The frontend contract: APIRouter(prefix="/api"). Shapes follow ../docs/BACKEND_INTEGRATION.md and
BACKEND_CONTRACT.md. Every handler is guarded: errors become `{"error": ...}` with a proper status, timed as
`bridge.<endpoint>`. Only /api/tutor/voice may answer 501 (the UI shows "not built yet" for 404/405/501).
"""
from __future__ import annotations

import asyncio
import functools
import os
import time
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from bridge import analyze, camera, images, llm, stt, tutor
from bridge.compat import cfg, error_body, log, now_iso
from bridge.store import default_store, history_item

VERSION = "0.1.0"
router = APIRouter(prefix="/api")
STREAM_FIRST_FRAME_S = 8.0
DEFAULT_CHAT_BUDGET_S = 85.0        # UI gives up at 90 s
DEFAULT_TUTOR_BUDGET_S = 42.0       # UI gives up at 45 s
DEFAULT_TUTOR_PIPELINE_S = 25.0
_stt_warmed = {"done": False}


# ---------------------------------------------------------------------- plumbing

def guarded(name: str) -> Callable:
    """Time the handler as bridge.<name>; map exceptions to {"error"} responses; never let the server die."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any):
            t0 = time.perf_counter()
            status = 200
            try:
                resp = await fn(*args, **kwargs)
                status = getattr(resp, "status_code", 200)
                return resp
            except (analyze.ResolveError, images.ImageError, ValueError) as exc:
                status = 400
                return JSONResponse(error_body(str(exc)), 400)
            except camera.CameraError as exc:
                status = 503
                return JSONResponse(error_body(f"camera not available: {exc}"), 503)
            except Exception as exc:  # noqa: BLE001 - last line of defence
                status = 500
                log(f"bridge.{name}.error", 0.0, error=f"{type(exc).__name__}: {exc}")
                return JSONResponse(error_body(f"{type(exc).__name__}: {exc}"), 500)
            finally:
                log(f"bridge.{name}", (time.perf_counter() - t0) * 1000.0, status=status)
        return wrapper
    return deco


async def _json_body(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    import json

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"body is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")
    return data


def _latest_real_twin() -> dict | None:
    """The latest stored twin, ignoring T4's 'no real twin yet' mock fallback."""
    try:
        from app import bridge_api

        twin = bridge_api.latest_twin()
    except Exception:  # noqa: BLE001
        return None
    if twin and "no real twin yet" in str(twin.get("_fallback") or ""):
        return None
    return twin


# ---------------------------------------------------------------------- status

@router.get("/status")
@guarded("status")
async def status():
    if not _stt_warmed["done"]:
        _stt_warmed["done"] = True
        stt.warm()
    connected = await asyncio.to_thread(camera.probe_camera)
    return {
        "ok": True, "version": VERSION,
        "camera": {"connected": connected, "streamUrl": "/api/camera/stream", "streamType": "mjpeg",
                   "source": camera.source_name(), "device": camera.source_device(),
                   "label": camera.KIND_LABELS.get(camera.source_name(), camera.source_name()),
                   "detail": camera.probe_detail()},
        "reading": {"eventsToday": default_store().count_today()},
        "ai": {"available": llm.available(), "model": llm.model_name()},
        "voice": stt.status(),
        "vision": {"mock": os.environ.get("SV_MOCK", "").strip() not in ("", "0", "false", "no"),
                   "latestSnapshotId": (_latest_real_twin() or {}).get("snapshot_id")},
    }


# ---------------------------------------------------------------------- camera

@router.get("/camera/stream")
@guarded("camera_stream")
async def camera_stream(max_frames: int | None = None):
    if camera.grabber.reader is None:
        camera.frame_reader()  # raises CameraError → 503 when the configured source is not a live camera
    camera.grabber.attach()

    async def gen():
        seq, sent, started = 0, 0, time.monotonic()
        try:
            while True:
                jpeg, new_seq = await asyncio.to_thread(camera.grabber.wait_frame, seq, 1.0)
                if new_seq > seq and jpeg:
                    seq = new_seq
                    sent += 1
                    yield camera.mjpeg_part(jpeg)
                    if max_frames and sent >= max_frames:
                        break
                elif sent == 0 and time.monotonic() - started > STREAM_FIRST_FRAME_S:
                    break  # no frame at all: close so the UI shows its retry button
                elif not camera.grabber.running and sent:
                    break
        finally:
            camera.grabber.detach()

    return StreamingResponse(gen(), media_type=f"multipart/x-mixed-replace; boundary={camera.BOUNDARY}",
                             headers={"Cache-Control": "no-store"})


def _snapshot_payload(fresh: bool) -> dict | None:
    if fresh:
        path, source = camera.take_still()
        return images.register_still(images.new_id("still"), path, source)
    still = images.latest_still()
    twin_obj = images.snapshot_from_twin(_latest_real_twin())
    if still and twin_obj and str(twin_obj.get("capturedAt") or "") > str(still.get("capturedAt") or ""):
        return twin_obj
    if still:
        return images.snapshot_object(still)
    if twin_obj:
        return twin_obj
    newest = camera.latest_snapshot_file()
    if newest:
        from pathlib import Path

        return {"id": f"file_{Path(newest).stem}", "imageUrl": images.file_url(newest),
                "capturedAt": camera.file_mtime_iso(newest), "deviceId": camera.source_name()}
    return None


@router.get("/camera/latest")
@guarded("camera_latest")
async def camera_latest(fresh: bool = False):
    payload = await asyncio.to_thread(_snapshot_payload, fresh)
    return JSONResponse(payload, 200)  # `null` with 200 when there is nothing yet (contract)


@router.post("/camera/capture")
@guarded("camera_capture")
async def camera_capture():
    return await asyncio.to_thread(_snapshot_payload, True)


@router.post("/camera/analyze")
@guarded("camera_analyze")
async def camera_analyze(request: Request):
    body = await _json_body(request)
    return await analyze.analyze_request(body)


# ---------------------------------------------------------------------- reading memory

@router.post("/reading")
@guarded("reading_upsert")
async def reading_upsert(request: Request):
    record = default_store().upsert(await _json_body(request))
    return record


@router.post("/reading/screenshot")
@guarded("reading_screenshot")
async def reading_screenshot(request: Request):
    rec = await asyncio.to_thread(default_store().save_screenshot, await _json_body(request))
    return {"stored": rec["id"], "sessionId": rec.get("sessionId"), "bytes": rec["bytes"]}


@router.get("/reading/screenshots")
@guarded("reading_screenshots")
async def reading_screenshots(limit: int = 20):
    """Metadata of stored screenshots (no image bytes, no local paths)."""
    items = await asyncio.to_thread(default_store().list_screenshots, None, max(1, min(int(limit), 100)))
    return {"items": [{k: v for k, v in s.items() if k != "path"} for s in items]}


@router.get("/reading/history")
@guarded("reading_history")
async def reading_history(limit: int = 100):
    return {"items": [history_item(r) for r in default_store().list(limit=max(1, min(int(limit), 1000)))]}


@router.delete("/reading/history")  # before /reading/{id}: otherwise "history" would be taken as an id
@guarded("reading_clear")
async def reading_clear():
    return {"cleared": True, "count": default_store().clear()}


@router.delete("/reading/{record_id}")
@guarded("reading_delete")
async def reading_delete(record_id: str):
    default_store().delete(record_id)  # 200 even when unknown (contract)
    return {"deleted": record_id}


# ---------------------------------------------------------------------- chat / tutor brain

async def _twin_for_question(image: Any, *, pipeline_timeout_s: float, include_notebook: bool) -> tuple[dict | None, list[str]]:
    """Twin to reason about: analyse the attached still if any, else the latest stored twin."""
    notes: list[str] = []
    if image:
        still = await asyncio.to_thread(analyze.resolve_image, image)
        twin = still.get("twin")
        if twin is None:
            twin, error = await analyze.run_pipeline(still["path"], still["source"], pipeline_timeout_s)
        if twin is not None:
            return twin, notes
        notes.append(f"NOTE: the photo attached to this question could not be analysed ({error}); "
                     "the notebook context below is the last analysed page, if any.")
    if not include_notebook:
        return None, notes
    return _latest_real_twin(), notes


def _readings(include: bool) -> list[dict]:
    return default_store().list(limit=tutor.MAX_READING_ITEMS) if include else []


def _screenshots(include: bool) -> list[dict]:
    return default_store().recent_screenshots(tutor.SCREENSHOT_MAX_AGE_H) if include else []


@router.post("/chat")
@guarded("chat")
async def chat(request: Request):
    body = await _json_body(request)
    message = str(body.get("message") or "").strip()
    if not message:
        raise ValueError("'message' is required")
    t0 = time.perf_counter()
    budget = float(cfg("bridge.chat_budget_s", DEFAULT_CHAT_BUDGET_S))
    include_notebook = bool(body.get("includeNotebook", True))
    twin, notes = await _twin_for_question(body.get("image"), pipeline_timeout_s=min(45.0, budget - 30),
                                           include_notebook=include_notebook)
    if not include_notebook and not body.get("image"):
        twin = None
    readings = _readings(bool(body.get("includeReading", True)))
    include_text = bool(body.get("includeReadingText", False))
    shots = _screenshots(bool(body.get("includeReading", True)))
    remaining = max(10.0, budget - (time.perf_counter() - t0))
    try:
        out = await asyncio.wait_for(asyncio.to_thread(
            tutor.respond, message, body.get("history"), twin=twin, readings=readings, include_text=include_text,
            context_notes=notes, timeout_s=min(remaining - 2, 60.0), screenshots=shots), timeout=remaining)
    except (llm.LLMError, asyncio.TimeoutError) as exc:
        return JSONResponse(error_body(f"Pip could not answer: {exc if str(exc) else 'timed out'}"), 502)
    return {"reply": out["reply"], "petExpression": out["petExpression"],
            "sources": tutor.sources_for(twin, readings, out["screenshotsUsed"])}


async def _form(request: Request) -> dict:
    form = await request.form()
    out: dict[str, Any] = {}
    for key in form.keys():
        out[key] = form.get(key)
    return out


async def _file_bytes(value: Any) -> bytes | None:
    if value is None or isinstance(value, str):
        return None
    data = await value.read()
    return data or None


async def _tutor_turn(fields: dict, message: str, *, transcript: str | None) -> Any:
    request_id = str(fields.get("requestId") or "")
    session_id = str(fields.get("sessionId") or "")
    t0 = time.perf_counter()
    budget = float(cfg("bridge.tutor_budget_s", DEFAULT_TUTOR_BUDGET_S))
    image_bytes = await _file_bytes(fields.get("image"))
    image = None
    if image_bytes:
        import base64

        image = {"source": "webcam", "base64": base64.b64encode(image_bytes).decode("ascii"),
                 "capturedAt": fields.get("imageCapturedAt")}
    twin, notes = await _twin_for_question(image, pipeline_timeout_s=float(cfg("bridge.tutor_pipeline_timeout_s", DEFAULT_TUTOR_PIPELINE_S)),
                                           include_notebook=True)
    readings = _readings(True)
    shots = _screenshots(True)
    remaining = max(8.0, budget - (time.perf_counter() - t0))
    try:
        out = await asyncio.wait_for(asyncio.to_thread(
            tutor.respond, message, tutor.sessions.history(session_id), twin=twin, readings=readings,
            include_text=False, context_notes=notes, timeout_s=min(remaining - 1, 40.0), screenshots=shots),
            timeout=remaining)
    except (llm.LLMError, asyncio.TimeoutError) as exc:
        return JSONResponse({**error_body(f"Pip could not answer: {exc if str(exc) else 'timed out'}"),
                             "requestId": request_id}, 502)
    tutor.sessions.record(session_id, message, out["reply"])
    return {"requestId": request_id, "transcript": transcript, "replyText": out["reply"], "replyAudioUrl": None,
            "petExpression": out["petExpression"], "sources": tutor.sources_for(twin, readings, out["screenshotsUsed"])}


@router.post("/tutor/message")
@guarded("tutor_message")
async def tutor_message(request: Request):
    fields = await _form(request)
    message = str(fields.get("message") or "").strip()
    if not message:
        raise ValueError("'message' is required")
    return await _tutor_turn(fields, message, transcript=message)


@router.post("/tutor/voice")
@guarded("tutor_voice")
async def tutor_voice(request: Request):
    if not stt.available():
        return JSONResponse(error_body("voice not built yet"), 501)
    fields = await _form(request)
    audio = await _file_bytes(fields.get("audio"))
    if not audio:
        raise ValueError("'audio' file is required")
    upload = fields.get("audio")
    filename = getattr(upload, "filename", None)
    try:
        transcript = await asyncio.wait_for(asyncio.to_thread(stt.transcribe, audio, str(fields.get("audioMimeType") or ""), filename),
                                            timeout=float(cfg("bridge.stt_timeout_s", 20.0)))
    except (stt.STTError, asyncio.TimeoutError) as exc:
        return JSONResponse({**error_body(f"could not understand the recording: {exc if str(exc) else 'timed out'}"),
                             "requestId": str(fields.get("requestId") or "")}, 502)
    if not transcript.strip():
        return JSONResponse({**error_body("I didn't catch any words in that recording. Try again a bit closer to the mic."),
                             "requestId": str(fields.get("requestId") or "")}, 422)
    return await _tutor_turn(fields, transcript, transcript=transcript)


@router.get("/debug")
@guarded("debug")
async def debug():
    """Bridge internals for the operator (not part of the frontend contract)."""
    return {"time": now_iso(), "grabber": {"running": camera.grabber.running, "clients": camera.grabber.clients,
                                           "lastError": camera.grabber.last_error},
            "stills": images.latest_still(), "stt": stt.status(), "model": llm.model_name(), "aiAvailable": llm.available()}
