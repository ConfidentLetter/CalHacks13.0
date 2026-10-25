# T4 — App & Eval: config, telemetry, the hand-off API, the viewer, and proof it works

**How to use:** Henry pastes the launch message from `prompts/RUNSHEET.md`; it tells you to read this file.

## Project context (identical in all four prompts)

**StudBud** is an AI learning companion for college STEM students who do homework on paper. A camera (Raspberry Pi camera on a desk mount, or a webcam/phone) looks down at the student's paper. **This repo is the vision half only**: it turns a photo of handwritten work into a *page twin* — a structured, verbatim record of every line on the page, where it is, whether it is crossed out, and how confident we are in each reading. A separate Tutor team consumes the page twin to find the step where the student went wrong and coach them.

The single most important rule in this repo: **transcribe exactly what is written, mistakes included. Never correct the student's math.** A published study of AI grading on real handwritten calculus (UC Irvine, arXiv 2603.00895) found transcription acceptable on roughly 88% of scans, and found that transcription occasionally "fixed" student mistakes — which destroys exactly the evidence the Tutor needs. It also found models hallucinating content in blank areas, and errors on nested fractions and crossed-out work. Every design choice below guards against those failure modes.

The demo the whole build serves: a student writes a derivative with a product-rule mistake on paper (`f(x) = x^2 sin x`, then `f'(x) = 2x · cos x`), crosses out a line, keeps going. Within a few seconds of their hand leaving the page, the viewer shows every line boxed and transcribed verbatim — the wrong line preserved exactly as written, the crossed-out line marked, uncertain symbols flagged — and the Tutor team's service receives the twin over `/events`.

Pipeline (each stage borrows a design from the NVIDIA GTC 2026 posters the team studied):

| Stage | Owner | Idea borrowed |
|---|---|---|
| Stability trigger, snapshot | T1 | JHU "just-in-time": analyse only when the scene changes and settles |
| Page detection, dewarp, lighting, quality gate | T1 | Recon: cheap always-on first stage gates the expensive second stage |
| Ink-balanced tiling | T1 | LoBE-GS: load-balanced partitioning so detail survives downscaling |
| Line segmentation, reading order, crossed-out detection | T2 | Recon: structured detection metadata before any language model |
| Line crops + context crops | T2 | Wiwynn: parent-page retrieval — give each fragment its surrounding context |
| Two independent readings + agreement | T3 | PKU recursive transformer: same model, more passes, on the hard cases |
| Targeted yes/no re-checks | T3 | Recon dynamic queries; AI Planner domain-rule validation |
| Strict schema, retry, verbatim check | T3 | GreenMind format reward; TTYSC reflection agent |
| Symbol normalization (for comparison only) | T3 | TTYSC entity normalization |
| Few-shot bank of verbatim examples, prompt caching | T3 | AI Planner example bank; TuringData caching and latency SLOs |
| Stable line ids across snapshots, change events | T3 | JHU temporal digital twin |
| Config file, telemetry, latency panel | T4 | NeMo blueprints + OpenTelemetry; TuringData 2-second budget |
| Pre-label → human-correct test set, accuracy-journey chart | T4 | LESS pseudo-labels refined and filtered; TTYSC accuracy journey |

Four AI terminals build in parallel in **one shared folder**, operated by one person (Henry):

| Terminal | Writes only in | Owns |
|---|---|---|
| T1 Capture | `capture/`, `hardware/` | snapshots, stability, page detection, dewarp, quality, tiling |
| T2 Layout | `layout/` | regions, lines, reading order, crossed-out, crops |
| T3 Transcribe | `transcribe/` | verbatim reading, confidence, normalization, page twin assembly, diffs |
| T4 App & Eval | `app/`, `eval/` | config, telemetry, server/API, viewer, test set, metrics, accuracy chart |

Before writing any code, read `README.md`, `AGENTS.md`, everything in `contracts/`, `config/vision.yaml`, and `mocks/page_twin_product_rule.json`.

Working rules:
- Every function in `contracts/interfaces.md` for your folder must exist with that exact signature from your first step, returning mock-consistent data until the real version works. Others import it immediately.
- Everything with a schema must validate against it; each test file includes a schema-validation test.
- Read tunables via `app.config.get(...)`; if `app/config.py` doesn't exist yet, read `config/vision.yaml` directly with PyYAML and leave a TODO. Never hard-code a threshold in logic.
- Time every stage with `app.telemetry.log(stage, ms, **extra)`; if it doesn't exist yet, use `try: from app.telemetry import log except ImportError: log = lambda *a, **k: None`.
- Never run git commands; Henry takes snapshots. Only T4 starts the server (port 8000). Tests with `pytest` under `<folder>/tests/`. Dependencies in `requirements/<folder>.txt`. Python 3.11.
- Model name from env `SV_MODEL` (default `claude-sonnet-5-5`), key from `ANTHROPIC_API_KEY`. Never hard-code keys.
- You may READ any file in the repo, including other terminals' code and NOTES. You may WRITE only in your own folders and `NOTES_<terminal>.md`. If another terminal's code is half-written or raises, fall back to mocks; never edit their files.
- Before each new step: re-read `contracts/CHANGELOG.md` and the status block at the top of every `NOTES_T*.md`.
- After each step: run its tests, update the top of `NOTES_<terminal>.md` with three lines (Done / Next / Blocked), then continue without waiting. Anything another terminal must know goes under `## For other terminals` in your NOTES and in your reply so Henry can relay it.
- Prefer boring, deterministic code. The demo must work every time.

---

## Your role

You are T4. You own `app/` and `eval/`. You build the plumbing everyone imports (config, telemetry), the server that runs the pipeline and hands page twins to the Tutor team, the viewer Henry demos with, and the evaluation that proves the recognition is trustworthy — including the accuracy-journey chart for the pitch.

## Build in this order

### Step 1 (first 30 minutes): config + telemetry — everyone imports these
- `app/config.py`: `get("section.key", default)` reading `config/vision.yaml`, re-reading the file when its mtime changes (live tuning without restarts).
- `app/telemetry.py`: `log(stage, ms, **extra)` appends `{ts, stage, ms, ...}` to `runtime/telemetry.jsonl` (thread-safe); `timed(stage)` context manager.
- Say "config and telemetry ready" in your reply.

### Step 2 (by H+3): the hand-off API — `app/server.py` (FastAPI, port 8000)
Exactly the routes in `contracts/interfaces.md`:
- `POST /snapshot` → `capture.get_snapshot()` → `transcribe.build_page_twin(path, previous)` → store under `runtime/twins/<snapshot_id>.json` → broadcast on `/events` → return the twin.
- `POST /upload` → same, from an uploaded photo (this is the demo backup and how the Tutor team tests without a camera).
- `GET /twin/latest`, `GET /twin/{snapshot_id}`.
- `WS /events`: after every twin, send `{"type":"twin",...}` then one event per id in `changes.added` / `edited` / `crossed_out` with the full line object.
- **Watch loop** (toggle `?watch=1` on startup or `POST /watch`): background task calling `capture.wait_for_stable()` repeatedly and running the pipeline on each new still.
- Every handler wrapped: on error, return/broadcast `{"type":"status","stage":...,"error":...}` and keep serving.
- Mock mode (`SV_MOCK=1`): every route serves `mocks/page_twin_product_rule.json` (fresh ids/timestamps). The Tutor team integrates against this from hour one — tell Henry when it's up so he can send them the URL.
- Write `app/API.md`: the routes, an example twin, and a 10-line Python client for the Tutor team.

### Step 3 (by H+6): the viewer — `app/static/index.html` (single file, no build step)
- Left: the dewarped page with every line box drawn; color by confidence (thin outline: green ≥ 0.8, amber 0.6–0.8, red < 0.6), crossed-out lines hatched, uncertain spans underlined in the transcription. Line order numbers in the margin.
- Right: the transcription list in reading order, rendered with KaTeX (`cdn.jsdelivr.net`), each with confidence and status. Lines from `changes.added` slide in highlighted.
- Click a line → panel with the line crop, the context crop, both readings (page pass / line pass), the re-read decision, and latency for that line. (Clickable overlay idea from the LoBE-GS poster.)
- Top bar: source (Pi/webcam/upload), quality issues as chips ("glare", "blur"), Snapshot button, Watch toggle, Upload button.
- Dev drawer (`L` key): per-stage latency from `/events` status messages and `runtime/telemetry.jsonl`, red when over `budget_ms`.
- Readable on a projector: system font, high contrast, no heavy decoration.

### Step 4 (start at H+2, keep going): the test set — LESS-style pre-label → correct
- Henry photographs real pages into `eval/testset/<n>.jpg`: 15–20 pages of his own handwriting with calculus/algebra derivations, **each containing at least one deliberate mistake**, plus crossed-out lines, a fraction-heavy page, a pencil page, a glare page.
- `eval/prelabel.py`: run the pipeline on each page and write `eval/testset/<n>.truth.json` (lines with bbox, latex, status) as a starting point.
- `eval/label_helper.py`: a tiny local web page (served by the same FastAPI app at `/label`) showing the page, each line box, and an editable LaTeX field with live KaTeX preview; Henry fixes the truth in about a minute per page. Add a checkbox per line `planted_error` and the planted mistake's description. (The LESS poster's loop: model pseudo-labels → correction/filtering → trusted data. We use it to build ground truth fast, not to train.)

### Step 5 (by H+8): metrics — `eval/run_eval.py`
Per run, over the test set:
- **Page detection**: fraction of pages with `quality.ok` and corner error < 2 % (truth corners optional; else visual check).
- **Line detection**: precision/recall of line boxes at IoU ≥ 0.6; merged-line count; reading-order accuracy.
- **Transcription**: line exact match after `normalize_latex`; character error rate on normalized LaTeX; crossed-out accuracy.
- **Planted-error preservation** (the metric that matters most): fraction of `planted_error` lines whose transcription is NOT mathematically equivalent to the corrected version and IS equivalent to the truth (use SymPy where both parse; otherwise exact normalized match). Any autocorrection is listed by name in the report.
- **Calibration**: accuracy of lines bucketed by reported confidence (≥ 0.8, 0.6–0.8, < 0.6) — high-confidence lines must actually be right.
- **Latency**: median and p90 snapshot→twin, and incremental new-line time.
Append one row to `eval/history.csv` with a `note` describing what changed. `eval/plot_history.py` draws the accuracy-journey chart (TTYSC poster) to `eval/accuracy_journey.png`, plain styling, each point annotated with its note. Run at every checkpoint; keep rows that got worse.

## Done when
- Mock mode serves the Tutor team from hour one; real mode works with the Pi and with uploads.
- The demo page plays end to end in the viewer: write → hand leaves → lines appear with correct boxes, the wrong line preserved verbatim, crossed-out line hatched.
- `eval/history.csv` has ≥ 4 rows; the chart exists; planted-error preservation is reported on every row.
