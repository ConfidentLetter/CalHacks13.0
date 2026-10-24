# Contract changes

- H0: initial contracts (page twin schema, interfaces, config).
- H+2 (Henry): `config/vision.yaml` — `budget_ms.snapshot_to_twin_first` 8000→15000, `new_line_incremental` 3000→8000 (one Sonnet 5.5 round trip is 4–9 s; the old budgets were unreachable with any model call). Added T3's optional `transcribe.*` keys (effort, thinking, empty_ink_density, page_pass_skip_below, sdk_max_retries) with their code defaults. `eval/runs/` is now git-ignored.
- H+3 (Henry): `config/vision.yaml` — `capture.webcam_index` 0→2 (built-in Mac camera; 0/1 are idle iPhone Continuity cameras), `page.blur_threshold` 80→1500 (T1's blur metric is variance-of-Laplacian near ink on normalized gray at 1100 px long side; old 80 never fired).
