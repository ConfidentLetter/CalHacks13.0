# NOTES_T2 — Layout

**Done:** Step 3 — classical segmenter (`layout/classical.py` + binarize/components/lines/order/debug): Sauvola, edge-to-edge rule removal (lenient mask + line fit), fraction fusion (bar with ink above AND below), drift-tolerant line grouping, fragment/stacked merges, column split, margin regions, problem region, crops + context crops, `runtime/debug/layout_<snapshot>.png`. Synth (60 pages, 490 lines): recall 100 % @IoU 0.6, 0 merges, order exact 59/60. 32 tests pass.
**Next:** Step 4 — `is_crossed_out` (skeleton + Hough strike / zig-zag detector, fraction bars and underlines must not trigger) so the demo's struck line reaches T3 as `crossed_out`/`unsure`.
**Blocked:** nothing.

## For other terminals
- T3: `from layout import segment, is_crossed_out` works now. Each line in `segment(...)["lines"]` has `bbox, crop_path, context_crop_path, status_hint, ink_density` plus `order` and `region_id` (bonus fields; `region_id` matches `regions[i]["id"]`). Paths are repo-relative (`runtime/crops/<snapshot_stem>/line_000.png`).
- T4: `layout.method` in `config/vision.yaml` accepts `classical` (default) or `mock`. Until Step 3 lands, `classical` silently falls back to mock boxes. `layout/_compat.py` reads `app.config.get` / `app.telemetry.log` when they exist, else YAML directly. Telemetry stage name: `layout.segment`.

## For Henry (demo page)
- Leave a visibly larger gap (≈1.5 line heights) between the problem statement and the first work line: that gap is what makes the first line a `problem` region. Lines inside the work should keep normal spacing.
- The debug picture for every snapshot is `runtime/debug/layout_<snapshot>.png` (boxes + order numbers, crossed-out hatched). Tune `layout.min_line_height_px` from it.

## Log
- Step 3 done: `layout/{binarize,components,lines,order,debug,classical}.py`, `layout/tests/test_segment_synth.py` (30-seed scoring harness). Non-config constants live at the top of each module with comments; promote any to `config/vision.yaml` as needed (I cannot edit config).
- T3's report (`d/dx` denominator split on `live_page`) predates fraction fusion; `eval/testset/synthetic_demo.jpg` now segments to 4 lines in order with no split.
- Step 2 done: `layout/tests/synth.py` (`render_page(seed)`, `render_demo_page()`, `make_testset(dir)`), `layout/tests/test_synth.py`. Preview: `python layout/tests/synth.py runtime/debug/synth`.
- Step 1 done: `layout/{_compat,geometry,crops,mock_layout,segment,crossed_out}.py`, `layout/tests/test_stubs.py`, `requirements/layout.txt`.
