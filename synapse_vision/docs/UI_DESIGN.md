# UI_DESIGN — the page twin becomes the hero

> Owner: T6 (UI). Written 2026-10-24 (H+9). Scope: `../frontend/src`, `../frontend/index.html`. Design language is
> Micha's "cozy stationery" (cream canvas, paper cards, butter + sage accents, olive ink, Pip). This note says what
> stays, what changes, and the layout of the new notebook page. The pitch is **fine-grained handwriting recognition**;
> every decision below serves one goal: a judge 3 m from a projector sees *our reading of the page*, line by line.

## 1. What stays (do not touch)

- **Tokens** in `src/index.css` `@theme`: cream / paper / paper-deep / butter / butter-deep / sage / sage-deep /
  sage-ink / olive / honey / clay. Fonts: Nunito (body), Fredoka (display), system mono. No new font files.
- **Motifs**: `.sheet` (white paper with a 5 px paper-deep offset print), `.ruled` (sage ruling every 28 px),
  `.sticky-note` (butter note with a hard olive shadow), `.scribble` underline, dotted-grid body texture, hard
  1 px olive borders, square corners (`rounded-sm` at most), the notebook "index tab" on the dashboard sheet.
- **Pip** (`PipPet.jsx`, `VoicePanel.jsx`) exactly where it is: under the live camera on the notebook page.
- **Copy voice**: lowercase display titles ("a quiet place to study."), short sentences, "Pip" as the tutor.
- **Camera block**: Live camera card, Start/Stop, source select, the "preview only — nothing is recorded" line.
- **Data layer**: `src/services/api.js` stays the only `fetch`; new reads (`GET /twin/{id}`) are added there.

## 2. What changes

| Area | Today | New |
|---|---|---|
| Hierarchy on the notebook page | Camera 1.7 fr left, a plain still + step list right; recognition is invisible | Camera + Pip stay on top; below them a full-width **Recognition View** that becomes the largest element once a result exists |
| Recognition | Step list: icon + label in 13 px mono | **PageTwin** (dewarped page with coloured line boxes) + **Line ledger** (KaTeX per line, confidence meter, status chip, strike for crossed-out) + **Line inspector** side sheet (crops, both readings, re-read candidates, raw latex) |
| Colour meaning | clay used for both "issue" and camera "live" | **One accent for actions (butter)**, **sage = correct**, **new `--color-ink-red` (#b23a2e) only for `error` and crossed-out hatching**, olive/40 dashed = unclear or confidence < 0.6. Clay remains for system errors (offline banner, failed requests) |
| Typography | Card titles 18 px, body 12–14 px | Page titles 28–32 px Fredoka (still lowercase), section titles 22 px, body **≥ 15 px**, ledger latex 20–22 px, every number `tabular-nums` |
| Dashboard "your page" | live video or "camera off" | latest **PageTwin thumbnail with boxes**; stat row gains **lines read today** and **errors caught** |
| Loading | four grey skeleton bars | **skeleton ruled lines** that fill in top-down; after 20 s "still reading your page…" (budget is 60 s) |
| Empty state | "Nothing analyzed yet" sentence | an **empty ruled page** with one line of copy. Never blank |
| Latency | not shown | quiet footnote "read in 10.7 s" from `latencyMs.bridge_total` |

Principles: the page twin is the hero · legible at 3 m (nothing important under 15 px, boxes ≥ 2 px stroke) · one
accent for actions · the planted error must *look* wrong at a glance without touching the verbatim label · keep the
paper.

## 3. Notebook page — wireframe (≥ 1280 px)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ peek at my notebook                                       [● live camera on]         │  32 px title
├──────────────────────────────────┬───────────────────────────────────────────────────┤
│  LIVE CAMERA (sheet)             │  ■ Pip  talk to Pip   Ready → Listening → …        │  unchanged
│  ┌────────────────────────────┐  │  [ Hold to talk ]  [ or type a question… ] [Ask]  │  (Micha's)
│  │  ● LIVE      video         │  │                                                   │
│  └────────────────────────────┘  │  ┌──────────────── sticky note ────────────────┐  │
│  camera ▾ [Default webcam]  Stop │  │  Analyze my page      ✦                     │  │  butter CTA
│  preview only — nothing recorded │  │  one still, read line by line               │  │
│                                  │  └─────────────────────────────────────────────┘  │
├──────────────────────────────────┴───────────────────────────────────────────────────┤
│ 01 — the page twin         read in 10.7 s · 4 lines · 1 error · 1 crossed out         │  Eyebrow + footnote
│ ┌─────────────────────────────────────┐ ┌──────────────────────────────────────────┐ │
│ │  PAGE TWIN (dewarped image)         │ │  LINE LEDGER (ruled card)                │ │
│ │  ┌0───────────────┐ dashed olive    │ │  0  f(x)=x^2 sin x        ▮▮▮▮▮▮░░ .60 ? │ │
│ │  │ f(x)=x² sin x  │                 │ │     low confidence; may be a misread      │ │
│ │  └────────────────┘                 │ │  1  f'(x)=2x·cos x        ▮▮▮▮▮▮▮▮ .92 ✕ │ │  ink-red row
│ │  ┌1───────────────┐ ink-red 3 px    │ │     Re-check this: the derivative of …    │ │
│ │  │ f'(x)=2x·cos x │ ◀ selected      │ │  2  ~~= 2 cos x~~          ▮▮▮▮▮▮▮░ .81 — │ │  struck, hatched
│ │  └────────────────┘                 │ │     crossed out                           │ │
│ │  ╱╱╱2╱╱╱╱╱╱╱╱╱╱╱╱  hatch (crossed) │ │  3  f'(0)=0               ▮▮▮▮▮▮▮▮ .95 ✓ │ │  sage
│ │  ┌3───────────────┐ sage 2 px       │ │                                          │ │
│ │  └────────────────┘                 │ │  [topics: Product rule · Derivatives…]   │ │
│ └─────────────────────────────────────┘ │  summary sentence (15 px)                │ │
│                                         │  ┌─ sticky note: hints ───────────────┐  │ │
│                                         │  │ • Write the product rule …          │  │ │
│                                         │  └─────────────────────────────────────┘  │ │
│                                         └──────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────────┘
          ┌─────────── LINE INSPECTOR (side sheet, slides in from the right) ───────────┐
          │ line 1 · error · confidence .92                                       [✕]  │
          │ [ crop image ]                [ context crop, target outlined ]             │
          │ page pass   f'(x)=2x\cdot\cos x   ┐                                        │
          │ line pass   f'(x)=2x\cdot\cos x   ┘ ✓ agree          (✕ disagree → re-read) │
          │ re-read zoom [img]   candidates: …                                         │
          │ raw latex  ┃ f'(x)=2x\cdot\cos x ┃ [copy]                                   │
          └─────────────────────────────────────────────────────────────────────────────┘
```

Below 1280 px the twin and the ledger stack (twin first). Hover or click a box ⇄ the ledger row highlights and
scrolls into view; click opens the inspector. Keyboard: ↑/↓ move the selection, Esc closes the inspector.

Box styling on the twin (in dewarped-image pixels, scaled to the rendered size with a `ResizeObserver`):

| line | stroke | fill | number badge |
|---|---|---|---|
| correct | sage-deep 2 px | sage 12 % | sage-ink on sage |
| error | ink-red 3 px | ink-red 10 % | cream on ink-red |
| unclear / confidence < 0.6 | olive 40 % dashed 2 px | none | olive on paper |
| crossed_out | olive 50 % 2 px | ink-red diagonal hatch (`repeating-linear-gradient`, 45°) | olive on paper, struck |
| selected | + butter-deep 3 px outline, 2 px offset | | |

## 4. Component list

`src/components/recognition/`
- `PageTwin.jsx` — image + absolutely positioned overlay; props `{ imageUrl, image:{width,height}, lines, selectedId, onSelect, compact }`. Uses `useElementSize` to scale.
- `LineBox.jsx` — one box (status → classes above), order badge, hover/click, `aria-label`.
- `LineLedger.jsx` — ruled card; rows via `LedgerRow.jsx` (order, `Latex`, `ConfidenceMeter`, `StatusChip`, note).
- `Latex.jsx` — KaTeX render (`katex` npm, `throwOnError:false`); falls back to a mono `<code>` with the verbatim string.
- `ConfidenceMeter.jsx` — 64 px bar + `.92` in tabular figures; colour follows the status, not the number.
- `StatusChip.jsx` — correct / error / unclear / crossed out; also used by the inspector header.
- `LineInspector.jsx` — side sheet (`position: fixed`, right); crop, context crop, readings (page vs line, agree mark), re-read zoom + candidates, raw latex with a Copy button.
- `SummaryStrip.jsx` — topics chips, summary sentence, hints sticky note, latency footnote, line/error counts.
- `RecognitionView.jsx` — composes the above; owns selection state; loading (skeleton ruled lines, 20 s message) and empty (ruled page + one line) states.
- `useTwin.js` — given an analyze result, merges `steps[]` with `GET /twin/{snapshotId}` (bbox, crops, readings, image size); uses step-level `bbox/cropUrl/contextCropUrl/readings` when the bridge already sends them.

Touched elsewhere: `services/api.js` (+`getTwin(id)`, +`getLatestTwin()`), `context/StudyDataProvider.jsx`
(load the latest twin on page load so the notebook and dashboard are never empty when a twin exists),
`pages/NotebookObserver.jsx` (new layout), `pages/Dashboard.jsx` (twin thumbnail + two stats), `index.css`
(`--color-ink-red`, `.hatch`, `.ruled-lg`, KaTeX import, type scale), `index.html` (title), `package.json` (katex).

## 5. Type scale (projector at 3 m)

| role | size / weight | font |
|---|---|---|
| page title (lowercase) | 32 px / 500 | Fredoka |
| section title | 22 px / 500 | Fredoka |
| eyebrow | 11 px / 700 / tracking .18em uppercase | Nunito |
| body | 15 px / 400, line-height 1.6 | Nunito |
| ledger latex | 21 px (KaTeX `\displaystyle` off) | KaTeX fonts |
| ledger number / confidence | 15 px tabular | Fredoka / Nunito |
| footnote | 13 px / olive 60 % | Nunito |

Light only (`color-scheme: light`). Tested at 1280×720 and 1920×1080.
