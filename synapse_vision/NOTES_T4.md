# NOTES_T4 — App & Eval

**Done:** Step 1 — `app/config.py` (`get("a.b", default)`, hot-reload on mtime) and `app/telemetry.py` (`log`, `timed`, `read`) with 11 passing tests.
**Next:** Step 2 — `app/server.py` (FastAPI :8000, mock mode, `/events` WS, watch loop) + `app/API.md`.
**Blocked:** nothing.

## For other terminals
- `from app.config import get` → `get("layout.min_line_height_px", 28)`. Dotted keys into `config/vision.yaml`; missing key returns the default; file is re-read when its mtime changes.
- `from app.telemetry import log, timed` → `log("layout.segment", ms, lines=7)` or `with timed("transcribe.page") as t: t["lines"] = 7`. Appends to `runtime/telemetry.jsonl`. Never raises.
- Please name stages `<folder>.<step>` (e.g. `capture.snapshot`, `page.dewarp`, `layout.segment`, `transcribe.page`, `transcribe.reread`) so the viewer's latency drawer can group them.

## Log
- H+0: Step 1 done. Installed python-multipart, matplotlib, pillow into .venv for Steps 2 and 5.
