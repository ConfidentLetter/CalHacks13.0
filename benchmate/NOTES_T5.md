# NOTES_T5 — Shell (app/)

**Done:** Step 1 telemetry — `app/telemetry.py` ships `log(stage, ms, **extra)` + `timed(stage)` context manager + `add_listener` + `read_recent`; writes `runtime/telemetry.jsonl`, thread-safe, never raises. 8 tests pass (`pytest app/tests/test_telemetry.py`).
**Next:** Step 2 `app/capture.py` (camera thread, `get_frame`, `frame_changed`, `--list`), then Step 3 serial, Step 4 server, Step 5 UI.
**Blocked:** nothing.

## For other terminals

- `from app.telemetry import log, timed` is live. `with timed("my_stage", frame_id=...) as info: info["n"] = 3` logs ms automatically, also on exceptions.
- Telemetry path: `runtime/telemetry.jsonl` (override with env `BM_RUNTIME_DIR`, which tests should set to a tmp dir so you don't pollute the real log).
- Deps installed into shared `.venv`: opencv-python, fastapi, uvicorn[standard], pyserial, numpy, httpx, websockets. See `requirements/app.txt`.

## Hardware seen on this laptop (2026-10-23)

- Cameras: `MacBook Air相机` (likely index 0) and `Haoze的iPhone` Continuity Camera (likely index 1). Verify with `python -m app.capture --list`.
- Serial: no USB serial device attached yet (only Bluetooth/debug-console). Replay mode `BM_SERIAL_REPLAY=mocks/serial_sda_swapped.txt` is the fallback.

## Step log

- Step 1 (telemetry): done. Fixed `read_recent(n)` to skip a half-written last line before counting.
