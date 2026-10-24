# Contract changes

- H0: initial contracts (page twin schema, interfaces, config).
- H+2 (Henry): `config/vision.yaml` — `budget_ms.snapshot_to_twin_first` 8000→15000, `new_line_incremental` 3000→8000 (one Sonnet 5.5 round trip is 4–9 s; the old budgets were unreachable with any model call). Added T3's optional `transcribe.*` keys (effort, thinking, empty_ink_density, page_pass_skip_below, sdk_max_retries) with their code defaults. `eval/runs/` is now git-ignored.
- H+3 (Henry): `config/vision.yaml` — `capture.webcam_index` 0→2 (built-in Mac camera; 0/1 are idle iPhone Continuity cameras), `page.blur_threshold` 80→1500 (T1's blur metric is variance-of-Laplacian near ink on normalized gray at 1100 px long side; old 80 never fired).
- H+6 (Henry): added T5 Bridge (`bridge/`, `docs/CONNECTIONS.md`): adapter from the vision pipeline to the team frontend's `/api/*` contract (`../docs/BACKEND_INTEGRATION.md`, `../docs/BACKEND_CONTRACT.md`). Port 8000 hand-off: T4's app → T5's `bridge.server:app` which imports and extends it. Teammate branch `frontend-synapse` (PR #1) merged into main.
- H+8 (Henry): port 8000 now served by `bridge.server:app` (T5), which imports T4's app; T4's `app.server:app` must not bind 8000 again. `config/vision.yaml` gained `transcribe.image_examples: false` and `transcribe.structured_output: false` (T3's latency fix).
