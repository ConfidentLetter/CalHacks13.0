# NOTES_T5 — Shell (app/)

**Done:** Steps 1–6 all in. `app/telemetry.py`, `app/capture.py`, `app/serial_bridge.py`, `app/modules.py`, `app/pipeline.py`, `app/server.py`, `app/markers.py`, `app/static/index.html` (overlay + cards + serial + ask bar + mic + Calibrate/Register modes + mock keys + latency drawer). 44 tests pass (`pytest app/tests`). Verified in Chrome in mock mode: press 3 → swapped card with pulsing wires + swapped serial replay; ask → rule card in ~160 ms, refine timed out at 8 s and the rule card stayed; Calibrate click-4-corners works; L drawer shows per-stage ms + p50/p90.
**Next:** real-camera pass once Henry grants camera permission (`python -m app.capture --list`, set `BM_CAMERA_INDEX`), real serial once a board is plugged in, then demo hardening (overlay drift check against a real twin from T2).
**Blocked (Henry, 1 min):** macOS camera permission — `python -m app.capture --list` says `OpenCV: not authorized to capture video`. Grant Camera access to the terminal app running Claude Code (System Settings → Privacy & Security → Camera), rerun `--list`. Synthetic frames meanwhile; nothing else blocked.

## How to run

```bash
source env.sh
BM_MOCK=1 .venv/bin/python -m uvicorn app.server:app --port 8000     # demo backup, no camera/board
.venv/bin/python -m uvicorn app.server:app --port 8000               # live: BM_CAMERA_INDEX, optional BM_SERIAL_PORT
```
Open http://localhost:8000 · keys: 1 OK · 2 5V · 3 swapped · 0 back to live · R re-check · L latency drawer · / focus question · Esc normal mode.
A server is currently running on :8000 in mock mode (started by T5; `pkill -f "uvicorn app.server"` to stop).

## For other terminals

- **T3:** `refine` exceeded the 8 s budget in mock mode for "why isn't the sensor reading?" (telemetry shows `search_timeout` 250 ms from T4 inside `answer`, then refine never returned within 8 s). The UI keeps the rule card and shows "refine: timeout after 8s". If the vision call is inherently slow, consider streaming or a cheaper model via `BM_MODEL`; the budget for refine first token is 2 s.
- **T1:** a telemetry record from `calibrate` contained `"before_px": Infinity`. Python's json.dumps emits it, browsers reject it; I now sanitize non-finite floats to null before broadcast, but please log finite numbers (or null).
- **T3:** your real `run_checks` already fires "SDA and SCL are swapped" on `mocks/twin_sda_swapped.json` through my pipeline — nice. Confirmations from the UI are stored in `runtime/confirmations.json` as `{element_id: {answer, ts, frame_id}}`; `run_checks(twin, serial)` has no slot for them in the contract, so read that file if you want to use them. `refine` gets 8 s; after that the UI keeps the rule card.
- **T4:** `knowledge/embeddings.py` pulls torch, so the first `search()` costs seconds. I now call `modules.warmup()` (imports all four modules) in a background thread at server start; keep heavy imports at module import time rather than inside the first call, or lazy-load and accept the first-call hit.
- **T2:** mock twins have wire `pixel: [0,0]`; the UI falls back to a synthetic hole grid for drawing when pixels are `[0,0]`. Real twins must carry real original-frame pixels or the overlay drifts.
- **All:** WebSocket client→server also accepts T5-internal `{"type":"mock","scenario":"ok|5v|sda_swapped"}`, `{"type":"live"}`, `{"type":"rerun"}` (not in the contract; UI keys 1/2/3/0/R).

- `from app.telemetry import log, timed` is live. `with timed("my_stage", frame_id=...) as info: info["n"] = 3` logs ms automatically, also on exceptions.
- Telemetry path: `runtime/telemetry.jsonl` (override with env `BM_RUNTIME_DIR`, which tests should set to a tmp dir so you don't pollute the real log).
- Deps installed into shared `.venv`: opencv-python, fastapi, uvicorn[standard], pyserial, numpy, httpx, websockets. See `requirements/app.txt`.

## Hardware seen on this laptop (2026-10-23)

- Cameras: `MacBook Air相机` (likely index 0) and `Haoze的iPhone` Continuity Camera (likely index 1). Verify with `python -m app.capture --list`.
- Serial: no USB serial device attached yet (only Bluetooth/debug-console). Replay mode `BM_SERIAL_REPLAY=mocks/serial_sda_swapped.txt` is the fallback.

## Step log

- Step 5 (UI): done. Dark high-contrast single file; overlay scales twin pixels by `naturalWidth/Height`; mock twins (pixel `[0,0]`) are laid out on a synthetic hole grid and component boxes hug their pins; error/warning evidence pulses; low-confidence dashed; click → JSON popover with net members; cards replace in place per frame_id; confirm cards; Web Speech mic; errors stick for 8 s on the status line.
- Step 6 (latency drawer): done. `L` toggles; last-run ms per stage vs budget (over budget in red) + p50/p90 from `/api/telemetry`.
- Fixes along the way: `serial_bridge.set_replay/set_serial` module-level wrappers (scenario keys did not switch the replay before); refine runs on a daemon thread (a hung vision call no longer blocks process exit); `json_safe()` strips Infinity/NaN.

- Step 3 (serial): done. `SerialBridge` thread; auto-pick port by USB/CP210/CH340/usbserial hint, rescans every 3 s if nothing is plugged in; replay mode loops a file at 1 line/s (`BM_SERIAL_REPLAY_INTERVAL` to speed up); `set_replay()`/`set_serial()` switch modes live.
- Step 4 (server): done. Thread pool for all pipeline work; MJPEG generator only copies pre-encoded JPEG bytes; every WS handler error becomes a `status` message. Twin/diagnosis are schema-validated on the way out (invalid → `status` error, still broadcast).

- Step 1 (telemetry): done. Fixed `read_recent(n)` to skip a half-written last line before counting.
- Step 2 (capture): done. `ChangeDetector` is a pure class (STABLE → CHANGING → fires once after 0.8 s quiet) tested with synthetic frames + fake clock. `Camera` falls back to `SyntheticSource` when the camera won't open (`BM_NO_CAMERA=1` forces it). `latest.jpg` is written via tmp + `os.replace` so readers never see a half file. Also exposes `camera().latest_jpeg()` for the MJPEG stream (no re-encode).
- Camera probe on this Mac: all indices refused with "not authorized to capture video" → terminal needs Camera permission (see Blocked).
