Done: Steps 1–4. `calibrate` (ArUco → homography → hole-grid refinement; 100 % of 630 holes on 50 synthetic boards even with markers taped 3 mm off), `pixel_to_hole`/`hole_to_pixel`, `detect_wires` (HSV masks + CLAHE, skeleton graph with junction pairing for same-colour crossings, fragment merging across crossing wires/PCBs, extrapolation, debug image), `tile` (edge-density-balanced strips, 1-pitch overlap, 2× upscale), `build_nets`. Demo-scene test renders the three mock circuits end to end. 42 tests pass (`pytest perception_geometry/tests -q`, ~55 s).
Next: Step 5 — tune `BOARD_CONFIG`, `WIRE_COLORS`, `WIRE_PARAMS["extend_pitches"]` on real photos the moment they land in `eval/calibration/` / `eval/testset/`. Until then: harden synthetic bench (lighting/resolution), reduce same-colour mis-pairing.
Blocked: no real photos yet (not blocking work). Henry: 4 calibration photos → `eval/calibration/` please; even phone snapshots of the taped markers + bare board help me verify the rail/row layout.

Synthetic accuracy (50 boards, 4–6 wires, 2 PCBs, markers jittered 1 mm): wire endpoints 94.9 % on the correct hole, ~80 ms/frame; calibrate ~20 ms (cached: <1 ms), tile ~15 ms.

## For other terminals

- **T2 (update):** `detect_wires` is real now and much better than the snapshot you measured (46/60): 94.9 % endpoints on my 50-board synthetic sweep. Same-colour wires that touch/cross are now split at skeleton junctions and come back as separate wires with `confidence ≤ 0.5`; an end that disappears under a PCB comes back as `hole: null` with confidence 0.3. Please keep passing `exclude_boxes` — I use them to tell a PCB blob from a wire of the same colour (a blob mostly inside a box AND fat ≥ 3.2 mm is the PCB; thin blobs inside the box are wires over it).
- **T2 (tiles):** each tile dict is `{path, bbox:[x,y,w,h], scale, strip_warped_x}`. `scale` is 1.0 or 2.0 (upscaled when the crop is narrower than 640 px). Map a detection back with `orig_xy = bbox[:2] + det_xy / scale`. Tile count = `min(max_tiles, ceil(board_width_px / 400))` (4 at 1080p, 2–3 at 720p). Tiles are axis-aligned crops of the ORIGINAL frame, saved to `$BM_RUNTIME_DIR/tiles/`.
- **T5:** fixed — calibrate telemetry no longer emits `Infinity` (non-finite → null). Telemetry keys I log: `calibrate{source, blobs, err_before_px, err_after_px, method}`, `detect_wires{n_wires, n_low_conf, debug}`, `tile{n_tiles, width_orig}`, `build_nets`.
- **T5 (debug):** set env `BM_DEBUG_WIRES=1` and every `detect_wires` call writes `$BM_RUNTIME_DIR/debug/wires_<frame>.png` (masks tinted, skeletons white, snapped holes labelled, bad snaps red). Handy to expose behind a key in the latency drawer.
- **Henry (hardware, before wiring the demo board):** an ESP32 DevKitC has its two pin rows 0.9" apart (9 pitches, e.g. rows C and J as in the mocks), and its body covers every row in between. On one 830 board that leaves free holes on ONE side only (A/B next to row C) — the J-row pins (GPIO21/22 in the mock) have no free hole to wire into. Options: straddle two breadboards, put the ESP32 at the very end of the board with one pin row in the rail area, or use a narrower dev board. The mocks' `I15`/`I18` wiring assumes rows F–I are free, which they are not with the body over C–J. Please decide; T2's footprint rows and my `render_mock_scene` follow whatever you pick.
- **Henry (wiring the demo board):** never let one wire lie on top of another wire's last ~2 holes. When two wires converge on neighbouring holes (SDA/SCL into B42/B43, GPIO21/22), the upper wire hides the lower wire's end; I then return a low-confidence guess and T3 has to ask. Also prefer the rail hole right above/below the wire's column. `perception_geometry/tests/test_demo_scene.py` renders the three mock circuits and checks exactly this.
- **T3:** wire `confidence` semantics: `1 − snap_distance/(0.5 pitch)` per end, min over both ends; `≤ 0.5` = passed through a crossing of the same colour (pairing could be wrong); `0.3` = one end hidden under a component (`hole: null`); `≤ 0.6` = end found by extrapolating through a crossing wire. Your 0.6 gate therefore asks the user exactly in the cases I am unsure about.

- **T2/T3**: `from perception_geometry import build_nets, calibrate, pixel_to_hole, hole_to_pixel, tile, detect_wires, CalibrationError` works now. `detect_wires` still returns the mock wires from `mocks/twin_ok.json`; `calibrate` returns identity until Step 2 lands.
- **T2**: each tile dict is `{path, bbox:[x,y,w,h], scale}`. `scale` (1.0 or 2.0) is the upscale factor of the saved tile image; map a detection back with `orig = bbox[:2] + det_xy / scale`.
- **T5**: when markers are missing, the UI should ask for clicks on the four corner holes of the *main grid*: A1 (TL), A63 (TR), J63 (BR), J1 (BL). `CalibrationError`'s message is safe to show to the user verbatim.
- **Henry (hardware)**: avoid white and black jumper wires (white vanishes on the board, black looks like holes / the ESP32). Use red, yellow, green, blue, orange. The mock twins use black GND wires; on the real board use blue or green for GND and I will map colours accordingly.
- **Henry**: `BOARD_CONFIG["rails"]` assumes the *outer* rail row of each pair is PLUS (red line). Verify on the real board; swapping two dict keys in `perception_geometry/board.py` is the fix. Row order default is A at the top (nearest marker 0/1); flip `letters_top_to_bottom` if the board is mounted the other way.

## Layout decisions (perception_geometry/board.py)

- Warped board frame: 10 px/mm, pitch 25.4 px, x along columns 1..63, y down rows A..J. E→F gap = 3 pitches.
- Board outline 165.1 × 54.6 mm placed at (40, 40) mm in the warped frame; marker centres 15 mm diagonally outside each board corner.
- Rails are bands (pitch units from row A): TOP_PLUS [-4.6,-3.5), TOP_MINUS [-3.5,-2.3), BOTTOM_MINUS [13.3,14.5), BOTTOM_PLUS [14.5,15.6).

## Tuning log

| when | change | accuracy before → after |
|---|---|---|
| H+1 | initial BOARD_CONFIG from datasheet-ish dimensions of an MB-102 style 830 board | n/a (no real photos yet) |
| H+3 | grid refinement: greedy 1-D clustering → de-tilt (±4°) + histogram-peak clustering; column numbering → gap-tolerant chain walk (survives a component hiding whole columns) | synthetic, markers 2 mm off: 92.6 % → 100 % of 630 holes (50 boards) |
| H+3 | correction sanity check measured at corner holes (≤ 4 pitches) instead of image corners; ICP fallback only when initial error < 0.3 pitch | synthetic, markers 3 mm off: 47/50 → 50/50 boards perfect |
| H+5 | wires v1: HSV + close/open + skeleton farthest-endpoints, fat hole mask | 47.9 % endpoints (8 boards) |
| H+5 | hole mask → only hole pixels (+0.1 mm); ends hidden under PCB → null | 73.8 % |
| H+6 | merge same-colour fragments across occluders (crossing wires / PCBs); insulation-tip walk; extension 0.4→0.47 pitch (measured) | 88.7 % |
| H+6 | PCB = blob mostly inside box AND fat; keep outside parts; PCA end direction; extrapolate through crossing wires | 93.3 % → 95.8 % (12 boards) |
| H+7 | skeleton graph: split at junctions, pair branches straight-through, merge close junctions, graph-based spur pruning | 50 boards (4–6 wires, 2 PCBs): 92.5 % → 94.9 % |
| H+8 | hole mask ignores saturated pixels (a yellow wire is darker than the board in grayscale and was being cut by the hole mask) | mock-circuit scenes: 2/6 → 6/6 pass; sweep unchanged 94.7 % |
