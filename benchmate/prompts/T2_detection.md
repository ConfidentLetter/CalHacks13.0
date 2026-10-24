# T2 — Detection: components, the circuit twin, and the evaluation

**How to use:** paste this whole file as the first message in the T2 terminal.

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

You are T2. You own `perception_detect/` and `eval/`. You find each component on the board, identify exactly which part it is, place each of its pins in a hole, and assemble the full circuit twin from your work plus T1's. You also own the test set and the accuracy-journey chart that goes into the pitch, because you are the one who knows what "correct" means for a twin.

## Key design decision: three tiers, stop at the first one that is good enough

The camera is fixed and the demo board has 2–3 components. Training a detector is not the starting point.

| Tier | Method | When |
|---|---|---|
| A — must ship | Click-to-register: the user clicks the first pin of each footprint row once in the UI; the remaining pins are laid out from the profile footprint at 2.54 mm pitch through T1's `hole_to_pixel` / `pixel_to_hole`. Deterministic. | H+1 → H+4 |
| B — target | Zero-shot open-vocabulary detection with OWLv2, then the vision model reads the printed text on each crop. No training. | H+4 → H+12 |
| C — stretch | Train a small YOLO model using Tier B boxes as pseudo-labels, filtered and spot-checked (the pseudo-label → filter → retrain loop from the LESS poster). | Only if B is too slow or misses parts on the test set |

**Never ask the language model for bounding-box coordinates.** Its boxes are not precise enough for pin mapping. Use it only to read text and to answer yes/no about a crop.

## Build in this order

### Step 1 (by H+1): stubs that unblock everyone
- Every T2 function from `contracts/interfaces.md`, exact signatures. `build_twin(frame_path)` returns the content of `mocks/twin_ok.json` with a fresh `frame_id` and `timestamp`. Do this first — T3 and T5 integrate against this.
- Create `eval/` skeleton (see Step 6) so photos can start being collected now.

### Step 2 (by H+4): Tier A — registration and pin layout
- `register(part_id, row_index, pixel)` persists `{part_id, row_index, pixel, homography_hash}` to `runtime/registrations.json`. One registration per footprint row (ESP32 DevKit has two rows → two clicks; a 4-pin sensor has one row → one click).
- Pin layout: read `knowledge.get_profile(part_id)["footprint"]["rows"][row_index]`. Snap the clicked pixel to a hole with T1's `pixel_to_hole`. Walk the numbered axis: pin k sits k holes further along (same letter). Direction: towards higher numbers by default; if the walk would leave the board, walk the other way. Allow the UI to send a second click on the last pin to fix direction unambiguously (store it if present).
- Component bbox for Tier A: the min/max of its pin pixels padded by 1.5 pitch. Confidence 0.99 (a human placed it).
- If T4's profiles are not ready, use `contracts/profile.example.yaml` (it contains two YAML documents).
- Tests: a registered BME280 row at `B40` with pins `[VIN, GND, SCL, SDA]` yields `B40, B41, B42, B43`; registration survives a server restart; a registration whose homography hash no longer matches is reported as stale.

### Step 3 (by H+6): part identification
- `normalize_part(label_text)`: fuzzy-match (`rapidfuzz`, token_set_ratio) against every alias in `knowledge.list_profiles()`, after uppercasing and stripping spaces/dashes. Return `part_id` if score ≥ 85, else `None`. Tests: `"GY-BME280"`, `"bme 280"`, `"BME280 3.3"` → `bme280`; `"HC-SR04"` → `None`.
- Text reading: crop the component (pad 20 %, upscale 2× if small), send to the vision model with a prompt that asks for strict JSON `{"text": "...", "legible": true|false}` — printed markings only, no guessing of what the part might be. If not legible, return `None` and let Tier A or the user's register click supply the `part_id`.

### Step 4 (H+4 → H+12): Tier B — OWLv2 zero-shot detection
- Model: `google/owlv2-base-patch16-ensemble` via `transformers` (`Owlv2Processor`, `Owlv2ForObjectDetection`). Load once at import, cache on disk. Use `mps` on Apple Silicon, CUDA if present, else CPU.
- Text queries: `"a microcontroller development board"`, `"a small electronic sensor breakout board"`, `"a breadboard"`. Keep them in config; tune on the test set.
- Run on T1's tiles; map boxes back to original coordinates; merge across tiles with NMS (IoU 0.5); score threshold starts at 0.2 and is tuned on the test set.
- For each box: read its text (Step 3) → `part_id` → pin layout. Pin anchor without a click: from the profile footprint and the box, place the first pin at the box edge nearest the board centre line along the numbered axis, then snap. If any pin lands off-board, fall back to asking for a register click (emit a `needs_user_confirmation` style hint in NOTES; T5 shows a register prompt).
- Registered components (Tier A) always override Tier B for the same `part_id`.
- Measure latency per tile; if total > 3 s on the demo laptop, reduce tiles, use the base model at lower resolution, or move to Tier C.

### Step 5 (by H+8): `build_twin`
`build_twin(frame_path)` =
1. `H = T1.calibrate(frame_path)`
2. `tiles = T1.tile(frame_path, H)`
3. `components = detect_components(frame_path, tiles)` (Tier A registrations + Tier B detections)
4. `wires = T1.detect_wires(frame_path, H, exclude_boxes=[c["bbox"] for c in components])`
5. `nets = T1.build_nets(components, wires)`
6. Assemble, validate against `twin.schema.json`, log each stage's ms.
Cache the twin by frame hash. Wrap each upstream call so that if it raises, the twin is still returned with what succeeded and the failure is logged (the UI must never go blank).

### Step 6 (start at H+1, keep going): evaluation
- `eval/testset/<n>.jpg` + `eval/testset/<n>.twin.json`: at least 20 photos from the fixed mount. Vary: lamp position, wire placement, both demo failure states, the OK state, one with a hand partly in frame. Ground truth: run `build_twin`, then hand-correct the JSON (write `eval/label_helper.py` that draws the twin on the photo so correcting takes a minute per image).
- `eval/run_eval.py` computes:
  - component accuracy: fraction of ground-truth components found with the right `part_id` and every pin in the right hole;
  - wire-endpoint accuracy: fraction of ground-truth endpoints with the exact hole;
  - net accuracy: fraction of images whose nets equal ground truth as sets of member groups;
  - diagnosis accuracy (once T3 exists): fraction of images where the set of finding ids from `run_checks` equals `expected_findings` stored in the ground-truth file;
  - median and p90 `build_twin` latency.
  It appends one row to `eval/history.csv`: `timestamp, note, component_acc, wire_acc, net_acc, diagnosis_acc, median_ms, p90_ms`. The `note` is a short description of what changed since the last row ("CLAHE on V channel", "OWLv2 threshold 0.2→0.15").
- `eval/plot_history.py`: line chart of the accuracy columns over rows, each point annotated with its note, saved to `eval/accuracy_journey.png`. Plain styling. This is the pitch slide (the "accuracy journey" idea from the TTYSC poster).
- Run the eval at every checkpoint and whenever T1 or you change something. Rows with worse numbers stay in — the chart is more credible with a dip in it.

## Pitfalls to design around
- The ESP32 and many sensor boards have small, glossy, low-contrast markings; text reading will often fail. That is why Tier A exists. Don't spend hours on OCR.
- Footprint pin orders differ between ESP32 DevKit variants. If pins land in the wrong holes, the profile is wrong, not your code; tell T4.
- The twin must stay valid when the board is half covered by a hand: return fewer components, never crash.

## Done when
- Both demo boards produce twins whose nets match the hand-checked ground truth.
- `eval/history.csv` has at least 4 rows and `eval/accuracy_journey.png` exists.
- `build_twin` median latency ≤ 2 s on the demo laptop with Tier A, ≤ 4 s with Tier B.

## Report at every checkpoint
Top of `NOTES_T2.md`: Done / Next / Blocked, then the latest eval row.
