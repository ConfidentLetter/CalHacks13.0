# Contract changes

- H0: initial contracts (page twin schema, interfaces, config).
- H+2 (Henry): `config/vision.yaml` — `budget_ms.snapshot_to_twin_first` 8000→15000, `new_line_incremental` 3000→8000 (one Sonnet 5.5 round trip is 4–9 s; the old budgets were unreachable with any model call). Added T3's optional `transcribe.*` keys (effort, thinking, empty_ink_density, page_pass_skip_below, sdk_max_retries) with their code defaults. `eval/runs/` is now git-ignored.
