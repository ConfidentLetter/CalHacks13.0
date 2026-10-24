# T1 — Capture: a clean, flat, trustworthy page image

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

You are T1. You own `capture/` and `hardware/`. Everything downstream reads the image you produce, so your job is to make it **flat, evenly lit, sharp, and honest about its own quality**. A bad photo must never silently become a confident transcription: when the photo is bad, you say so in `quality.issues` and downstream lowers confidence or skips.

## Build in this order

### Step 1 (by H+1): stubs + synthetic test bench
- Every T1 function in `contracts/interfaces.md`, exact signatures. `get_snapshot` with `source="upload:<path>"` copies that file into `runtime/snapshots/` (this path works from minute one). `detect_and_dewarp` stub returns the input as `dewarped_path` with `quality.ok=True`. `tile` returns one tile.
- `capture/tests/synth.py`: render a synthetic "photo of a page": a white sheet (A4/Letter aspect) with lines of text and simple math drawn with OpenCV fonts (use `cv2.FONT_HERSHEY_SCRIPT_SIMPLEX` for a handwritten feel), optional ruled lines, placed on a darker desk texture, random perspective (±15°), rotation (±10°), uneven lighting (a gradient + a bright glare blob), slight blur, JPEG compression. Return image + ground-truth page corners. This lets you reach high accuracy before any real photo exists.

### Step 2 (by H+3): sources and the stability trigger
- `capture/source.py`:
  - `pi`: HTTP GET `config capture.pi_url` (the Pi runs `hardware/pi_snapshot_server.py`), timeout 5 s, one retry.
  - `webcam`: OpenCV `VideoCapture(capture.webcam_index)`, request the highest resolution the camera supports (try 3840×2160, then 1920×1080), discard 5 warm-up frames, lock exposure/white balance if supported.
  - Save as `runtime/snapshots/<timestamp>.jpg`; log ms.
- `wait_for_stable(timeout_s)`: poll small frames (`/preview.jpg` on the Pi, or a downscaled webcam frame) at ~5 fps. State machine STILL → CHANGING (mean abs diff on 160×120 gray > `capture.change_threshold`) → STILL_AGAIN after `capture.stable_seconds` with diff below half the threshold → take one full-resolution snapshot and return it. This avoids photographing a hand mid-stroke.
- Hand/pen-in-frame check on the final snapshot: skin-tone mask (YCrCb range) touching the page area > 3 % → `hand_in_frame` issue. Cheap and good enough.
- `python -m capture.source --list` tries webcam indices 0–5 and the Pi URL, saves one frame from each to `runtime/debug/`, prints which work.

### Step 3 (by H+6): page detection and dewarp — `capture/page.py`
1. Downscale to ~1000 px long side for detection. Convert to gray, blur, Canny + morphological close; find the largest 4-point convex contour (`approxPolyDP`) whose area ≥ `page.min_page_area_fraction` of the frame. Also try an adaptive-threshold variant of the same search; keep the candidate with the best rectangularity score.
2. If no page quad is found and `page.use_aruco_fallback`, look for 4 ArUco markers (DICT_4X4_50, ids 0–3 TL/TR/BR/BL) taped at the paper or desk-mat corners.
3. Order corners, compute the homography, warp to portrait with long side `page.output_long_side`, aspect from the detected quad (snap to Letter 8.5×11 or A4 if within 3 %).
4. Lighting normalization: divide the gray image by a heavily blurred copy of itself (background flattening), then CLAHE. Keep a color version too (blue/red ink matters to T2's crossed-out logic). Save both: `*_dewarped.jpg` (color) and `*_dewarped_gray.png`.
5. Quality gate: blur = variance of Laplacian on the dewarped gray (below `page.blur_threshold` → `blur`); glare = fraction of near-saturated pixels inside the page (above `page.glare_fraction_max` → `glare`); `too_dark`, `partial_page` (quad touching frame edge), `skew_extreme` (any corner angle off by > 35°), `hand_in_frame`, `no_page`. `ok` = no blocking issues (`no_page`, `partial_page`, `blur`, `hand_in_frame`); `glare` alone is a warning.
6. Never raise. On `no_page`, return the original frame as `dewarped_path` with `ok=False`.
- Synthetic tests: corner error < 1.5 % of page diagonal on ≥ 95 % of 100 generated images; blur and glare flags fire on images built to have them and not on clean ones.

### Step 4 (by H+7): tiling
`tile(dewarped_path, max_tiles)`: horizontal bands with roughly equal ink pixel counts (from the binarized gray), each overlapping its neighbours by 60 px, never cutting through a band of dense ink if a quieter row is within 40 px. Save to `runtime/tiles/`. T3 uses tiles for the full-page reading pass so small handwriting survives model downscaling.

### Step 5 (H+7 → H+14): real camera
- Henry mounts the camera; take 10 real snapshots from `eval/calibration/`. Tune detection and the quality gate there. Record every tuning change with before/after numbers in your NOTES (T4 puts them in the accuracy journey).
- Document the working mount in `hardware/README.md`: height, angle, lighting, which source worked, the Pi hostname/IP.

## Pitfalls
- Notebook pages on a white desk have weak edges: a dark desk mat or the ArUco fallback fixes it — tell Henry if you need either.
- Spiral-bound or curled pages: a homography flattens only planar pages. Ask Henry to keep the sheet flat (clip it); don't try to model curl.
- Phone/webcam autofocus hunting gives intermittently blurry frames; the blur gate plus a single automatic retake is the fix.

## Done when
- Synthetic accuracy targets met; real snapshots of the demo page dewarp cleanly with `quality.ok=True` under the demo lamp.
- `wait_for_stable` never returns a frame with a hand over the page in 10 trials.
- `runtime/debug/page_<snapshot>.png` shows detected corners, the dewarped page and the quality numbers side by side.
