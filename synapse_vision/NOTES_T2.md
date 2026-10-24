# NOTES_T2 — Layout

**Done:** Steps 1–4. Step 4 — `is_crossed_out`: Otsu crop ink (faint printed rules dropped), Zhang-Suen skeleton, Hough strokes chained by collinearity, scored by span / glyph crossings / continuity (letter-bar chains and fraction bars capped at 0.35), plus zig-zag detector (alternating diagonals + full middle-band coverage). Synth crops (40 pages): struck 49/52 flagged ≥0.6, clean 280/280 < 0.4 (0 false, 0 unsure). `segment` now emits `status_hint` = crossed_out / unsure / active; synthetic demo page → `[active, active, crossed_out, active]`. 43 tests pass (`pytest layout/tests`, ~7 s).
**Next:** Step 6 on Henry's real pages the moment `eval/testset/*.jpg` + truth exist (pencil contrast, back-bleed, graph paper); Step 5 (doctr) only if classical misses on real pages.
**Blocked:** nothing.

## For other terminals
- T3: `from layout import segment, is_crossed_out` works now. Each line in `segment(...)["lines"]` has `bbox, crop_path, context_crop_path, status_hint, ink_density` plus `order` and `region_id` (bonus fields; `region_id` matches `regions[i]["id"]`). Paths are repo-relative (`runtime/crops/<snapshot_stem>/line_000.png`).
- T4: `layout.method` in `config/vision.yaml` accepts `classical` (default) or `mock`. Until Step 3 lands, `classical` silently falls back to mock boxes. `layout/_compat.py` reads `app.config.get` / `app.telemetry.log` when they exist, else YAML directly. Telemetry stage name: `layout.segment`.

## For Henry (demo page)
- Leave a visibly larger gap (≈1.5 line heights) between the problem statement and the first work line: that gap is what makes the first line a `problem` region. Lines inside the work should keep normal spacing.
- The debug picture for every snapshot is `runtime/debug/layout_<snapshot>.png` (boxes + order numbers, crossed-out hatched). Tune `layout.min_line_height_px` from it.

## Log
- Step 4 done: `layout/{skeleton,crossed_out}.py`, `layout/tests/test_crossed_out.py`. Residual misses: tiny zig-zag lines (< 70 px) and strongly tilted double strikes; both would need the model's yes/no (they currently return 0.0/0.35 → `active`, not `unsure`).
- Step 3 done: `layout/{binarize,components,lines,order,debug,classical}.py`, `layout/tests/test_segment_synth.py` (30-seed scoring harness). Non-config constants live at the top of each module with comments; promote any to `config/vision.yaml` as needed (I cannot edit config).
- T3's report (`d/dx` denominator split on `live_page`) predates fraction fusion; `eval/testset/synthetic_demo.jpg` now segments to 4 lines in order with no split.
- Step 2 done: `layout/tests/synth.py` (`render_page(seed)`, `render_demo_page()`, `make_testset(dir)`), `layout/tests/test_synth.py`. Preview: `python layout/tests/synth.py runtime/debug/synth`.
- Step 1 done: `layout/{_compat,geometry,crops,mock_layout,segment,crossed_out}.py`, `layout/tests/test_stubs.py`, `requirements/layout.txt`.
