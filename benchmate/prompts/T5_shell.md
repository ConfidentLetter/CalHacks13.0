# T5 — Shell: camera, serial, server, UI, telemetry

**How to use:** paste this whole file as the first message in the T5 terminal.

## Project context (identical in all five prompts)

We are building **BenchMate** at Cal Hacks (a weekend hackathon): "a stack trace for your breadboard". A phone camera on a fixed mount looks straight down at a solderless breadboard. BenchMate turns the image into a structured *circuit twin* (which component pin and which wire sits in which hole, and which holes are electrically connected), checks it against component profiles built from datasheets, reads the microcontroller's serial output, and tells the user what is wrong, how to fix it, and which datasheet page says so.

The whole build serves two live demo scenarios:
1. **Prevention** — a 3.3 V-only I2C sensor's VIN is wired to the 5 V pin. Before anyone asks, BenchMate raises an error card citing the datasheet's maximum supply voltage page.
2. **Debug** — the sensor's SDA and SCL wires are swapped. Serial prints "no I2C devices found". The user asks "why isn't the sensor reading?" BenchMate answers "SDA and SCL are swapped — move the yellow wire from I18 to I15" with the datasheet page. The user swaps the wires and readings appear.

One person (Henry, the integrator) runs five AI terminals in parallel. **All five work in the same project folder at the same time**, so every file another terminal writes is visible to you immediately:

| Terminal | Folder | Owns |
|---|---|---|
| T1 Geometry | `perception_geometry/` | calibration, hole mapping, tiling, wire detection, nets |
| T2 Detection | `perception_detect/`, `eval/` | components, part identification, twin assembly, test set, accuracy chart |
| T3 Reasoning | `reasoning/` | rule checks, vision-model answers, self-correction |
| T4 Knowledge | `knowledge/` | datasheets, retrieval, profiles, reading history |
| T5 Shell | `app/` | camera, serial, server, UI, telemetry |

Before writing any code, read: `README.md`, `AGENTS.md`, `HARDWARE.md`, every file in `contracts/`, and the files in `mocks/` (run `python mocks/make_mocks.py` to see how the mock twins are built). The contracts are frozen; if one blocks you, write the problem at the top of `NOTES_<terminal>.md` and continue with a workaround. Never edit another terminal's folder, `contracts/` or `mocks/`.

Working rules:
- Every function in `contracts/interfaces.md` for your folder must exist with that exact signature from your first step, returning mock data if the real version is not ready. Other terminals import it immediately.
- Everything you return that has a schema must validate against it; each of your test files includes a schema-validation test.
- Time every stage with `app.telemetry.log(stage, ms, **extra)`. If `app/telemetry.py` does not exist yet, use `try: from app.telemetry import log except ImportError: log = lambda *a, **k: None`.
- Dependencies go in `requirements/<folder>.txt`. Python 3.11. Tests with `pytest` under `<folder>/tests/`.
- Model name from env `BM_MODEL` (default `claude-sonnet-5-5`), key from `ANTHROPIC_API_KEY`. Never hard-code keys.
- Never run git commands (no commit, branch, checkout, stash, reset); Henry takes snapshots. Only T5 starts the server on port 8000; everyone else tests with `pytest` and plain imports. Install packages with `pip install` into the shared environment and add them to your requirements file. At each checkpoint (H+1, H+4, H+8, H+16, H+22) update the 3-line status block at the top of `NOTES_<terminal>.md`: Done / Next / Blocked.
- Prefer boring, deterministic code. A demo that works every time beats a clever one that works most of the time.
- When you finish a step, run its tests, update your NOTES status block, then move to the next step without waiting for confirmation. Ask the human only when a decision changes another terminal's work.
- Staying in sync: before each new step, re-read `contracts/CHANGELOG.md` and the status block at the top of every other `NOTES_T*.md`. You may READ any file in the repo at any time (other terminals' code included) to integrate correctly; you may only WRITE inside your own folder and your own `NOTES_<terminal>.md`. If another terminal must know something (wrong pin order, contract problem, hardware surprise), add it under `## For other terminals` in your NOTES and say it in your reply so Henry sees it.

---

## Your role

You are T5. You own `app/`. You build everything the judges see and the plumbing everyone else depends on: telemetry, camera capture, serial reading, the FastAPI server that runs the pipeline, and the browser UI. You are also responsible for demo safety: the demo must be able to run from mocks if hardware or network fails on stage.

## Build in this order

### Step 1 (within the first 30 minutes): telemetry
`app/telemetry.py`: `log(stage, ms, **extra)` appends one JSON line `{ts, stage, ms, ...}` to `runtime/telemetry.jsonl` (create dirs as needed; thread-safe with a lock). Add a `timed(stage)` context manager. Finish this before anything else and say so in your reply — every other terminal imports this.

### Step 2 (by H+2): capture — `app/capture.py`
- Background thread reading `cv2.VideoCapture(BM_CAMERA_INDEX)` (env, default 0). Request 1920×1080; log what you actually get.
- Try to lock exposure and white balance (`CAP_PROP_AUTO_EXPOSURE`, `CAP_PROP_AUTO_WB`); not all cameras honour it — log the result and move on.
- Keep the latest frame in memory; write `runtime/frames/latest.jpg` at ~5 fps.
- `get_frame(high_res=False)` → path to latest; `high_res=True` → save a fresh full-resolution still with a timestamped name and return it.
- `frame_changed(threshold=0.02)`: downscale to 160×90 grayscale, compare with the last *analysed* frame by mean absolute difference. State machine: STABLE → (diff > threshold) CHANGING → (diff between consecutive frames < threshold/2 for 0.8 s) STABLE_NEW → return True once. This waits until the user's hand has left the frame before analysing (the "just-in-time" idea from the JHU poster).
- Camera list helper `python -m app.capture --list` that tries indices 0–5 and saves one frame from each, because phone-as-webcam often appears at index 1 or 2.

### Step 3 (by H+3): serial — `app/serial_bridge.py`
- `pyserial` reader thread; port from env `BM_SERIAL_PORT`, else auto-pick the first port whose description contains `USB`, `CP210`, `CH340` or `usbserial`; 115200 baud.
- Ring buffer of `(timestamp, line)`; `get_recent_serial(seconds)`.
- Replay mode (env `BM_SERIAL_REPLAY=mocks/serial_sda_swapped.txt`): emit the file's lines one per second, looping. Used when no board is attached and as stage backup.
- Push every new line over WebSocket as `{"type": "serial", ...}`.

### Step 4 (by H+4): server — `app/server.py`
- FastAPI app; run with `uvicorn app.server:app --port 8000`.
- Routes exactly as in `contracts/interfaces.md`: `GET /` (UI), `GET /stream` (MJPEG multipart of the latest frame, ~10 fps), `GET /frame.jpg`, `POST /read` (→ `knowledge.record_read`), `WS /ws`.
- Pipeline loop (background task): when `frame_changed()` → `frame = get_frame(high_res=True)` → `twin = perception_detect.build_twin(frame)` → broadcast `twin` → `diag = reasoning.run_checks(twin, get_recent_serial(10))` → broadcast `diagnosis`. Run blocking work in a thread pool so the WebSocket stays responsive.
- On `ask`: rebuild the twin from a fresh frame, broadcast it, call `reasoning.answer(...)` → broadcast (Phase 1, rules); then `reasoning.refine(...)` → broadcast again with the same `frame_id` (Phase 2, refined). If refine fails or takes > 8 s, keep the Phase 1 card.
- On `calibrate` → `perception_geometry.calibrate(frame, corners)`; on `register` → `perception_detect.register(...)`; on `confirm` → store the answer in `runtime/confirmations.json` and re-run checks.
- Every handler wrapped in try/except: on error, broadcast `{"type":"status","stage":"<stage>","error":"<short message>"}` and keep serving. The server must never crash on stage.
- **Mock mode** (env `BM_MOCK=1`): no camera or other modules needed. Keyboard shortcuts in the UI (1 = OK, 2 = 5V, 3 = swapped) load the matching mock twin, a matching serial replay, and the diagnosis from the real `reasoning.run_checks` if importable, otherwise `mocks/diagnosis_sda_swapped.json`. This is the demo backup; it must work offline.

### Step 5 (H+4 → H+12): the UI — `app/static/index.html` (one file, plain HTML/CSS/JS, no build step)
Layout: left 2/3 live view; right 1/3 alert cards on top, serial panel below; question bar along the bottom.
- **Live view**: `<img src="/stream">` with a `<canvas>` overlay of the same size. Scale twin pixel coordinates from the original frame size to the displayed size.
- **Overlay** (the clickable-overlay idea from the LoBE-GS poster): component boxes with `part_id` labels; each wire drawn as a line between its endpoint pixels in its own color with a small hole label at each end; elements involved in an `error` finding pulse red; low-confidence elements dashed. Click any element → side popover with its JSON (`hole`, `confidence`, net members).
- **Alert cards**: severity color as a thin left border only (red error, amber warning, grey info, green ok), title, fix (larger text), explanation (collapsed), "Datasheet p. N" chip with the quote on hover, confidence as a small number. When the refined diagnosis arrives for the same `frame_id`, replace the cards in place with a subtle transition — don't stack duplicates.
- **Confirm requests**: inline card with the prompt and Yes / No buttons → `confirm`.
- **Modes** (toolbar): Normal · Calibrate (shows ArUco status: "4/4 markers"; click 4 board corners as fallback) · Register (pick a part from a dropdown filled by `knowledge.list_profiles`, click its first pin; for two-row parts it asks for the second row).
- **Question bar**: text input + mic button using the Web Speech API (`webkitSpeechRecognition`, Chrome) → `ask`. Show a spinner card immediately.
- **Status line**: last stage and its ms, any error from the server.
- Visual style: clean, high contrast, readable from 3 metres on a projector; system font; no heavy decoration. Test at 1280×720 and on a phone width.

### Step 6 (by H+12): latency panel
Dev-only drawer (toggle with `L`): per-stage ms for the last pipeline run from `status` messages and `runtime/telemetry.jsonl`; anything over budget (twin 2 s, rules 0.3 s, refined first token 2 s) in red. The 2-second budget idea is from the TuringData poster.

## Pitfalls to design around
- Phones used as webcams sleep or rotate; lock orientation and keep the phone charging.
- MJPEG in Chrome can freeze if the server blocks — never do heavy work on the event loop.
- The overlay must not drift: always use the twin's original-image pixel coordinates and the stream's natural size for scaling.

## Done when
- With `BM_MOCK=1` and nothing else running, the full demo plays: overlay → press 2 → 5V error card with page chip → press 3 → swapped card → ask a question → refined card replaces it.
- With the real camera and microcontroller, moving a wire updates overlay and cards within ~3 s of the hand leaving the frame.
- Killing the network mid-demo still leaves the Phase 1 cards working.

## Report at every checkpoint
Top of `NOTES_T5.md`: Done / Next / Blocked, plus which camera index and serial port worked on the demo laptop.
