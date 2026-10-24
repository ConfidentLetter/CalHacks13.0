# Synapse Vision — handwritten work → verbatim page twin

The vision half of Synapse. A camera over the desk photographs the student's paper; this repo turns the photo into a **page twin**: every line on the page, its box, reading order, crossed-out status, a verbatim LaTeX/text reading (mistakes preserved, never corrected), and an honest confidence. The Tutor team consumes it over HTTP/WebSocket (`app/API.md`).

## Pipeline

snapshot (when the scene settles) → page detection + dewarp + quality gate → tiles → line segmentation + crossed-out → two independent readings per line + targeted re-read on disagreement → normalization (for comparison only) → page twin with stable line ids and change events → `/events`

## Terminals (one operator, one shared folder)

| Terminal | Writes only in | Owns |
|---|---|---|
| T1 Capture | `capture/`, `hardware/` | snapshots, stability trigger, page detection, dewarp, quality, tiling |
| T2 Layout | `layout/` | regions, lines, reading order, crossed-out detection, crops |
| T3 Transcribe | `transcribe/` | verbatim reading, confidence, normalization, page twin, diffs |
| T4 App & Eval | `app/`, `eval/` | config, telemetry, API, viewer, test set, metrics, accuracy chart |
| T5 Bridge | `bridge/`, `docs/CONNECTIONS.md` | module analysis, `/api/*` adapter for the team frontend (`../frontend`, `../extension`), tutor/chat layer, CORS, end-to-end verification |
| Henry | `contracts/`, `config/`, `main.py` | contracts, tuning, snapshots, camera, test pages, demo |

Launch steps and first messages: `prompts/RUNSHEET.md`.

## Rules
1. Each terminal writes only in its own folders and its own `NOTES_T*.md`; reads anything.
2. Code against `contracts/` and `mocks/` from minute one.
3. Transcribe verbatim. Never correct the student.
4. Tunables live in `config/vision.yaml`.
5. AI terminals never run git; Henry snapshots with `git add -A && git commit` at each checkpoint.

## Checkpoints (H0 = all four terminals launched)

| Time | Must be true |
|---|---|
| H+1 | Stubs, config, telemetry exist; `SV_MOCK=1` server serves the mock twin to the Tutor team |
| H+4 | Each module works on synthetic data; uploads go end to end |
| H+8 | Real camera → real twin in the viewer; first eval row |
| H+14 | Demo page correct: lines boxed, mistake preserved verbatim, crossed-out flagged; incremental update within budget |
| H+20 | Accuracy push done; accuracy-journey chart ready |
| H+24 | Feature freeze; rehearse |
