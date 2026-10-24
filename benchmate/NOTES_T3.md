# NOTES_T3 — Reasoning

**Done:** Step 1 — `reasoning.run_checks / answer / refine` exist with contract signatures, return the mock diagnosis adapted to frame_id/mode; schema-validated; 4 tests pass.
**Next:** Step 2 — rule engine (`reasoning/rules.py`) over `contracts/profile.example.yaml` profiles; Step 3 run_checks with serial evidence + citations.
**Blocked:** nothing. Using local fallbacks: no `app/telemetry.py` yet (no-op shim in `reasoning/_telemetry.py`), no `knowledge.*` yet (profiles read from `contracts/profile.example.yaml`).

Latencies: n/a yet (stub).

## For other terminals
- T5: `reasoning.answer()` returns within ~1 ms today (mock); call `reasoning.refine(...)` right after and send both as `diagnosis` messages with the same `frame_id`.
- Deps: `requirements/reasoning.txt` (anthropic, jsonschema, PyYAML, pytest) — all already in the shared venv.

## Log
- H+0: read contracts/mocks/prompt; Step 1 stubs + tests.
