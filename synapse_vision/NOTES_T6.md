# NOTES_T6 — UI (recognition view in Micha's frontend)

**Done:** Steps 1–4 + H+11 relay (Desk View camera default: picker pre-selects a device whose label contains 桌上视角 / "Desk View" unless the student chose one explicitly, choice remembered in `localStorage` `synapse.camera.device`, "desk view" chip by the picker, one-line hint under it when no Desk View camera is selected). `docs/UI_DESIGN.md` (design note). `../frontend/src/components/recognition/` — PageTwin (dewarped page + percentage-positioned line boxes, "writing / page / still" views), LineLedger (KaTeX per line, confidence meter, status chip, hand-struck crossed-out, tutor note), LineInspector (side sheet: crop, context crop, page-pass vs line-pass with agree/disagree, re-read zoom + candidates, raw LaTeX + copy, ↑/↓/Esc), SummaryStrip (topics, summary, hints sticky note, "read in 17.0 s" footnote). Notebook page rebuilt around it (camera card, Pip and "Analyze my page" untouched); dashboard shows the latest twin with boxes + "lines read today" / "errors caught"; type scale raised (body 15 px, titles 28 px, tabular figures). Verified live on :8000 with `eval/testset/synthetic_demo.jpg` through `POST /api/camera/analyze` (webcam shape, base64): **L1 `f'(x)=2x\cdot\cos x` shows as error with the label verbatim, L2 `=2\cos x` hatched + struck as crossed out**; real webcam Analyze from the UI round-trips (face still → honest "no lines were read"); loading skeleton and 20 s "still reading" message exercised. `npm run build` passes; `oxlint` has no errors (only Micha's pre-existing warnings). Screenshots: `runtime/debug/ui/`.
**Next:** nothing blocking. Nice-to-haves: the "writing" zoom could follow the selected line; a "judge this page" button for an unjudged latest twin (today it says "transcribed only — press Analyze").
**Blocked:** nothing.

## For the frontend team
Every file I touched, so the diff reviews cleanly. Nothing outside `src/`, `index.css`, `package.json`/`package-lock.json` (katex 0.16.22).

New — `src/components/recognition/`
- `twinModel.js` — pure helpers: analyze `steps[]` + `GET /twin/{id}` → one line model (`toneOf`: error / correct / crossed / unclear / read), `buildRecognition`, `inkRegion` (zoom-to-writing window), `fileUrl` (`runtime/...` → `/files/runtime/...`), `readInSeconds`. Labels are passed through verbatim; nothing is rewritten.
- `useTwin.js` — fetches `/twin/{snapshotId}` (bbox, crops, both readings, image size); skips the request when the latest twin is already in hand.
- `PageTwin.jsx` + `LineBox.jsx` — dewarped image with boxes in percentages of the image (exact at any size, no re-measure); `region` prop shows only the ink area; `compact` for the dashboard thumbnail.
- `LineLedger.jsx` + `LedgerRow.jsx` — ruled card, 48 px rules, one row per line; hover/click syncs with the boxes.
- `Latex.jsx` — KaTeX (`throwOnError:true` in a try, so a string KaTeX can't parse falls back to monospace, still verbatim).
- `ConfidenceMeter.jsx`, `StatusChip.jsx` — shared by ledger, inspector, twin badges.
- `LineInspector.jsx` — portal side sheet (`.sheet` paper, slide-in).
- `SummaryStrip.jsx`, `RecognitionView.jsx` — composition, loading skeleton (`.ink-fill` ruled lines, "still reading your page… N s of a 60 s budget" after 20 s), empty ruled page copy.
- `src/hooks/useElementSize.js` — ResizeObserver hook (PageTwin fit).

Changed
- `src/utils/camera.js` (new) — `isDeskView(label)`, `findDeskView(devices)`.
- `src/context/CameraProvider.jsx` — H+11: `refreshDevices` auto-selects the Desk View camera when nothing was chosen explicitly (labels appear after the first permission, so a running default webcam restarts once on Desk View); `setSource` marks the choice explicit; exposes `isDeskView`, `deskViewAvailable`. Saved choice (`synapse.camera.device`) unchanged.
- `src/services/api.js` — `resolveUrl` exported; `getTwin(id)`, `getLatestTwin()` (ignores `_fallback` mock twins). Still the only `fetch`.
- `src/context/StudyDataProvider.jsx` — `analysis` keeps `startedAt`; the last judged result is cached in `localStorage` (`synapse.analysis.v1`, small JSON, no image data) so a reload keeps the twin judged; `latestTwin` loaded on start (`GET /twin/latest`); exposes `recognition` (built model), `recogStats` (`lines read today` / `errors caught`, `synapse.recognition.stats.v1`), `refreshLatestTwin`. On an analyze error the previous result stays on screen under the error.
- `src/pages/NotebookObserver.jsx` — camera card unchanged; right column = Analyze button (same place) + small still + SummaryStrip + "↓ see every line"; full-width `RecognitionView` below. Grid 1.25fr/1fr.
- `src/pages/Dashboard.jsx` — stat row gained `lines read today`, `errors caught`; the notebook sheet shows the latest PageTwin (with boxes, zoomed to the writing) instead of the plain video when a twin exists; header shows "4 lines · 1 error · 1 crossed out".
- `src/components/layout/Topbar.jsx` — page title 28 px Fredoka (still lowercase); notebook subtitle copy.
- `src/components/ui/Card.jsx` — CardHeader title `text-xl`, subtitle 13 px.
- `src/index.css` — `--color-ink-red` (#b23a2e, only for wrong lines + crossed-out hatch; clay stays for system errors), KaTeX stylesheet import, type scale (`--text-xs` 13 px, `--text-sm` 15 px, body 15 px / 1.6, `tabular-nums` on body), utilities `.ruled-lg`, `.hatch`, `.struck`, `.ink-fill`, `.slide-in-right`, `.latex`.
- `package.json` — `katex ^0.16.22`.

Untouched: `index.html` (title/fonts fine), Pip, VoicePanel, LiveFeed, camera provider, extension bridge, tutor/reading/settings pages (they only pick up the global type scale).

## For other terminals
- **T5 (bridge):** the running :8000 process does **not** send `bbox` / `cropUrl` / `contextCropUrl` / `readings` on steps yet (`tutor.step_base` exists in the file but the analyze response I got at 14:13 had only `id,label,status,note,confidence,lineStatus`). The UI falls back to `GET /twin/{snapshotId}` so everything shows; when you restart with the step extras live the UI uses them automatically (twin still wins for geometry). No action needed unless `/twin/{id}` ever goes away.
- **T5:** `GET /twin/latest` in real mode before any snapshot returns the mock flagged `_fallback` — the UI hides it (never shown as the student's page), as CONNECTIONS §4.17 intends.
- **T3 (FYI):** the inspector shows `readings.page`, `readings.line`, `readings.reread`, `notes`, `reread.zoom_path`, `reread.candidates{A,B}` and `uncertain_spans` straight from the twin. On the synthetic page L0 came back `f(x)=x^{\wedge}2\sin x` at 0.55 → shown as unclear with the note, never corrected.
- **T4/T1 (observation):** the latest real twin before my run (`snap_20261024T204033_9a971a`, 13:40) is a hand-held sheet: 65 lines, 54 illegible, `quality.issues=[no_page]`. The UI shows it honestly (footnote "page quality: no_page") — for the demo, lay the page flat so the twin has 4 clean lines.

## How to run / verify
- Bridge on :8000 (already running), `cd ../frontend && npm run dev` → http://localhost:5173/#/notebook. Start camera → Analyze my page. Without a camera: the latest stored twin is shown on load (unjudged until Analyze).
- Build: `npm run build`; lint: `npx oxlint src`.
- Screenshots (2026-10-24 14:08–14:14): `runtime/debug/ui/notebook_top_1280.jpg`, `notebook_twin_1280.jpg`, `notebook_twin_1920.jpg`, `notebook_twin_writing_1920.jpg`, `dashboard_twin_1920.jpg`.

## Log
- H+11: Desk View relay adapted. Verified with a simulated "MacBook Air桌上视角相机" device (Desk View app was not running on this Mac): picker pre-selects it, chip shows, hint hides; saved choice is only written on an explicit pick.
- H+9 (14:14): Steps 1–4 done, verified live (synthetic page L1 error verbatim, L2 crossed out; webcam round trip; skeleton; 1280 and 1920 layouts). Added zoom-to-writing view after seeing the tall dewarped page at projector scale.
- H+9 (13:5x): launched; read frontend + bridge surfaces; wrote UI_DESIGN.md; built recognition components.
