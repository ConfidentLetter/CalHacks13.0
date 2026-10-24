# Rules for every AI coding agent in this repo

You are one of five parallel AI terminals building BenchMate. One human (Henry) operates all five; all terminals share this one project folder. Read `README.md` and `contracts/` before writing code.

- Edit only the folder your prompt assigns you. Never edit `contracts/`, `mocks/`, or another terminal's folder. If a contract blocks you, stop and write the problem to `NOTES_<your terminal>.md` for the integrator.
- Implement every function listed for your folder in `contracts/interfaces.md` with the exact signature. Return mock data first, real data second.
- Anything you return must validate against `contracts/twin.schema.json` or `contracts/diagnosis.schema.json` where those apply. Add a test that validates it.
- Use `mocks/` as input until the real upstream module exists. Never block on another terminal.
- Wrap each stage in `app.telemetry.log(stage, ms, ...)`. If `app/telemetry.py` does not exist yet, create nothing in `app/`; use a local no-op and leave a TODO.
- Keep dependencies in `requirements/<your folder>.txt`. Python 3.11.
- Model name comes from env `BM_MODEL`; API key from `ANTHROPIC_API_KEY`. Never hard-code keys.
- Never run git commands; Henry takes snapshots. Only T5 runs the server (port 8000). Write a 3-line status at the top of `NOTES_<your terminal>.md` after every step (Done / Next / Blocked).

## Sync protocol (shared folder, one operator)

- You may READ any file in the repo at any time, including other terminals' code and NOTES. You may only WRITE inside your own folder and your own `NOTES_<terminal>.md`.
- Before starting each new step: re-read `contracts/CHANGELOG.md` and the status block at the top of every `NOTES_T*.md`. If something there affects you, adapt first.
- Another terminal's code may be half-written when you import it. If an import fails or a function raises, fall back to the mock and note it in your NOTES; never edit their file to fix it.
- If another terminal must know something, add it under `## For other terminals` in your NOTES and say it in your reply so Henry can relay it.
