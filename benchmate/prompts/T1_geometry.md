# T1 — Geometry: from pixels to holes

**How to use:** paste this whole file as the first message in the T1 terminal (Claude Code, Cursor, or similar).

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

You are T1. You own `perception_geometry/` and nothing else. You turn an overhead photo into exact breadboard coordinates: where the board is, which hole any pixel belongs to, where every jumper wire starts and ends, and which holes are electrically connected. Everything downstream trusts your hole ids, so precision beats features. Your work is classical computer vision with OpenCV — no neural networks.

## Board model (define this first, in `perception_geometry/board.py`)

- Board type `breadboard_830`: 63 numbered positions (1–63) × lettered positions A–J, plus 4 power rails.
- Hole id format: letter + number, e.g. `A1`, `J63`. Rail ids: `RAIL_TOP_PLUS`, `RAIL_TOP_MINUS`, `RAIL_BOTTOM_PLUS`, `RAIL_BOTTOM_MINUS`.
- Pitch 2.54 mm. Work in a **warped top-down board image at 10 px/mm** (pitch = 25.4 px).
- A–E and F–J are separated by the centre channel: the distance from E to F is 3 pitches (0.3 inch); within each half it is 1 pitch.
- Rails: treat each rail as a horizontal band. Any point inside a band maps to that rail id. Rail hole spacing differs between brands, so don't model individual rail holes.
- All layout constants (origin of A1, pitch, channel gap, rail band y-ranges, which side is "top") live in one `BOARD_CONFIG` dict so the team can tune them live against the real board in under a minute.

## Build in this order

### Step 1 (by H+1): stubs + `build_nets` + tests
- Create every T1 function from `contracts/interfaces.md` with the exact signature. Stubs return mock-consistent values: `calibrate` → identity matrix, `detect_wires` → the `wires` list from `mocks/twin_ok.json`, `tile` → one tile covering the whole frame.
- Port `build_nets` from `mocks/make_mocks.py` (union-find over breadboard nodes). Tests: for each of `mocks/twin_ok.json`, `twin_sda_swapped.json`, `twin_5v.json`, recompute nets from `components` + `wires` and assert they equal the file's `nets` (compare as sets of sorted member tuples; net ids may differ).
- Edge cases to test: a wire with one end `None` (off-board), a rail-to-rail wire, two wires sharing a hole, a component pin with `hole: None`.
- T2 and T3 can now integrate against you.

### Step 2 (by H+4): calibration, hole mapping, synthetic test bench
- **Synthetic renderer** `perception_geometry/tests/synth.py`: draw a white breadboard with dark holes at the `BOARD_CONFIG` positions, 4 ArUco markers (DICT_4X4_50, ids 0 TL, 1 TR, 2 BR, 3 BL) just outside the corners, and N colored wires (thick polylines, slight curve) between random holes. Apply a random perspective warp (±8° tilt, ±10 % scale), brightness change and Gaussian noise. Return the image plus ground truth (wire endpoints as hole ids). This lets you hit high accuracy before touching real hardware.
- `calibrate(frame_path, corners=None)`:
  1. Detect ArUco markers with `cv2.aruco.ArucoDetector`. If all four ids 0–3 are found, map each marker's centre to its configured target point in the warped board image and compute the homography with `cv2.findHomography`.
  2. **Grid refinement**: in the warped image, detect hole blobs (dark small circles, `cv2.SimpleBlobDetector` or adaptive threshold + contour filter). Fit a small affine correction (offset + scale + rotation) that minimizes distance from detected blobs to the nearest model hole. Accept the refinement only if it reduces the median error. This absorbs imprecise marker placement.
  3. If markers are missing but `corners` were clicked, use them (TL, TR, BR, BL of the board's hole area), then refine the same way.
  4. Otherwise raise `CalibrationError` with a message the UI can show ("Only 2 of 4 markers visible").
  5. Cache by a hash of the four marker positions; recompute only when they move more than 3 px, so a bumped camera self-heals.
- `pixel_to_hole(x, y, H)`: transform to warped coords, find the nearest hole; return its id if within 0.5 pitch, a rail id if inside a rail band, else `None`.
- `hole_to_pixel(hole, H)`: inverse, used by T2 to lay out component pins.
- Tests on synthetic images: after calibration, every model hole projected to the original image and back must round-trip to the same id; ≥ 99 % across 50 random warps.

### Step 3 (by H+8): wire detection
`detect_wires(frame_path, H, exclude_boxes=None)`:
1. Warp the frame to the board image. Apply CLAHE to the V channel to normalize lighting.
2. Mask out: holes (small dark blobs from Step 2), the board's printed lines, and every `exclude_boxes` region (component PCBs are blue, green or black and would otherwise look like wires) transformed into warped space.
3. Per color in `WIRE_COLORS` (HSV ranges in config; red needs two hue ranges because it wraps around 0/180), threshold, morphological close (kernel ~ 0.3 pitch), drop blobs smaller than 1.5 pitches of length.
4. Skeletonize each blob (`skimage.morphology.skeletonize`). Endpoints are skeleton pixels with exactly one neighbour.
5. If a blob has more than 2 endpoints (crossing or touching wires), take the two endpoints with the greatest geodesic distance and set confidence ≤ 0.5 so T3 asks the user to confirm.
6. The metal pin enters the hole slightly beyond the visible insulation: extend each endpoint ~0.4 pitch along the local skeleton direction before snapping.
7. Snap with `pixel_to_hole`. Confidence per wire = `min over both ends of (1 − snap_distance / (0.5 · pitch))`, clipped to [0, 1], further multiplied by 0.5 for the crossing case.
8. Return wires per `twin.schema.json` with `pixel` in ORIGINAL image coordinates and stable ids (`w_<color>_<n>`, numbered left to right).
- Synthetic test: ≥ 95 % of endpoints on the correct hole across 50 generated boards with 4–6 wires.
- Expose a debug mode that writes `runtime/debug/wires_<frame>.png` with masks, skeletons and snapped holes drawn on top. You and the integrator will live in this image while tuning.

### Step 4 (by H+8): tiling
`tile(frame_path, H, max_tiles=6)`: split the board along the numbered axis into vertical strips with roughly equal Canny edge density (so busy areas get smaller tiles), each overlapping its neighbour by 1 pitch. Save each tile, upscaled 2× if narrower than 640 px, to `runtime/tiles/`. Return bboxes in original image coordinates. T2 runs open-vocabulary detection on these, because large images get downscaled and thin parts disappear.

### Step 5 (H+8 → H+16): the real board
- Use the integrator's 4 calibration photos in `eval/calibration/` and T2's test set in `eval/testset/`.
- Tune `BOARD_CONFIG` and `WIRE_COLORS` on real images. Record each tuning change and the resulting accuracy in your NOTES file; the integrator puts this in the accuracy-journey chart.
- Target: ≥ 90 % of real wire endpoints on the correct hole under the demo lamp.

## Pitfalls to design around
- White wires on a white board and black wires next to dark holes are unreliable. If the team has them, tell the integrator to swap them for red/yellow/green/blue/orange. Write that in NOTES at H+1.
- Glare on the board makes white areas look saturated; CLAHE plus ignoring very high V values helps.
- Do not assume the board is horizontal in the image; everything goes through the homography.
- A wire's middle often lies over other wires or components; only the endpoints matter, so never use the blob's bounding box as the endpoints.

## Done when
- All T1 tests pass, including the three mock-net tests and the synthetic accuracy tests.
- On the integrator's real calibration photos, `calibrate` works from markers alone, and ≥ 90 % of wire endpoints land on the correct hole.
- The debug image makes every wrong snap visibly obvious.

## Report at every checkpoint
Top of `NOTES_T1.md`:
```
Done: ...
Next: ...
Blocked: ...
```
Below it, a running log of tuning changes with the accuracy before and after.
