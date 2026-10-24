# NOTES_T1 — Capture

**Done:** Step 1 (stubs with exact contract signatures, `upload:<path>` works, synthetic photo bench `capture/tests/synth.py`, 20 tests green). Step 2 source code written (pi/webcam/stability state machine), untested on hardware.
**Next:** Step 3 real page detection + dewarp + lighting + quality gate in `capture/page.py`, measured on 100 synthetic photos.
**Blocked:** nothing. `eval/calibration/` is still empty — using synthetic photos until real ones appear.

## For other terminals
- `from capture import get_snapshot, detect_and_dewarp, tile, wait_for_stable` works now. `get_snapshot("upload:<path>")` copies into `runtime/snapshots/<timestamp>.jpg`.
- `detect_and_dewarp(path)` currently (Step 1 stub) returns the input as `dewarped_path`, `quality.ok=True`, identity homography. When Step 3 lands it writes `<snapshot>_dewarped.jpg` (color, lighting-normalized) and `<snapshot>_dewarped_gray.png` next to it under `runtime/dewarped/`. All bboxes downstream are in the dewarped image's pixels.
- `quality.issues` values come from the schema enum: `no_page, partial_page, blur, glare, too_dark, hand_in_frame, skew_extreme`. `ok=False` for `no_page | partial_page | blur | hand_in_frame`; `glare`, `too_dark`, `skew_extreme` are warnings (`ok` stays True) — lower confidence, don't skip.
- T2: synthetic photos for your own tests: `from capture.tests.synth import render, save` (`render(seed, crossed_out=True, pencil=True, ruled=True)` → `.image`, `.page` (flat page), `.corners`).
- T4: I read config through `capture.compat.cfg(key, default)` which calls `app.config.get` when it exists, else PyYAML; telemetry via `capture.compat.log` → `app.telemetry.log` when it exists. Stage names: `capture.snapshot`, `capture.wait_for_stable`, `capture.page`, `capture.tile`.

## Log
- H+0: read everything; no NOTES from others yet. Wrote `capture/compat.py`, `capture/source.py`, `capture/page.py` (stub), `capture/tests/synth.py` + tests. `python -m capture.tests.synth --n 6 --flag aruco` renders samples to `runtime/debug/synth/`.
