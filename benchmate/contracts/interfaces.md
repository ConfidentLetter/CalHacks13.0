# Interfaces (frozen — only the integrator changes this file; every change goes in CHANGELOG.md)

All modules live in one Python process started by `app/server.py`. Data crossing module boundaries must validate against the JSON schemas in this folder. Pixel coordinates are always in the ORIGINAL camera frame unless a name says `warped`.

## T5 app/ — capture, serial, telemetry

```python
# app/capture.py
def get_frame(high_res: bool = False) -> str:
    """Path to the latest frame (jpg). high_res=True grabs a fresh full-resolution still."""

def frame_changed(threshold: float = 0.02) -> bool:
    """True once the scene changed AND has been stable again for ~0.8 s (a hand has left the frame)."""

# app/serial_bridge.py
def get_recent_serial(seconds: int = 10) -> list[str]:
    """Recent lines from the microcontroller's serial port, oldest first."""

# app/telemetry.py
def log(stage: str, ms: float, **extra) -> None:
    """Append {ts, stage, ms, **extra} to runtime/telemetry.jsonl."""
```

## T1 perception_geometry/ — board geometry

```python
def calibrate(frame_path: str, corners: list[tuple[float, float]] | None = None) -> list[list[float]]:
    """3x3 homography: original image pixels -> warped board image. corners = 4 clicked points
    (TL, TR, BR, BL); if None, detect ArUco markers ids 0-3. Raises CalibrationError if neither works."""

def pixel_to_hole(x: float, y: float, homography) -> str | None:
    """Original-image pixel -> hole id like 'J15', or rail id 'RAIL_TOP_PLUS' etc. None if off-board."""

def hole_to_pixel(hole: str, homography) -> tuple[float, float]:
    """Inverse of pixel_to_hole: centre of a hole in original-image pixels (T2 uses it to lay out pins)."""

def tile(frame_path: str, homography, max_tiles: int = 6) -> list[dict]:
    """Density-balanced tiles of the board region. Each: {path, bbox:[x,y,w,h]} in original pixels."""

def detect_wires(frame_path: str, homography, exclude_boxes: list[list[float]] | None = None) -> list[dict]:
    """Wires per twin.schema.json. exclude_boxes = component bboxes [x,y,w,h] to mask out (PCBs are colored too)."""

def build_nets(components: list[dict], wires: list[dict]) -> list[dict]:
    """Breadboard connectivity (A-E of a row, F-J of a row, each rail) -> nets per twin.schema.json."""
```

## T2 perception_detect/ — components and the twin

```python
def register(part_id: str, row_index: int, pixel: tuple[float, float]) -> None:
    """Tier A: user clicked the first pin of footprint row `row_index` of `part_id`. Persist to runtime/registrations.json."""

def detect_components(frame_path: str, tiles: list[dict] | None = None) -> list[dict]:
    """Components per twin.schema.json, part_id normalized, pins mapped to holes."""

def normalize_part(label_text: str) -> str | None:
    """'GY-BME280', 'BME 280' -> 'bme280'. None if below match threshold."""

def build_twin(frame_path: str) -> dict:
    """calibrate -> tile -> components -> wires (excluding component boxes) -> nets. Returns twin.schema.json."""
```

## T4 knowledge/ — datasheets, profiles, reading history

```python
def ingest(pdf_path: str, part_id: str) -> int:
    """Extract, chunk, index a datasheet. Returns number of chunks. Idempotent."""

def search(part_id: str, query: str, k: int = 5) -> list[dict]:
    """Hybrid keyword+vector search. Each hit: {text, page, section, score, source_file}.
    `page` is the page label a human sees in a PDF viewer. `text` is the parent-page window, <= 1200 chars."""

def get_profile(part_id: str) -> dict:
    """Parsed knowledge/profiles/<part_id>.yaml (schema: contracts/profile.example.yaml). KeyError if missing."""

def list_profiles() -> list[dict]:
    """All profiles (T2 uses aliases for normalization)."""

def record_read(url_or_path: str, text: str | None, seconds_on_page: float) -> None:
    """Log that the user read something (called via POST /read from the browser extension)."""

def recent_reads(part_id: str | None = None, hours: int = 24) -> list[dict]:
    """[{part_id, page, title, read_at, seconds}] newest first — lets T3 say 'you read page 7 last night'."""
```

## T3 reasoning/ — diagnosis

```python
def run_checks(twin: dict, serial: list[str]) -> dict:
    """Proactive. Deterministic profile checks only (no API call). Returns diagnosis.schema.json, mode='proactive'."""

def answer(question: str, twin: dict, serial: list[str], frame_path: str) -> dict:
    """Reactive, phase 1: rule findings for the question, no API call (<300 ms). diagnosis.schema.json, mode='answer'."""

def refine(question: str, twin: dict, serial: list[str], frame_path: str, rule_diagnosis: dict) -> dict:
    """Reactive, phase 2: vision-model answer, grounded and verified. Same frame_id as rule_diagnosis.
    Must never return something worse than rule_diagnosis: on any failure, return rule_diagnosis."""
```

## HTTP + WebSocket (T5 owns server and client)

HTTP: `GET /` UI · `GET /stream` MJPEG · `GET /frame.jpg` · `POST /read` body `{url, text, seconds}` → `knowledge.record_read` · `WS /ws`

Server -> client:
- `{"type": "twin", "twin": {...}}` — draw overlay
- `{"type": "diagnosis", "diagnosis": {...}}` — show alert cards (may arrive twice for one question: rules first, then the refined answer with the same `frame_id`)
- `{"type": "serial", "line": "..."}`
- `{"type": "confirm_request", "element_id": "...", "prompt": "..."}`
- `{"type": "status", "stage": "...", "ms": 123}`

Client -> server:
- `{"type": "ask", "question": "..."}`
- `{"type": "calibrate", "corners": [[x,y],[x,y],[x,y],[x,y]]}`
- `{"type": "register", "part_id": "bme280", "row_index": 0, "pixel": [x, y]}`
- `{"type": "confirm", "element_id": "...", "answer": true}`
