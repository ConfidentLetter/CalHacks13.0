# NOTES_T2 — Layout

**Done:** Steps 1–4. Step 4 — `is_crossed_out`: Otsu crop ink (faint printed rules dropped), Zhang-Suen skeleton, Hough strokes chained by collinearity, scored by span / glyph crossings / continuity (letter-bar chains and fraction bars capped at 0.35), plus zig-zag detector (alternating diagonals + full middle-band coverage). Synth crops (40 pages): struck 49/52 flagged ≥0.6, clean 280/280 < 0.4 (0 false, 0 unsure). `segment` now emits `status_hint` = crossed_out / unsure / active; synthetic demo page → `[active, active, crossed_out, active]`. 48 tests pass (`pytest layout/tests`, ~7 s).
**Next:** Step 6 on Henry's real pages the moment `eval/testset/*.jpg` + truth exist (pencil contrast, back-bleed, graph paper); Step 5 (doctr) only if classical misses on real pages.
**Blocked:** nothing.

## For other terminals
- T3: `from layout import segment, is_crossed_out`. Each line in `segment(...)["lines"]` has `bbox, crop_path, context_crop_path, status_hint, ink_density` plus `order` and `region_id` (bonus; `region_id` matches `regions[i]["id"]`). Paths are repo-relative (`runtime/crops/<snapshot_stem>/line_000.png`, `_ctx.png` = line ± `layout.context_lines` neighbours with the target outlined in orange).
- T3: `status_hint` is real now — `crossed_out` when the classical strike score ≥ `layout.crossed_out_min_conf` (0.6), `unsure` when 0.4 ≤ score < threshold (ask the model yes/no), else `active`. `is_crossed_out(crop_path)` returns `(bool, score)` and works on any crop (upscaled or not). Your `d/dx` split report is fixed: stacked fractions (bar with ink above AND below) are fused before line grouping.
- T4: `layout.method` accepts `classical` (default) or `mock`. Telemetry stages: `layout.segment` (total), `layout.binarize`, `layout.components`, `layout.group`, `layout.crops`, `layout.crossed_out`, `layout.is_crossed_out` (per crop). Whole page ≈ 120–160 ms. `segment` never raises: on an internal error it logs `error=` in telemetry and returns `{regions: [], lines: []}`. Debug picture per snapshot: `runtime/debug/layout_<snapshot>.png`.
- All: thresholds I needed beyond `config/vision.yaml` are named constants at the top of each `layout/*.py` module (documented inline). Henry can promote any of them into `layout:` in the config and I will read them via `config_get` — tell me which.

## For Henry (demo page)
- Leave a visibly larger gap (≈1.5 line heights) between the problem statement and the first work line: that gap is what makes the first line a `problem` region. Lines inside the work should keep normal spacing.
- The debug picture for every snapshot is `runtime/debug/layout_<snapshot>.png` (boxes + order numbers, crossed-out hatched). Tune `layout.min_line_height_px` from it.

## Log
- Dewarp border slivers (dark strip left by a quad a few px inside the paper, seen on T1's synthetic photo seed 5 → 11 phantom 'lines') are now ignored: components entirely inside the outer 2 % band of the page are dropped. T1 chain re-checked on 12 photos: line counts match on all, struck lines flagged on all 4 struck pages. 48 tests.
- Step 6 prep (no real pages yet): graph-paper grids (both directions) and back-of-page bleed-through (gray 185–218) are ignored — faint components (< 0.5 × the page's strong-ink contrast) are dropped. End-to-end on T1's synthetic photos (`capture.tests.synth.render` → `detect_and_dewarp` → `segment`): line counts match on pen/pencil/ruled/struck pages, struck lines hatched. 47 tests.
- Step 4 done: `layout/{skeleton,crossed_out}.py`, `layout/tests/test_crossed_out.py`. Residual misses: tiny zig-zag lines (< 70 px) and strongly tilted double strikes; both would need the model's yes/no (they currently return 0.0/0.35 → `active`, not `unsure`).
- Step 3 done: `layout/{binarize,components,lines,order,debug,classical}.py`, `layout/tests/test_segment_synth.py` (30-seed scoring harness). Non-config constants live at the top of each module with comments; promote any to `config/vision.yaml` as needed (I cannot edit config).
- T3's report (`d/dx` denominator split on `live_page`) predates fraction fusion; `eval/testset/synthetic_demo.jpg` now segments to 4 lines in order with no split.
- Step 2 done: `layout/tests/synth.py` (`render_page(seed)`, `render_demo_page()`, `make_testset(dir)`), `layout/tests/test_synth.py`. Preview: `python layout/tests/synth.py runtime/debug/synth`.
- Step 1 done: `layout/{_compat,geometry,crops,mock_layout,segment,crossed_out}.py`, `layout/tests/test_stubs.py`, `requirements/layout.txt`.
