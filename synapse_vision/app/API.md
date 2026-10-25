# StudBud Vision — hand-off API

Base URL: `http://<laptop-ip>:8000` (Henry will tell you the IP). While the camera pipeline is being built the server runs in **mock mode** (`SV_MOCK=1`) and every route returns the mock page twin from `mocks/page_twin_product_rule.json` with fresh ids and timestamps. The shape is final: `contracts/page_twin.schema.json`.

## Routes

| Method | Path | What |
|---|---|---|
| GET | `/twin/latest` | Latest page twin (404 with a status object if none yet) |
| GET | `/twin/{snapshot_id}` | A specific snapshot |
| GET | `/twins` | `{"snapshot_ids":[...]}` oldest → newest |
| POST | `/snapshot` | Capture now, run recognition, return the twin. Optional `?source=pi|webcam` |
| POST | `/upload` | Multipart field `file` (an image) → recognise it, return the twin. Camera-free testing |
| WS | `/events` | Push stream, see below |
| GET/POST | `/watch` | Watch-loop state / toggle (`{"on": true}`; empty body toggles). Auto-snapshots when the scene settles |
| GET | `/status` | Mode, source, watch state, budgets, recent status messages |
| GET | `/telemetry?limit=200` | Tail of `runtime/telemetry.jsonl` |
| GET | `/files/<path>` | Images referenced by a twin (`image.dewarped_path`, line crops) |
| GET | `/` | Viewer |

Errors never take the server down. A failed handler returns HTTP 500 with
`{"type":"status","stage":"capture|transcribe|upload|...","error":"...","ok":false}` and the same object is broadcast on `/events`.

## `/events` (WebSocket)

On connect: `{"type":"hello","mock":true,"watch":{...},"latest_snapshot_id":"..."}`.

After every new snapshot, in this order:
1. `{"type":"status","stage":"pipeline","phase":"start",...}`
2. `{"type":"twin","twin":{...full page twin...}}`
3. one message per changed line, each with the **full line object**:
   `{"type":"line_added"|"line_edited"|"line_crossed_out","snapshot_id":"...","line":{...}}`
   (plus `{"type":"line_removed","line_id":"L7"}` for lines that vanished)
4. `{"type":"status","stage":"pipeline","phase":"done","ms":...,"latency_ms":{...}}`

The server ignores anything you send on the socket (ping if you like).

## Page twin, abridged

```json
{
  "page_id": "page_mock_01", "snapshot_id": "snap_mock_20261024T170000_a1b2c3",
  "captured_at": "2026-10-24T10:00:00-07:00", "source": "mock",
  "image": {"original_path": "...", "dewarped_path": "...", "width": 1700, "height": 2200},
  "quality": {"ok": true, "issues": [], "blur_score": 210.5, "glare_fraction": 0.01},
  "regions": [{"id": "R1", "type": "work", "bbox": [120, 300, 1460, 900]}],
  "lines": [
    {"id": "L1", "region_id": "R1", "order": 1, "bbox": [130, 320, 1100, 110], "status": "active", "kind": "math",
     "latex": "f'(x)=2x\\cdot\\cos x", "text": "f'(x) = 2x · cos x", "confidence": 0.91,
     "uncertain_spans": [], "parse_ok": true, "first_seen": "...", "last_changed": "..."},
    {"id": "L2", "order": 2, "status": "crossed_out", "latex": "=2\\cos x", "confidence": 0.62,
     "uncertain_spans": [{"start": 1, "end": 2, "alternatives": ["2", "z"]}], "...": "..."}
  ],
  "changes": {"added": ["L3"], "edited": [], "removed": [], "crossed_out": ["L2"]},
  "latency_ms": {"capture": 0, "page": 0, "layout": 0, "transcribe": 0, "snapshot_to_twin": 12.3}
}
```

Things to rely on:
- `lines[*].latex` is **verbatim**. The mistake on L1 (`2x·cos x` instead of the product rule) is intentional and must stay. Never "fix" it on your side either.
- `id` is stable across snapshots of the same page; `changes` tells you what moved since the previous twin.
- `status == "crossed_out"` lines are still transcribed; treat them as retracted work.
- `confidence < 0.6` or non-empty `uncertain_spans` → the symbol may be wrong; `alternatives` lists other plausible readings.
- `bbox = [x, y, w, h]` in pixels of `image.dewarped_path` (fetch it at `/files/<dewarped_path>`).
- `_fallback` (present only in mock/fallback situations) says why the twin is not real data.

## Python client (10 lines)

```python
import asyncio, json, websockets, requests   # pip install websockets requests

BASE = "http://LAPTOP_IP:8000"
print(requests.get(f"{BASE}/twin/latest").json()["lines"][0]["latex"])          # pull
twin = requests.post(f"{BASE}/upload", files={"file": open("page.jpg", "rb")}).json()  # push a photo

async def listen():                                                           # push stream
    async with websockets.connect(BASE.replace("http", "ws") + "/events") as ws:
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "twin": print("new twin", msg["twin"]["snapshot_id"], len(msg["twin"]["lines"]), "lines")
            elif msg["type"].startswith("line_"): print(msg["type"], msg["line"]["id"], msg["line"]["latex"])
asyncio.run(listen())
```

## Running it

```bash
source .venv/bin/activate && source env.sh
SV_MOCK=1 uvicorn app.server:app --host 0.0.0.0 --port 8000      # mock
uvicorn app.server:app --host 0.0.0.0 --port 8000                 # real
python -m app.server --watch                                      # real + auto-snapshot on scene settle
```

## Embedding the app (T5 bridge)

`app.server` imports without side effects: no camera is opened, no model is loaded, no port is bound (`pytest app/tests/test_bridge_api.py` checks this). Extend it instead of forking it:

```python
from app.server import app as vision_app, analyze     # analyze(path, source) -> twin; stores + broadcasts on /events
from app import bridge_api, pipeline
bridge_api.latest_twin()        # dict | None — same object as GET /twin/latest
bridge_api.latest_snapshot()    # {snapshot_id, captured_at, source, path, dewarped_path, image_url, quality, line_count, mock}
bridge_api.latest_frame_path()  # newest still under runtime/snapshots/, analysed or not
pipeline.set_frame_provider(fn) # fn() -> image path; then POST /snapshot uses YOUR frames instead of opening the camera
```

Camera ownership: T4's server never keeps the camera open — each `POST /snapshot` calls `capture.get_snapshot`, which opens and releases the device, and the watch loop calls `capture.wait_for_stable` the same way. If the bridge streams MJPEG and holds the device, install a frame provider so `/snapshot` and the watch loop read your latest still instead of fighting for the device.
