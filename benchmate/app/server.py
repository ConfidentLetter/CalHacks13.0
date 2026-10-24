"""FastAPI server (T5, Step 4).  Run:  uvicorn app.server:app --port 8000

Routes (contracts/interfaces.md): GET / · GET /stream (MJPEG) · GET /frame.jpg · POST /read · WS /ws
Extra, T5-internal: GET /api/state · GET /api/telemetry · GET /api/profiles · GET /healthz

Rules that keep the demo alive:
- Nothing heavy runs on the event loop. Pipeline work goes to a thread pool; the MJPEG generator
  only copies the camera's already-encoded JPEG bytes.
- Every handler is wrapped: an error becomes a {"type":"status","stage":..,"error":..} message.
- BM_MOCK=1: no camera, no board. UI keys 1/2/3 load the mock scenarios; works offline.
"""
import asyncio
import json
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app import capture, modules, serial_bridge, telemetry
from app.pipeline import Pipeline

STATIC = Path(__file__).parent / "static"
STREAM_FPS = 10
LOOP_POLL_S = 0.1

MOCK = os.environ.get("BM_MOCK") == "1"
if MOCK:
    os.environ.setdefault("BM_NO_CAMERA", "1")
    os.environ.setdefault("BM_SERIAL_REPLAY", modules.mock_serial_path("ok"))


def json_safe(obj):
    """Browsers reject Infinity/NaN, which Python's json.dumps happily emits. Replace them with None."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- broadcaster
class Broadcaster:
    """Thread-safe fan-out to all WebSocket clients. emit() may be called from any thread."""

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.queue: Optional[asyncio.Queue] = None
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop, self.queue = loop, asyncio.Queue(maxsize=2000)

    def emit(self, msg: dict) -> None:
        if self.loop is None or self.queue is None or self.loop.is_closed():
            return
        try:
            self.loop.call_soon_threadsafe(self._put, msg)
        except RuntimeError:  # loop shutting down
            pass

    def _put(self, msg: dict) -> None:
        if self.queue.full():
            self.queue.get_nowait()  # drop oldest rather than block the pipeline
        self.queue.put_nowait(msg)

    async def pump(self) -> None:
        while True:
            msg = await self.queue.get()
            data = json.dumps(json_safe(msg), default=str)
            with self._lock:
                clients = list(self.clients)
            for ws in clients:
                try:
                    await ws.send_text(data)
                except Exception:
                    self.discard(ws)

    def add(self, ws: WebSocket) -> None:
        with self._lock:
            self.clients.add(ws)

    def discard(self, ws: WebSocket) -> None:
        with self._lock:
            self.clients.discard(ws)


broadcaster = Broadcaster()
pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pipeline")
pipeline = Pipeline(emit=broadcaster.emit, capture=capture, serial=serial_bridge, mock=MOCK)


def _on_telemetry(record: dict) -> None:
    """Mirror every telemetry record to the UI latency drawer (status messages)."""
    broadcaster.emit({"type": "status", "stage": record.get("stage"), "ms": record.get("ms"),
                      "telemetry": True, **{k: v for k, v in record.items() if k not in ("stage", "ms", "ts")}})


def _on_serial(line: str, ts: float) -> None:
    broadcaster.emit({"type": "serial", "line": line, "ts": ts})


# --------------------------------------------------------------------------- lifespan
async def pipeline_loop() -> None:
    """Background: when the scene changed and settled, run the proactive pipeline."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            if not pipeline.mock and capture.frame_changed():
                loop.run_in_executor(pool, pipeline.run_proactive)
        except Exception as exc:
            pipeline.status("loop", error=f"{type(exc).__name__}: {exc}"[:120])
        await asyncio.sleep(LOOP_POLL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    broadcaster.bind(loop)
    telemetry.add_listener(_on_telemetry)
    serial_bridge.bridge().add_listener(_on_serial)
    if os.environ.get("BM_NO_CAPTURE_THREAD") != "1":
        capture.camera()  # start the camera thread early so /stream has frames
    tasks = [asyncio.create_task(broadcaster.pump()), asyncio.create_task(pipeline_loop())]
    loop.run_in_executor(pool, modules.warmup)
    if pipeline.mock:
        loop.run_in_executor(pool, pipeline.load_scenario, "ok")
    telemetry.log("server_start", 0, mock=pipeline.mock, camera=capture.camera().info if os.environ.get("BM_NO_CAPTURE_THREAD") != "1" else None)
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        telemetry.remove_listener(_on_telemetry)
        serial_bridge.bridge().remove_listener(_on_serial)


app = FastAPI(title="BenchMate", lifespan=lifespan)


# --------------------------------------------------------------------------- HTTP routes
@app.get("/", response_class=HTMLResponse)
async def index():
    path = STATIC / "index.html"
    if not path.exists():
        return HTMLResponse("<h1>BenchMate</h1><p>UI not built yet (app/static/index.html).</p>")
    return FileResponse(path, media_type="text/html")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "mock": pipeline.mock, "camera": capture.camera().info,
            "serial": serial_bridge.bridge().status()}


@app.get("/frame.jpg")
async def frame_jpg():
    jpeg = capture.camera().latest_jpeg()
    if not jpeg:
        raise HTTPException(status_code=503, detail="no frame yet")
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


async def mjpeg_generator():
    cam = capture.camera()
    last = None
    while True:
        jpeg = cam.latest_jpeg()
        if jpeg and jpeg is not last:
            last = jpeg
            yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode()
                   + b"\r\n\r\n" + jpeg + b"\r\n")
        await asyncio.sleep(1 / STREAM_FPS)


@app.get("/stream")
async def stream():
    return StreamingResponse(mjpeg_generator(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


class ReadBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    text: Optional[str] = Field(default=None, max_length=200_000)
    seconds: float = Field(ge=0, le=86400)


@app.post("/read")
async def read(body: ReadBody):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(pool, modules.record_read, body.url, body.text, body.seconds)
    return {"ok": True}


@app.get("/api/state")
async def api_state():
    return JSONResponse(json.loads(json.dumps(pipeline.snapshot(), default=str)))


@app.get("/api/telemetry")
async def api_telemetry(n: int = 200):
    return telemetry.read_recent(max(1, min(n, 2000)))


@app.get("/api/profiles")
async def api_profiles():
    loop = asyncio.get_running_loop()
    profiles = await loop.run_in_executor(pool, modules.list_profiles)
    return [{"part_id": p.get("part_id"), "role": p.get("role"),
             "rows": len((p.get("footprint") or {}).get("rows", []) or [])} for p in profiles]


# --------------------------------------------------------------------------- WebSocket
def _hello() -> dict:
    snap = pipeline.snapshot()
    return {"type": "hello", "mock": pipeline.mock, "scenario": pipeline.scenario,
            "camera": capture.camera().info, "serial": serial_bridge.bridge().status(),
            "twin": snap["twin"], "diagnosis": snap["diagnosis"], "budget_ms": snap["budget_ms"],
            "recent_serial": serial_bridge.get_recent_serial(30)}


def handle_client_message(msg: dict) -> None:
    """Blocking; runs in the pool. Dispatches one client->server message."""
    kind = msg.get("type")
    try:
        if kind == "ask":
            pipeline.ask(str(msg.get("question", "")))
        elif kind == "calibrate":
            corners = msg.get("corners")
            if corners is not None and (len(corners) != 4 or any(len(c) != 2 for c in corners)):
                raise ValueError("corners must be 4 [x, y] points")
            pipeline.calibrate([tuple(map(float, c)) for c in corners] if corners else None)
        elif kind == "register":
            pixel = msg["pixel"]
            if len(pixel) != 2:
                raise ValueError("pixel must be [x, y]")
            pipeline.register(str(msg["part_id"]), int(msg.get("row_index", 0)), (float(pixel[0]), float(pixel[1])))
        elif kind == "confirm":
            pipeline.confirm(str(msg["element_id"]), bool(msg.get("answer")))
        elif kind == "mock":
            pipeline.load_scenario(str(msg.get("scenario", "ok")))
        elif kind == "live":
            pipeline.set_live()
        elif kind == "rerun":
            pipeline.run_proactive()
        elif kind == "markers":
            pipeline.marker_status()
        elif kind == "ping":
            broadcaster.emit({"type": "status", "stage": "pong", "ms": 0})
        else:
            raise ValueError(f"unknown message type {kind!r}")
    except Exception as exc:
        pipeline.status(kind or "message", error=f"{type(exc).__name__}: {exc}"[:160])


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    broadcaster.add(ws)
    loop = asyncio.get_running_loop()
    try:
        await ws.send_text(json.dumps(json_safe(_hello()), default=str))
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise ValueError("message must be a JSON object")
            except ValueError as exc:
                broadcaster.emit({"type": "status", "stage": "message", "error": f"bad JSON: {exc}"[:120]})
                continue
            loop.run_in_executor(pool, handle_client_message, msg)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        telemetry.log("ws_error", 0, error=f"{type(exc).__name__}: {exc}"[:120])
    finally:
        broadcaster.discard(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.server:app", host="0.0.0.0", port=int(os.environ.get("BM_PORT", "8000")), reload=False)
