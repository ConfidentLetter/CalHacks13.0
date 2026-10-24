# Interfaces (frozen — only Henry changes this file; every change goes in CHANGELOG.md)

One Python process on the laptop (`app/server.py`) imports every module. The Raspberry Pi only takes pictures (`hardware/pi_snapshot_server.py`).
All bboxes are `[x, y, w, h]` in **dewarped page** pixels unless the name says `original`.
Thresholds and tunables live in `config/vision.yaml`, read via `app.config.get("section.key")`.

## T1 capture/ — getting a clean, flat page

```python
# capture/source.py
def get_snapshot(source: str | None = None) -> str:
    """Grab a full-resolution still. source = 'pi' | 'webcam' | 'upload:<path>' (default from env SV_SOURCE).
    Returns path under runtime/snapshots/."""

def wait_for_stable(timeout_s: float = 30.0) -> str | None:
    """Block until the scene changed and has been still for ~1 s with no hand/pen motion; return a fresh snapshot path, or None on timeout."""

# capture/page.py
def detect_and_dewarp(snapshot_path: str) -> dict:
    """{dewarped_path, width, height, homography, quality:{ok, issues, blur_score, glare_fraction}}.
    Finds the paper (page quad or ArUco fallback), flattens to a fixed aspect, normalizes lighting.
    Never raises on a bad photo: returns quality.ok=False with issues."""

def tile(dewarped_path: str, max_tiles: int = 6) -> list[dict]:
    """Ink-density-balanced horizontal bands with overlap. Each {path, bbox}."""
```

## T2 layout/ — where the lines are

```python
def segment(dewarped_path: str) -> dict:
    """{regions:[{id,type,bbox}], lines:[{bbox, crop_path, context_crop_path, status_hint, ink_density}]}
    in reading order. status_hint in {'active','crossed_out','unsure'}. crop_path = the line alone (2x upscale if small);
    context_crop_path = the line plus the line above and below (for parent-context reading)."""

def is_crossed_out(crop_path: str) -> tuple[bool, float]:
    """Classical check (strike-through stroke over the ink); returns (crossed, confidence)."""
```

## T3 transcribe/ — what the lines say, verbatim, with honest confidence

```python
def transcribe_page(dewarped_path: str, layout: dict, previous_twin: dict | None = None) -> list[dict]:
    """Lines per page_twin.schema.json#/properties/lines (without first_seen/last_changed — build_page_twin sets those).
    Only re-transcribes lines whose crop changed since previous_twin (crop hash cache)."""

def normalize_latex(latex: str) -> str:
    """Canonical spacing/commands for comparison only (\\cdot vs *, \\left( vs (, etc.). Never changes math meaning."""

def parse_ok(latex: str) -> bool:
    """True if SymPy can parse it. Used for confidence only; a failed parse never triggers a 'fix'."""

def build_page_twin(snapshot_path: str, previous_twin: dict | None = None) -> dict:
    """Full pipeline: T1 detect_and_dewarp -> T2 segment -> transcribe_page -> match lines to previous_twin
    (stable ids, changes.added/edited/removed/crossed_out, first_seen/last_changed) -> validate against page_twin.schema.json."""
```

## T4 app/ — server, viewer, telemetry, config, eval

```python
# app/telemetry.py
def log(stage: str, ms: float, **extra) -> None: ...
# app/config.py
def get(key: str, default=None): ...   # dotted key into config/vision.yaml, hot-reloaded
```

HTTP for the Tutor team (the hand-off):
- `GET /twin/latest` → latest page twin JSON
- `GET /twin/{snapshot_id}` → a specific snapshot
- `POST /snapshot` → trigger capture + recognition now; returns the twin
- `POST /upload` (multipart image) → recognize an uploaded photo; returns the twin
- `WS /events` → `{"type":"twin","twin":{...}}` after every new snapshot, plus `{"type":"line_added"|"line_edited"|"line_crossed_out","line":{...}}`
- `GET /` → viewer (dewarped page with line boxes, confidence, transcription; click a line to see crops and both readings)
