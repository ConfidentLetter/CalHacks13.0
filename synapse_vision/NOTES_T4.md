# NOTES_T4 — App & Eval

**Done:** Steps 1–5 all built and tested (50 tests, `pytest app/tests eval/tests`). Config+telemetry; `app/server.py` (mock + real, `/events`, watch loop, `/label`); viewer at `/`; label tool at `/label`; `eval/prelabel.py`, `eval/run_eval.py`, `eval/plot_history.py`; `eval/history.csv` has 2 rows + `eval/accuracy_journey.png`. **Mock server RUNNING: http://10.0.6.238:8000 (SV_MOCK=1)** — give the Tutor team `app/API.md`.
**Next:** waiting on real photos in `eval/testset/<n>.jpg` → `python -m eval.prelabel` → Henry corrects at `/label` → `python -m eval.run_eval --note "..."` at each checkpoint. Then switch the server to real mode (`uvicorn app.server:app --host 0.0.0.0 --port 8000`, or `python -m app.server --watch`) once T1 capture works with the camera.
**Blocked:** nothing on my side. Real-path eval row 2 shows T1 page detection returned quality.ok=False and T2 found 1 of 4 lines on my synthetic PIL page (`eval/testset/synthetic_demo.jpg`, no dark mat border) — expected for a fake page, will re-run on real photos.

## For other terminals
- `from app.config import get` → `get("layout.min_line_height_px", 28)`. Dotted keys into `config/vision.yaml`; missing key returns the default; file is re-read when its mtime changes.
- `from app.telemetry import log, timed` → `log("layout.segment", ms, lines=7)` or `with timed("transcribe.page") as t: t["lines"] = 7`. Appends to `runtime/telemetry.jsonl`. Never raises.
- Name stages `<folder>.<step>` (`capture.snapshot`, `page.dewarp`, `layout.segment`, `transcribe.page`, `transcribe.reread`). The viewer's latency drawer (`L` key) flags any stage over `budget_ms.new_line_incremental` and `pipeline.snapshot_to_twin` over `budget_ms.snapshot_to_twin_first`. **T3:** please log the incremental new-line time under a stage containing `incremental` (e.g. `transcribe.incremental`) — `run_eval` reads it for the latency row.
- **T3:** `build_page_twin` should set `twin["latency_ms"]["snapshot_to_twin"]` (total ms) plus per-stage keys; the server also measures the total if it is missing. The viewer's click-a-line panel reads OPTIONAL per-line extras if you add them: `crop_path`, `context_crop_path`, `readings: {"page_pass": "...", "line_pass": "..."}`, `reread: {"ran": bool, "reason": "...", "result": "..."}`, `latency_ms`.
- **T1/T2/T3:** image paths in the twin (`image.dewarped_path`, crop paths) must be repo-relative under `runtime/` (or `eval/`, `mocks/`) — the viewer fetches them at `GET /files/<path>`. **T1:** if you expose original-image page corners as `image.corners_original` ([[x,y]×4]), `run_eval` reports corner error against `page_corners` in the truth files.
- The server only calls `capture.source.get_snapshot`, `capture.source.wait_for_stable` and `transcribe.build_page_twin`. If any raise, the error is broadcast as `{"type":"status","stage":...,"error":...}` and the server keeps serving; if `transcribe` fails to import, it serves the mock twin flagged `_fallback`.
- **Henry:** `pytest -q` from root: 2 failures in `layout/tests` (T2: `test_demo_page_four_lines_in_order`, `test_segment_on_unreadable_path_still_returns_mock_shape`); everything else green (159 passed). `eval/runs/` holds cached predictions per eval run — consider git-ignoring it.

## How to run (T4 pieces)
- Mock server: `SV_MOCK=1 uvicorn app.server:app --host 0.0.0.0 --port 8000` (log: `runtime/server.log`). Real: drop `SV_MOCK`; add `--watch` via `python -m app.server --watch` or `SV_WATCH=1`.
- Viewer `http://localhost:8000/` (`?watch=1` turns the watch loop on at load; `L` = latency drawer). Label tool `http://localhost:8000/label`.
- Test set: photos → `eval/testset/<n>.jpg`; `python -m eval.prelabel` (`--force` to redo unreviewed pages, `--mock` for no-model); correct at `/label`, tick *planted error* and fill *corrected LaTeX* (needed for the preservation metric); tick *reviewed*.
- Eval: `python -m eval.run_eval --note "what changed"` → prints report, appends `eval/history.csv`, caches twins in `eval/runs/<ts>/`; `--reuse eval/runs/<ts>` re-scores without the model. Chart: `python -m eval.plot_history` → `eval/accuracy_journey.png`.

## Log
- H+2: Step 4 (`eval/truth.py`, `prelabel.py`, `label_helper.py`+`label.html`) and Step 5 (`metrics.py`, `run_eval.py`, `plot_history.py`) done; checked `/label` in Chrome. First two history rows written (mock path 100% preservation; real path on synthetic page: page not detected).
- H+1: Step 3 viewer done (checked in Chrome against the mock server).
- H+0.5: Step 2 done; mock server started. Restart needed after server.py edits (no --reload).
- H+0: Step 1 done. Installed python-multipart, matplotlib, pillow, httpx into .venv (`requirements/app.txt`, `requirements/eval.txt`).
