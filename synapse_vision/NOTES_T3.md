# NOTES_T3 — Transcribe

**Done:** Step 1 — all four T3 functions exist with contract signatures; `build_page_twin` returns the re-stamped mock twin, schema-validated (7 tests pass: `pytest transcribe/tests`).
**Next:** Step 2 — verbatim system prompt (`transcribe/prompts.py`) + few-shot example bank (`transcribe/examples/`) with prompt caching.
**Blocked:** nothing. app/config.py and app/telemetry.py don't exist yet → using local fallbacks in `transcribe/compat.py` (auto-switches when T4 lands them).

## For other terminals
- T4: `from transcribe import build_page_twin, transcribe_page, normalize_latex, parse_ok` works now. `build_page_twin(path)` returns a schema-valid twin (mock content, fresh `snapshot_id`/`captured_at`). `transcribe.twin.mock_twin()` is the explicit SV_MOCK backup.
- T4: lines in the final twin may carry extra keys beyond the schema (`crop_path`, `context_crop_path`, `readings`) so the viewer can show crops and both readings. Schema permits additional properties on lines.
- T2: I consume `layout["lines"][i]` keys exactly as in interfaces.md: `bbox, crop_path, context_crop_path, status_hint, ink_density`. If `ink_density` is missing I compute my own.

## Log
- H+0: read contracts, config, mock. Step 1 stubs + tests written.
