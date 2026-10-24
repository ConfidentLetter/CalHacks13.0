# NOTES_T2 — Layout

**Done:** Step 2 — `layout/tests/synth.py` renders flat synthetic pages (script fonts, ±3° lines, ±6 px word jitter, superscripts, stacked fractions, single/double/zigzag strikes, ruled paper, pencil, margin notes) with ground-truth boxes/order/crossed flags; Step 1 stubs; 24 tests pass.
**Next:** Step 3 — classical line segmentation (`layout/classical.py`) hitting ≥95 % IoU-0.6 recall, zero merges, exact order on synth.
**Blocked:** nothing.

## For other terminals
- T3: `from layout import segment, is_crossed_out` works now. Each line in `segment(...)["lines"]` has `bbox, crop_path, context_crop_path, status_hint, ink_density` plus `order` and `region_id` (bonus fields; `region_id` matches `regions[i]["id"]`). Paths are repo-relative (`runtime/crops/<snapshot_stem>/line_000.png`).
- T4: `layout.method` in `config/vision.yaml` accepts `classical` (default) or `mock`. Until Step 3 lands, `classical` silently falls back to mock boxes. `layout/_compat.py` reads `app.config.get` / `app.telemetry.log` when they exist, else YAML directly. Telemetry stage name: `layout.segment`.

## Log
- Step 2 done: `layout/tests/synth.py` (`render_page(seed)`, `render_demo_page()`, `make_testset(dir)`), `layout/tests/test_synth.py`. Preview: `python layout/tests/synth.py runtime/debug/synth`.
- Step 1 done: `layout/{_compat,geometry,crops,mock_layout,segment,crossed_out}.py`, `layout/tests/test_stubs.py`, `requirements/layout.txt`.
