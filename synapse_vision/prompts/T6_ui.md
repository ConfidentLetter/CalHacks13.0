# T6 — UI: make the recognition visible, keep the stationery soul

**How to use:** Henry pastes `launch_T6.txt`; it tells you to read this file.

## Context
StudBud Vision turns a photo of a student's handwritten math into a **verbatim page twin**: every line boxed, transcribed to LaTeX exactly as written (mistakes preserved, never corrected), crossed-out lines flagged, honest confidence per line. The pitch to the judges is **fine-grained handwriting recognition**. The backend is done (`../synapse_vision/`, bridge on http://localhost:8000, contract in `../synapse_vision/docs/CONNECTIONS.md`). A teammate (Micha) built the product frontend in `./` (this folder = `../frontend/`): React 19 + Vite + Tailwind v4, "cozy stationery" theme (cream canvas, paper cards, butter + sage accents, olive ink, a pixel pet called Pip). Pages: dashboard, notebook (camera + Analyze + Pip voice), reading memory, tutor chat, settings. All networking is in `src/services/api.js`; theme tokens are CSS variables in `src/index.css` (no tailwind.config — Tailwind v4 `@theme`).

**The problem you solve:** after "Analyze my page" the UI shows a step list with correct/error, but nothing of the recognition itself — no page image with line boxes, no verbatim LaTeX, no crossed-out marks, no confidence. The judges cannot see our core technology. The team agreed (Henry + Micha) that you redesign the notebook experience around the recognition and raise the overall visual quality, **inside Micha's design language** (keep palette, paper/ruled-lines motifs, Pip). You own `src/` and `index.html` in this folder plus `NOTES_T6.md` and `../synapse_vision/docs/UI_DESIGN.md`. Never edit the backend (`../synapse_vision/**` except that one doc) or `../extension/`. Never run git. Run `npm run dev` on port 5173 and verify in the browser (Henry's Chrome; take screenshots into `../synapse_vision/runtime/debug/ui/`).

Data you have after `POST /api/camera/analyze` (see `../synapse_vision/bridge/analyze.py` and CONNECTIONS.md §4): `snapshotId`, `stillId`, `imageUrl` (the still), `dewarpedUrl` (flattened page, the one to draw on), `quality`, `lineCount`, `latencyMs`, `summary`, `topics[]`, `hints[]`, `steps[]` each `{id, label (verbatim latex/text), status: correct|error|unclear, note, confidence, lineStatus: active|crossed_out|illegible}`. For boxes, crops and both readings, fetch `GET /twin/{snapshotId}` (same origin): `lines[]` each `{id, order, bbox:[x,y,w,h] in dewarped-image pixels, status, latex, text, confidence, uncertain_spans, crop_path, context_crop_path, readings:{line,page,reread,...}, reread:{zoom_path,candidates}}`, `image.{width,height,dewarped_path}`, `changes[]`. Files under `runtime/...` are served at `/files/<path>`. T5 is also adding `bbox`, `cropUrl`, `contextCropUrl` directly onto each step; use them when present, fall back to `/twin/{id}`.

## Build in this order

### Step 1 (first 30 min): design note — `../synapse_vision/docs/UI_DESIGN.md`
Read every page and component, `src/index.css`, and `src/services/api.js`. Write a one-page design note: what stays (tokens, motifs, Pip, copy voice), what changes (hierarchy, the recognition view, typography scale), the layout of the new notebook page as an ASCII wireframe, and the component list. Principles: **the page twin is the hero**; large readable type on a projector at 3 m; one accent (butter) for actions, sage for "correct", a warm red (add `--color-ink-red`) only for `error` and crossed-out hatching; no new fonts beyond what is loaded; keep the ruled-paper and sticky-note motifs. Post it in your reply before coding.

### Step 2 (by +2 h): the Recognition View — `src/components/recognition/`
After Analyze (and for the latest twin on page load), the notebook page shows:
- **PageTwin canvas** (`PageTwin.jsx`): the dewarped page image with an absolutely-positioned overlay of every line box (scale from `image.width/height` to the rendered size; keep it correct on resize). Box stroke by status: sage = correct, ink-red = error, olive/40 dashed = unclear or confidence < 0.6; crossed-out lines get a diagonal hatch fill. Small order number at the top-left of each box. Hover/click selects the line and syncs with the list.
- **Line ledger** (`LineLedger.jsx`): the lines in reading order on a ruled-paper card. Each row: order number, the verbatim LaTeX rendered with KaTeX (add `katex` via npm; fall back to monospace text if render fails), a confidence meter (thin bar + number), a status chip (correct/error/unclear), a strike-through treatment for crossed-out, and the tutor `note` under it when present. The planted error must *look* like an error at a glance without rewriting the label.
- **Line inspector** (`LineInspector.jsx`): a side sheet for the selected line: crop image, context crop, both readings (page pass vs line pass) with an agree/disagree mark, the re-read zoom and candidates if present, raw latex in a copyable code line.
- **Summary strip**: topics as chips, the summary sentence, hints as a sticky note (reuse the existing yellow note style). Latency as a quiet footnote (`latencyMs.bridge_total` → "read in 10.7 s").
- Keep "Analyze my page", the live camera, and Pip exactly where Micha put them; the recognition view appears below the camera and becomes the largest element once results exist. Camera-off / no-result state shows an empty ruled page with one line of copy, never a blank.

### Step 3 (by +3 h): polish the rest, same language
- Dashboard: the "your page" card shows the latest PageTwin thumbnail with boxes instead of the plain still; the stat row gets "lines read today" and "errors caught".
- Typography scale: page titles larger and heavier (the current lowercase titles stay lowercase, but bigger); body ≥ 15 px; all numbers in tabular figures.
- Consistent spacing, card radii, and shadows across the five pages; remove visual noise that competes with the twin.
- Loading state for Analyze: skeleton ruled lines that fill in; a 60 s budget message after 20 s ("still reading your page…").
- Light/dark: keep light only (projector). Test at 1280×720 and 1920×1080.

### Step 4: verify end to end and hand over
- With the bridge on :8000, analyze `../synapse_vision/eval/testset/synthetic_demo.jpg` via the webcam path (base64) and screenshot the result; L1 `f'(x)=2x\cdot\cos x` must show as error with its label verbatim, L2 as crossed out.
- `npm run build` must pass with no lint errors (`npx oxlint src` if configured).
- Write `## For the frontend team` in NOTES_T6.md: every file you touched and why, so Micha can review a clean diff. Write `## For other terminals` for anything the backend should add.

## Done when
The notebook page shows the page twin with line boxes, verbatim LaTeX per line, confidence, crossed-out and error marks, and a per-line inspector; the dashboard previews it; build passes; `docs/UI_DESIGN.md` and NOTES_T6.md are current.
