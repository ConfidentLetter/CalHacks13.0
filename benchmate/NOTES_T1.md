Done: Step 2 — real `calibrate` (ArUco ids 0-3 → homography → hole-grid refinement with de-tilt + row-pattern + gap-tolerant column chain), `pixel_to_hole`, `hole_to_pixel`, marker-move cache, clicked-corner fallback. Synthetic bench `perception_geometry/tests/synth.py`. 50-warp hole accuracy: 100 % with exact markers, 100 % with markers taped up to 3 mm off. 24 tests pass.
Next: Step 3 — `detect_wires` (CLAHE, HSV colour masks, skeleton endpoints, snap) + debug image; then Step 4 tiling.
Blocked: nothing. Still no real photos in eval/calibration/ (synthetic only).

## For other terminals

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
