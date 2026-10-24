# BenchMate — A stack trace for your breadboard

Overhead camera watches a breadboard, reads the datasheets you read, and tells you which wire is wrong and where the datasheet says so.

## How the work is split (5 AI terminals, one operator, one shared folder)

| Terminal | Folder (only edit here) | Owns | Pipeline parts |
|---|---|---|---|
| T1 Geometry | `perception_geometry/` | Board calibration, tiling, wire endpoints, hole mapping, nets | 2, part of 4 |
| T2 Detection | `perception_detect/`, `eval/` | YOLO components, auto-labeling, part_id normalization, twin assembly, test set + accuracy | 3, 4, 9 (accuracy) |
| T3 Reasoning | `reasoning/` | Dynamic checks, VLM queries, rule checks on twin, self-correction | 5, 7 |
| T4 Knowledge | `knowledge/` | Datasheet ingestion, hybrid search, page citation, component profiles | 6 |
| T5 Shell | `app/` | Camera capture, serial bridge, FastAPI + WebSocket, UI overlay, telemetry | 1, 8, 9 (latency) |
| Henry (integrator) | `contracts/`, `main.py`, hardware | Contracts, snapshots, end-to-end runs, hardware, pitch | all |

Launch order and the exact first message for each terminal: `prompts/INTEGRATOR.md`.

## Ground rules for every terminal (human or AI)

1. Edit only your own folder. Never edit `contracts/` — ask the integrator.
2. Code against the contracts and the files in `mocks/` from minute one. Do not wait on another terminal.
3. Every public function in `contracts/interfaces.md` must exist with that exact signature, even if it returns mock data at first.
4. Log every stage to `runtime/telemetry.jsonl` using `app.telemetry.log(stage, ms, **extra)` (T5 ships a stub first).
5. AI terminals never run git. Henry snapshots with `git add -A && git commit` at each checkpoint, so any bad change can be rolled back.

## Timeline (H0 = all five terminals launched)

| Checkpoint | Goal |
|---|---|
| H0 | Contracts + mocks on `main`. Every terminal starts. |
| H+4 | Each module runs standalone on mocks. Stubs replaced where ready. |
| H+8 | Integration 1: camera → twin → diagnosis → UI, end to end, even if accuracy is poor. |
| H+16 | Integration 2: both demo scenarios (5V warning, SDA/SCL swapped) work on the real board in good light. |
| H+22 | Accuracy push on the test set; accuracy-journey chart updated. |
| H+26 | Feature freeze. Only demo hardening and rehearsal after this. |

## Demo scenarios (the whole build serves these two)

1. Prevention: sensor VCC wired to 5V on a 3.3V-only module → warning before power-on, citing the datasheet page.
2. Debug: SDA and SCL swapped → serial shows "no I2C device" → user asks "why isn't it reading?" → "SDA is on GPIO22, should be GPIO21" → swap → readings appear.

## Hardware

See `HARDWARE.md`. Minimum: phone or webcam on a fixed overhead mount, a lamp, breadboard, ESP32 or Arduino Uno, one 3.3V-only I2C sensor, 4+ wire colors, printed ArUco markers from `markers/`.

## Stack

Python 3.11, FastAPI, OpenCV (ArUco + color segmentation), OWLv2 zero-shot detection (YOLO only as a stretch), a Claude model via API (model name in env `BM_MODEL`, default `claude-sonnet-5-5` for latency), plain HTML + JS frontend over WebSocket. Single process: modules are imported by `main.py`.
