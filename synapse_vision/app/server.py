"""Synapse Vision hand-off API (FastAPI, port 8000). See app/API.md.

    uvicorn app.server:app --port 8000            # real pipeline
    SV_MOCK=1 uvicorn app.server:app --port 8000  # serve the mock twin only
    python -m app.server --watch                  # start with the watch loop on
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import events, pipeline, store, telemetry
from app.config import get as cfg
from app.pipeline import PipelineError

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
SERVABLE_DIRS = ("runtime", "mocks", "eval")  # image paths in twins live under these

hub = events.Hub()
_pipeline_lock = asyncio.Lock()
_watch: dict[str, Any] = {"on": False, "task": None, "last_error": None, "runs": 0}


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    if os.environ.get("SV_WATCH", "").strip() in ("1", "true", "yes"):
        await set_watch(True)
    yield
    if _watch["on"]:
        await set_watch(False)


app = FastAPI(title="Synapse Vision", version="0.1", lifespan=_lifespan)


# ----------------------------------------------------------------------------- helpers

def _source_name(explicit: str | None = None) -> str:
    src = explicit or os.environ.get("SV_SOURCE") or cfg("capture.source", "webcam")
    return "upload" if str(src).startswith("upload") else str(src)


def _error_payload(stage: str, exc: BaseException) -> dict:
    msg = str(exc) or type(exc).__name__
    return events.status(stage, error=msg, ok=False)


async def _run_pipeline(snapshot_path: str, source: str) -> dict:
    """Build a twin from a snapshot path, store it, broadcast it. Serialised across callers."""
    async with _pipeline_lock:
        t0 = time.perf_counter()
        await hub.broadcast(events.status("pipeline", ok=True, phase="start", snapshot=snapshot_path))
        previous = store.latest()
        twin = await asyncio.to_thread(pipeline.build_twin, snapshot_path, previous, source)
        store.save(twin)
        for msg in events.twin_messages(twin):
            await hub.broadcast(msg)
        ms = (time.perf_counter() - t0) * 1000.0
        await hub.broadcast(events.status("pipeline", ok=True, phase="done", ms=round(ms, 1),
                                          snapshot_id=twin["snapshot_id"], latency_ms=twin.get("latency_ms", {}),
                                          fallback=twin.get("_fallback")))
        _watch["runs"] += 1
        return twin


async def analyze(snapshot_path: str, source: str = "upload") -> dict:
    """Public entry for embedders (T5 bridge): still → twin, stored and broadcast on /events. Raises PipelineError."""
    return await _run_pipeline(snapshot_path, source)


async def _guarded(stage: str, coro):
    """Run a handler body; on failure broadcast a status message and return HTTP 500 instead of dying."""
    try:
        return await coro
    except PipelineError as exc:
        payload = _error_payload(exc.stage, exc)
    except Exception as exc:  # noqa: BLE001 - keep serving no matter what
        payload = _error_payload(stage, exc)
    telemetry.log(f"error.{payload['stage']}", 0, error=payload["error"])
    await hub.broadcast(payload)
    return JSONResponse(payload, status_code=500)


# ----------------------------------------------------------------------------- routes: twins

@app.get("/twin/latest")
async def twin_latest():
    twin = store.latest()
    if twin is None:
        twin = pipeline.mock_twin()
        if pipeline.is_mock():
            store.save(twin)
        else:
            # Real mode before the first snapshot: keep the hand-off alive with the mock, clearly flagged (not stored).
            twin["_fallback"] = "no real twin yet — POST /snapshot or /upload; serving mock"
    return twin


@app.get("/twins")
async def twins():
    return {"snapshot_ids": store.list_ids()}


@app.get("/twin/{snapshot_id}")
async def twin_by_id(snapshot_id: str):
    twin = store.get(snapshot_id)
    if twin is None:
        return JSONResponse(events.status("store", error=f"unknown snapshot_id {snapshot_id}", ok=False), 404)
    return twin


@app.post("/snapshot")
async def snapshot(source: str | None = None):
    async def body():
        src = _source_name(source)
        if pipeline.is_mock():
            src = "mock"
            path = pipeline.mock_twin()["image"]["original_path"]
        else:
            path = await asyncio.to_thread(pipeline.take_snapshot, source)
        return await _run_pipeline(path, src)
    return await _guarded("capture", body())


@app.post("/upload")
async def upload(file: UploadFile | None = File(default=None), image: UploadFile | None = File(default=None)):
    async def body():
        up = file or image
        if up is None:
            raise PipelineError("upload", "multipart field 'file' (or 'image') is required")
        data = await up.read()
        if not data:
            raise PipelineError("upload", "empty upload")
        path = pipeline.save_upload(up.filename or "upload.jpg", data)
        return await _run_pipeline(path, "upload")
    return await _guarded("upload", body())


# ----------------------------------------------------------------------------- routes: watch loop

async def _watch_loop() -> None:
    timeout = float(cfg("capture.stable_seconds", 1.0)) * 10 + 20
    backoff = 1.0
    while _watch["on"]:
        try:
            path = await asyncio.to_thread(pipeline.wait_for_stable, timeout)
        except PipelineError as exc:
            _watch["last_error"] = str(exc)
            await hub.broadcast(_error_payload(exc.stage, exc))
            if "unavailable" in str(exc):  # no capture module: a loop would just spin
                _watch["on"] = False
                await hub.broadcast(events.status("watch", ok=False, on=False, error="watch stopped: capture unavailable"))
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)
            continue
        except asyncio.CancelledError:
            break
        if not path:
            continue
        try:
            await _run_pipeline(path, _source_name())
            backoff = 1.0
        except PipelineError as exc:
            _watch["last_error"] = str(exc)
            await hub.broadcast(_error_payload(exc.stage, exc))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)
        except Exception as exc:  # noqa: BLE001
            _watch["last_error"] = str(exc)
            await hub.broadcast(_error_payload("watch", exc))
            await asyncio.sleep(backoff)
    _watch["task"] = None


def _watch_state() -> dict:
    return {"on": bool(_watch["on"]), "runs": _watch["runs"], "last_error": _watch["last_error"]}


async def set_watch(on: bool) -> dict:
    if on and not _watch["on"]:
        if pipeline.is_mock():
            _watch["last_error"] = "watch is a no-op in SV_MOCK mode; use POST /snapshot"
            await hub.broadcast(events.status("watch", ok=True, on=False, note=_watch["last_error"]))
            return _watch_state()
        _watch["on"] = True
        _watch["last_error"] = None
        _watch["task"] = asyncio.create_task(_watch_loop())
    elif not on and _watch["on"]:
        _watch["on"] = False
        task = _watch["task"]
        if task is not None:
            task.cancel()
    await hub.broadcast(events.status("watch", ok=True, on=_watch["on"]))
    return _watch_state()


@app.get("/watch")
async def watch_get():
    return _watch_state()


@app.post("/watch")
async def watch_post(request: Request):
    body: dict = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - empty body means "toggle"
        body = {}
    on = body.get("on") if isinstance(body, dict) else None
    return await set_watch(not _watch["on"] if on is None else bool(on))


# ----------------------------------------------------------------------------- routes: events / status / viewer

@app.websocket("/events")
async def events_ws(ws: WebSocket):
    await hub.connect(ws)
    try:
        latest = store.latest()
        await ws.send_json({"type": "hello", "mock": pipeline.is_mock(), "watch": _watch_state(),
                            "latest_snapshot_id": latest["snapshot_id"] if latest else None})
        while True:
            await ws.receive_text()  # clients may ping; we ignore content
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        await hub.disconnect(ws)


@app.get("/status")
async def status():
    latest = store.latest()
    return {
        "mock": pipeline.is_mock(),
        "source": _source_name(),
        "model": os.environ.get("SV_MODEL", "claude-sonnet-5-5"),
        "watch": _watch_state(),
        "clients": hub.count,
        "latest_snapshot_id": latest["snapshot_id"] if latest else None,
        "budget_ms": cfg("budget_ms", {}),
        "recent_status": hub.recent[-20:],
    }


@app.get("/telemetry")
async def telemetry_tail(limit: int = 200, stage: str | None = None):
    return {"records": telemetry.read(limit=max(1, min(limit, 5000)), stage=stage)}


@app.get("/files/{path:path}")
async def files(path: str):
    """Serve images referenced by twins (dewarped page, crops). Only under runtime/, mocks/, eval/."""
    target = (ROOT / path).resolve()
    try:
        rel = target.relative_to(ROOT.resolve())
    except ValueError:
        return JSONResponse({"error": "outside repo"}, 403)
    if not rel.parts or rel.parts[0] not in SERVABLE_DIRS:
        return JSONResponse({"error": "not servable"}, 403)
    if not target.is_file():
        return JSONResponse({"error": "not found"}, 404)
    return FileResponse(target)


@app.get("/", response_class=HTMLResponse)
async def index():
    page = STATIC_DIR / "index.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Synapse Vision</h1><p>Viewer not built yet. Try <a href='/twin/latest'>/twin/latest</a>.</p>")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

try:  # Step 4: label helper (eval/label_helper.py) registers /label when present.
    from eval.label_helper import router as _label_router
    app.include_router(_label_router)
except Exception:  # noqa: BLE001 - not written yet or broken; the API keeps working
    pass




def main() -> None:
    import argparse

    import uvicorn

    p = argparse.ArgumentParser(description="Synapse Vision server")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--watch", action="store_true", help="start the stability watch loop immediately")
    p.add_argument("--mock", action="store_true", help="same as SV_MOCK=1")
    a = p.parse_args()
    if a.watch:
        os.environ["SV_WATCH"] = "1"
    if a.mock:
        os.environ["SV_MOCK"] = "1"
    uvicorn.run("app.server:app", host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
