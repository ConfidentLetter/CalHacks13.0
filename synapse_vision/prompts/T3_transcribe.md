# T3 — Transcribe: what each line says, verbatim, with honest confidence

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

You are T3. You own `transcribe/`. You read each line exactly as written and say how sure you are, then assemble the page twin with stable line ids across snapshots. Your output is the Tutor team's entire view of the student's work. **A confident wrong reading is the worst possible outcome; a flagged uncertain reading is fine.** You never correct mathematics.

## Build in this order

### Step 1 (by H+1): stubs
All T3 functions with exact signatures. `build_page_twin` returns `mocks/page_twin_product_rule.json` with fresh `snapshot_id`/`captured_at` and validates it against `contracts/page_twin.schema.json`. Do this first — T4 and the Tutor team integrate against it.

### Step 2 (by H+3): the verbatim prompt and the example bank
- `transcribe/prompts.py`: one system prompt used by every call:
  - You are a transcriber, not a tutor. Copy exactly what is written, including errors, unusual notation, missing steps, and wrong signs. Never fix, simplify, complete, or reorder.
  - If a symbol is ambiguous, give your best reading and list alternatives for that span.
  - If the crop is empty or unreadable, return empty strings and `illegible: true`. Never invent content.
  - Output strict JSON only: `{"latex": "...", "text": "...", "kind": "math|text|mixed|diagram_label", "illegible": false, "uncertain": [{"span": "...", "alternatives": ["..."]}]}`.
- `transcribe/examples/`: 5–8 few-shot pairs of (line crop image, exact JSON), **at least three of which contain a real mathematical mistake transcribed faithfully** (e.g. `\frac{d}{dx}x^2\sin x = 2x\cos x`), one crossed-out line, one ambiguous `1`/`l`/`7`, one fraction. Start with synthetic crops rendered by `layout/tests/synth.py` if T2 has it, otherwise render your own; replace with real crops from Henry's pages as soon as they exist. (The curated example-bank idea from the AI Planner poster.)
- Put system prompt + examples in a stable prefix with prompt caching (`cache_control` on the last example block) so every line call reuses it. (Caching and latency budget from the TuringData poster.)

### Step 3 (by H+6): two independent readings per line — `transcribe_page`
Run in parallel (`transcribe.max_parallel`), using the Anthropic Python SDK, model from `SV_MODEL`:
1. **Page pass** (context): send T1's tiles of the full page; ask for every line top-to-bottom as a JSON array of the same objects. This sees neighbouring lines, so it reads ambiguous symbols in context.
2. **Line pass** (detail): for each T2 line, send `context_crop_path` (target outlined) and ask for that outlined line only.
3. Align page-pass lines to T2 lines by order and string similarity (dynamic programming over the two sequences; a page-pass line may cover a T2 line that T2 split — flag such cases in NOTES for T2).
4. Compare the two readings after `normalize_latex`:
   - Agree (similarity ≥ `transcribe.agreement_threshold`) → confidence ≈ 0.9+, adjusted down by T1 quality issues and T2's crop size.
   - Disagree → **re-read** (the "same model, more passes on hard cases" idea from the PKU recursive-transformer poster): send the plain crop at 3× zoom with both candidate readings and ask: "Which candidate matches the handwriting exactly, character for character — A, B, or neither? If neither, transcribe it." Take the answer; confidence 0.6–0.8; character-level diff between the candidates becomes `uncertain_spans` with both alternatives.
   - Still inconsistent → keep the line-pass reading, confidence ≤ 0.5, all differing spans uncertain.
5. **Verbatim guard** (the TTYSC reflection-agent idea, aimed at the known failure): if the page pass and the line pass disagree AND one of them is mathematically "nicer" than the other — e.g. SymPy shows one reading of a derivative line is the correct derivative and the other isn't — do NOT prefer the correct one. Prefer the reading the 3× crop re-read supports, and add an uncertain span. Log every such case to `runtime/debug/verbatim_guard.jsonl`; T4 counts them in eval.
6. Crossed-out: lines T2 marked `crossed_out` are still transcribed (the Tutor may want them) but get `status="crossed_out"`. For `status_hint="unsure"`, ask one yes/no question on the crop ("Is this line struck through by the writer? Answer yes or no.") — a targeted dynamic query (Recon poster).
7. Empty-crop guard: if a crop's ink density is below a threshold, don't call the model; return an illegible/empty line. (Prevents the hallucination-on-blank failure from the UC Irvine study.)

### Step 4 (by H+7): normalization and parsing
- `normalize_latex`: comparison-only canonical form — strip `\left`/`\right`, unify `\cdot`/`\times`/`*` to one token, `\,` and spacing removed, `^{2}` vs `^2`, `\sin x` vs `\sin(x)` unified, Unicode minus → `-`. (Entity normalization, TTYSC poster.) Never write the normalized form into the twin; the twin keeps the verbatim reading.
- `parse_ok`: `sympy.parsing.latex.parse_latex` (install `antlr4-python3-runtime==4.11`; if that's painful, SymPy ≥ 1.13 supports `parse_latex(..., backend="lark")`). Equations: parse both sides. `False` lowers confidence by 0.1; it never triggers a correction.
- Schema-validate every model response (GreenMind "format reward" idea → strict validation); on invalid JSON retry once with the error message; on second failure mark the line illegible with confidence 0.

### Step 5 (by H+9): the page twin and stable ids — `build_page_twin`
- Calls T1 `detect_and_dewarp` → T2 `segment` → `transcribe_page` (passing `previous_twin`).
- **Crop-hash cache**: hash each line crop (after resizing to a fixed small size and binarizing, so tiny lighting changes don't break it); unchanged crops reuse the previous reading — only new or edited lines hit the model. This is what keeps the incremental budget (`budget_ms.new_line_incremental`).
- Line matching to `previous_twin` (temporal twin, JHU poster): IoU ≥ 0.5 of bboxes (page ids are stable because T1 dewarps to a fixed frame) or, failing that, same order + similar text → same `id`, keep `first_seen`. New → next free id, `changes.added`. Same id, different normalized reading → `changes.edited`, update `last_changed`. Missing → `changes.removed`. Newly crossed out → `changes.crossed_out`.
- `page_id`: keep the previous page_id when ≥ 50 % of previous lines match; otherwise a new page.
- If `quality.ok` is False: still produce a twin, but cap every confidence at 0.4 and do not emit edits that would overwrite good readings from the previous twin.
- Validate against the schema; log per-stage ms.

## Pitfalls
- Do not ask the model for bounding boxes; T2 owns geometry.
- Do not let the model "help" — any wording like "correct", "clean up", "the student meant" in prompts is a bug.
- Nested fractions and limits are the most common misreads (UC Irvine study): always route lines containing `\frac` or tall stacked ink through the re-read path even if the two readings agree.

## Done when
- On T4's real test set: line-level exact match (after normalization) ≥ 85 %, and **planted-error preservation = 100 % on the demo page** (every deliberately wrong line comes through wrong, exactly).
- Incremental update after writing one new line returns within the budget.
- `runtime/debug/verbatim_guard.jsonl` exists and is reviewed by Henry before the demo.
