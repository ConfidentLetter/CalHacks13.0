# T2 — Layout: find every line, in order, and know which are crossed out

**How to use:** Henry pastes the launch message from `prompts/RUNSHEET.md`; it tells you to read this file.

## Project context (identical in all four prompts)

**Synapse** is an AI learning companion for college STEM students who do homework on paper. A camera (Raspberry Pi camera on a desk mount, or a webcam/phone) looks down at the student's paper. **This repo is the vision half only**: it turns a photo of handwritten work into a *page twin* — a structured, verbatim record of every line on the page, where it is, whether it is crossed out, and how confident we are in each reading. A separate Tutor team consumes the page twin to find the step where the student went wrong and coach them.

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

You are T2. You own `layout/`. You turn T1's flat page into an ordered list of line crops — the units T3 reads. If you merge two lines, T3 reads garbage; if you split one line, the Tutor sees a broken step; if you miss a crossed-out mark, the Tutor critiques work the student already abandoned. Precise boxes come from classical vision, never from a language model's coordinates.

## Build in this order

### Step 1 (by H+1): stubs
`segment` and `is_crossed_out` with exact signatures. `segment` on any input returns regions and lines matching the bboxes in `mocks/page_twin_product_rule.json`, cropping from the given image (pad if out of bounds). Write crops to `runtime/crops/<snapshot>/`.

### Step 2 (by H+4): synthetic test pages
`layout/tests/synth.py`: render flat dewarped pages (no perspective — T1 handles that) with 4–12 lines of handwriting-style text and math (OpenCV script fonts at varied sizes), uneven baselines (each line rotated ±3°, words jittered ±6 px vertically), superscripts and fractions stacked vertically (draw a numerator, a bar, a denominator — these are where line splitting goes wrong), one or two lines struck through with a pen-like stroke (single line, double line, or zig-zag), occasional margin notes. Return ground-truth line boxes, reading order and crossed-out flags.

### Step 3 (by H+6): line segmentation, classical (`layout.method: classical`)
1. Binarize the gray dewarped page (Sauvola, window ~ 1.5 × typical line height). Remove ruled lines: long thin horizontal components spanning > 60 % of the page width with height < 4 px (morphological opening with a wide horizontal kernel), and the left margin rule.
2. Connected components → filter specks (area threshold scaled to page size).
3. **Group components into lines by vertical overlap, not by a global projection profile** (handwriting baselines drift): sort components by x-center; greedily attach each to the line whose running y-band it overlaps most (≥ 40 % of the smaller height), allowing the band to drift with x. Then merge vertically stacked pieces into one line when they're horizontally overlapping and the gap is < 0.6 × median line height — this keeps fractions, exponents and limits on one line.
4. Split a "line" in two if it contains a horizontal whitespace gap > 3 × median character width AND the two parts' y-centers differ by > 0.5 line height (two columns of work).
5. Reading order: cluster into columns by x-gaps (most pages: one column + margin), then top-to-bottom within columns, left column first.
6. Regions: the first line(s) above a clear vertical gap, or starting with words like "Find", "Compute", "Prove", "Q", or a problem number, become `problem`; the main column is `work`; narrow far-right/left clusters are `margin`; large low-text-density blobs with long curves are `diagram` (don't send diagrams to line reading — give them one region crop).
7. Crops: `crop_path` = line bbox padded 12 px, upscaled 2× if height < 60 px; `context_crop_path` = the same horizontal span including `layout.context_lines` lines above and below, with the target line outlined by a thin colored rectangle so the reader knows which line to read. (Parent-context retrieval from the Wiwynn poster: a fragment is read better with its neighbours visible.)
- Synthetic targets: ≥ 95 % of ground-truth lines matched with IoU ≥ 0.6 and no merges, reading order exact on ≥ 95 % of pages.

### Step 4 (by H+8): crossed-out detection
`is_crossed_out(crop_path)`:
- Skeletonize the crop's ink. Look for a long, low-curvature stroke spanning > 60 % of the ink's width and passing through the vertical middle 60 % of the ink (Hough lines on the skeleton), or a dense zig-zag (many direction reversals in a band), or two parallel such strokes.
- Score = combination of span, straightness and overlap with other ink; threshold from config.
- Return (crossed, confidence). Between 0.4 and `layout.crossed_out_min_conf` → `status_hint="unsure"`: T3 asks the vision model a targeted yes/no question on that crop (the dynamic-query idea from the Recon poster).
- Tests on synthetic struck-through lines and on lines with fraction bars and underlines (must NOT trigger: a fraction bar spans only part of the line and has ink above and below it; an underline sits below the ink).

### Step 5 (optional, only if classical misses on real pages): `layout.method: doctr`
Use `python-doctr`'s text detection model (pretrained `db_resnet50`) to get word boxes, then run your step-3 grouping on word boxes instead of components. Pick whichever method scores better on T4's real test set; record both numbers in NOTES.

### Step 6 (H+8 → H+14): real pages
Tune on Henry's real pages in `eval/testset/` (T4 provides ground truth). Typical real-world problems: pencil (low contrast — lower binarization threshold), ink bleeding from the back of the page (ignore very faint components), graph paper (remove grid both directions).

## Pitfalls
- Never let an exponent or a denominator become its own line — that silently changes the math T3 reads.
- Equals signs aligned under each other across lines are a strong reading-order cue in derivations; keep columns intact.
- Write `runtime/debug/layout_<snapshot>.png` with every line box, its order number, and crossed-out lines hatched. You and Henry will tune from this picture.

## Done when
- Synthetic targets met; on real test pages ≥ 95 % of lines correctly boxed with no merged lines in the demo page.
- Crossed-out lines in the demo page are flagged; fraction bars and underlines never are.
