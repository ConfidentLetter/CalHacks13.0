# Rules for every AI coding agent in this repo

You are one of four parallel AI terminals building Synapse Vision. One human (Henry) operates all four; all terminals share this folder. Read `README.md`, `contracts/`, `config/vision.yaml` and `mocks/` before writing code.

- Write only in the folders your prompt assigns you and your own `NOTES_<terminal>.md`. Never edit `contracts/`, `config/`, `mocks/`, or another terminal's folder. You may read anything.
- Implement every function listed for your folder in `contracts/interfaces.md` with the exact signature. Mock data first, real data second.
- Outputs with a schema must validate against `contracts/page_twin.schema.json`. Add a schema-validation test.
- Transcribe verbatim. Never correct, complete or simplify the student's work — not in prompts, not in post-processing.
- Tunables come from `config/vision.yaml` via `app.config.get`. Time each stage with `app.telemetry.log`. Fall back to local no-ops if those modules don't exist yet.
- Dependencies in `requirements/<folder>.txt`; Python 3.11; tests with pytest in `<folder>/tests/`.
- Model from env `SV_MODEL`, key from `ANTHROPIC_API_KEY`. Never hard-code keys.
- Never run git. Only T4 runs the server (port 8000).

## Sync protocol
- Before each new step: re-read `contracts/CHANGELOG.md` and the top status block of every `NOTES_T*.md`.
- After each step: run tests, update your three-line status (Done / Next / Blocked), continue without waiting.
- If another terminal's code is half-written or raises, fall back to mocks and note it; never edit their files.
- Anything another terminal must know: `## For other terminals` in your NOTES, and say it in your reply so Henry can relay it.
