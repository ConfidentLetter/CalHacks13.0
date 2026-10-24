# CONNECTIONS — how the vision pipeline reaches the frontend

> Owner: T5 (Bridge). Written 2026-10-24 (H+6) from reading every module's public surface, `app/API.md`,
> `../docs/BACKEND_INTEGRATION.md`, `../docs/BACKEND_CONTRACT.md`, `../frontend/src/services/*.js` and
> `../extension/background.js`. Kept current as the seam changes (see § Change log at the bottom).

## 0. One-paragraph summary

A camera over the desk photographs the student's handwritten math. **T1 capture** finds and flattens the page,
**T2 layout** finds the lines, **T3 transcribe** reads every line *verbatim* (mistakes preserved) with an honest
confidence and assembles a schema-validated **page twin**, and **T4 app** serves twins over HTTP/WebSocket on
port 8000 (`/snapshot`, `/upload`, `/twin/*`, `WS /events`, viewer `/`). Micha's **frontend** (`../frontend`, React
on :5173) and **Chrome extension** (`../extension`) speak a different contract: `http://localhost:8000/api/*`
(status, camera, analyze, reading memory, chat, Pip tutor). **T5 bridge** is the adapter in between: one process
(`bridge.server:app`) that imports T4's app, adds CORS and an `/api` router, and maps every frontend endpoint to
the vision functions — plus the only place where the student's work is *judged* (the tutor layer), always quoting
the verbatim twin.

## 1. Modules

### T1 — `capture/` (snapshot, page detection, dewarp, quality, tiles)
Entry points: `capture.get_snapshot(source) -> str` (pi | webcam | upload:<path>; writes `runtime/snapshots/<ts>.jpg`,
repo-relative), `capture.wait_for_stable(timeout_s) -> str | None` (STILL→CHANGING→STILL state machine at 5 fps on a
160×120 preview), `capture.detect_and_dewarp(path) -> dict` (`{dewarped_path, width, height, homography, quality:{ok,
issues, blur_score, glare_fraction}, dewarped_gray_path, detection:{method, quad}}`; never raises; portrait, long side
2200), `capture.tile(dewarped_path) -> list[{path,bbox}]`. The webcam is a process-wide singleton
(`capture.source._webcam()` → `Webcam(index=cfg capture.webcam_index=2)`, `release_webcam()`); `Webcam.read()` has
no lock. Latency: grab ≈ 0–1 ms once open (opening + warm-up ≈ 1–2 s), `detect_and_dewarp` 120–210 ms
(telemetry `capture.page`). Config: `capture.*`, `page.*`.

### T2 — `layout/` (regions, lines, reading order, crossed-out)
Entry points: `layout.segment(dewarped_path) -> {regions:[{id,type,bbox}], lines:[{bbox, crop_path,
context_crop_path, status_hint∈active|crossed_out|unsure, ink_density, order, region_id}]}` (never raises; empty
layout on error), `layout.is_crossed_out(crop_path) -> (bool, score)`. Crops under `runtime/crops/<stem>/line_NNN.png`.
Latency: whole page 73–180 ms (`layout.segment`). Config: `layout.*`.

### T3 — `transcribe/` (verbatim reading, confidence, page twin)
Entry points: `transcribe.build_page_twin(snapshot_path, previous_twin=None) -> dict` (the full T1→T2→T3 chain;
since H+6 it **never raises**: on failure it returns a schema-valid twin with `quality.ok=False`, `lines=[]` and
`_error`), `transcribe_page`, `normalize_latex`, `parse_ok`. Each line: `id` (stable, `L3`), `order` (0-based),
`status ∈ active|crossed_out|illegible`, `latex` (verbatim), `text`, `confidence` 0–1, `uncertain_spans`, `parse_ok`,
plus extras `readings`, `reread`, `crop_path`, `latency_ms`. Two readings per line (page pass over tiles + line pass),
targeted re-read on disagreement; model = env `SV_MODEL` (default `claude-sonnet-5-5`), key `ANTHROPIC_API_KEY`,
60 s per-call SDK timeout. Latency: **8–17 s per page** when the API is quiet (last `/upload`: page 207 ms, layout
183 ms, transcribe 16.5 s, total 17.0 s), **25–33 s under API contention** (eval rows 5–6); one model round trip is
4–9 s. Incremental re-reads of ≤2 changed lines skip the page pass. Config: `transcribe.*`, `budget_ms.*`.

### T4 — `app/` (config, telemetry, server, store, viewer) and `eval/`
`app.config.get("a.b", default)` (hot-reloaded `config/vision.yaml`), `app.telemetry.log(stage, ms, **extra)` /
`timed(stage)` → `runtime/telemetry.jsonl`. `app.store` persists twins at `runtime/twins/<snapshot_id>.json` +
`latest.json`. `app.pipeline.build_twin` wraps T3 (mock twin flagged `_fallback` when `SV_MOCK=1` or T3 missing);
`pipeline.set_frame_provider(fn)` (H+6) lets an embedder supply stills so the camera is opened once. `app.server`
(FastAPI, importable without side effects): `GET /twin/latest|/twin/{id}|/twins`, `POST /snapshot[?source]`,
`POST /upload` (multipart `file`), `WS /events`, `GET|POST /watch`, `GET /status`, `GET /telemetry`,
`GET /files/<repo-relative path under runtime|mocks|eval>`, viewer `/`, label tool `/label`. H+6 additions for the
bridge: `await app.server.analyze(path, source) -> twin` (runs the pipeline, stores, broadcasts on `/events`) and
`app.bridge_api.{latest_twin, latest_snapshot, latest_frame_path, file_url}` (read-only, no camera, no model).
Errors never kill the server: a failed handler returns 500 `{"type":"status","stage":...,"error":...,"ok":false}`.

### Frontend — `../frontend` (React + Vite, :5173) and `../extension` (Chrome MV3)
All dashboard networking is in `src/services/api.js` (JSON, `{error}` bodies, 404/405/501 ⇒ "not built yet" banner,
network error ⇒ red Offline banner) and `src/services/voiceTutorClient.js` (multipart XHR to `/api/tutor/*`, 45 s).
Polling: `/api/status` every 10 s (3 s timeout), `/api/reading/history` every 15 s, `/api/camera/latest` every 10 s
while capturing. Timeouts: analyze 60 s, chat 90 s, capture 20 s, everything else 10 s. The extension posts
`POST /api/reading` (upsert by id, re-posted as duration grows) and optionally `POST /api/reading/screenshot`
(≤1280 px JPEG base64), probes `GET /api/status`, and `DELETE /api/reading/:id`; host permission is
`http://localhost/*`, `http://127.0.0.1/*` only. The webcam mode never touches the backend camera (getUserMedia in
the browser, one base64 still per Analyze/question); the "hardware" mode uses `/api/camera/stream` (MJPEG) and
`/api/camera/capture`.

## 2. Data flow (camera → frontend)

```
 paper on desk
   │  (webcam idx 2 / Pi / upload)                       browser webcam (getUserMedia)
   ▼                                                        │  one JPEG still, base64
 T1 capture.get_snapshot ──► runtime/snapshots/<ts>.jpg     │
   │                                                        ▼
   │  POST /snapshot | /upload (T4)        POST /api/camera/analyze  {image.base64 | image.snapshotId}
   │                                                        │  bridge writes runtime/uploads/<id>.jpg
   ▼                                                        ▼
 app.server.analyze(path) ─────────────────► transcribe.build_page_twin(path, previous_twin)
                                               ├─ T1 detect_and_dewarp  → runtime/dewarped/<stem>_dewarped.jpg   (~0.2 s)
                                               ├─ T2 segment            → lines + crops (runtime/crops/<stem>/)   (~0.15 s)
                                               ├─ T3 transcribe_page    → verbatim latex/text/confidence (2 readings + re-read) (8–17 s)
                                               └─ match_to_previous     → stable ids, changes, validated twin
   │
   ├─► app.store (runtime/twins/<snapshot_id>.json)  ─► GET /twin/latest, /twin/{id}   (Tutor team, viewer)
   ├─► WS /events  {twin, line_added, line_edited, line_crossed_out, status}
   │
   └─► bridge tutor layer (ONE Claude call, SV_MODEL): verbatim twin lines in → per-line status/note + summary + hints out
          │   labels stay verbatim; crossed_out → unclear; confidence < transcribe.low_confidence → unclear
          ▼
       {snapshotId, analyzedAt, summary, topics, steps[{label,status,note}], hints}  ─► dashboard (Notebook Observer / Dashboard)

 Chrome extension ─► POST /api/reading{,/screenshot} ─► bridge/store.py (runtime/reading/*.json) ─► GET /api/reading/history ─► Reading Memory page
 Dashboard chat  ─► POST /api/chat {message, history, includeNotebook, includeReading, includeReadingText, image?}
                     └─► (image? → build_page_twin) + latest twin + reading titles[/text] → ONE Claude call → {reply, sources}
 Pip tutor       ─► POST /api/tutor/message | /voice (multipart) ─► same brain, history per sessionId ─► {requestId, replyText, petExpression}
```

Hand-off of port 8000: T4's `uvicorn app.server:app` (PID 12727 as of H+6) → `uvicorn bridge.server:app` which
does `from app.server import app as vision_app`, `include_router(bridge_router)`, `add_middleware(CORSMiddleware)`,
`app = vision_app`. Every T4 route keeps working; the frontend's `/api/*` lives in the same process so the webcam,
the twin store and `/events` are shared.

## 3. Endpoint mapping (frontend contract → vision backend)

Kinds: `direct` thin adapter over an existing function/route · `compose` several modules · `new` nothing backs it
yet, bridge builds it · `defer` not for the demo.

| Frontend call | Timeout | Backing today | Missing | Bridge builds | Kind |
|---|---|---|---|---|---|
| `GET /api/status` | 3 s (polled 10 s) | T4 `/status` (mock, source, model, latest id); `ANTHROPIC_API_KEY`/`SV_MODEL` env; `capture.source._webcam()` | shape (`ok, version, camera{connected,streamUrl,streamType}, reading{eventsToday}, ai{available,model}`); real `camera.connected`; eventsToday | `bridge/api.py:status` — camera probe = shared webcam already open ⇒ true, else try `Webcam.open` once, cache 5 s; eventsToday from `bridge/store.py` | compose |
| `GET /api/camera/stream` | 10 s to first frame | `capture.source._webcam().read()` (singleton), `wait_for_stable`'s 5 fps preview loop (not reusable as-is) | MJPEG `multipart/x-mixed-replace` endpoint; a frame grabber that doesn't fight T4 for the camera | `bridge/camera.py:FrameGrabber` — one thread, lock around `Webcam.read()`, ~5 fps, latest JPEG in memory; installs itself as `pipeline.set_frame_provider` so `/snapshot` and `/api/camera/capture` take stills from the same handle; only runs while a stream client is connected; Pi source → proxy `pi_url` preview | new |
| `GET /api/camera/latest[?fresh=true]` | 10 s (polled 10 s) | `app.bridge_api.latest_snapshot()` (latest analysed twin), `latest_frame_path()` (newest still), T4 `/files/` | snapshot object `{id, imageUrl, capturedAt, deviceId}`; `null` 200 when none; `fresh=true` = grab a still | `bridge/api.py:camera_latest` — bridge still index first, else latest twin, else newest file; `fresh` grabs one still (no pipeline) | direct |
| `POST /api/camera/capture` | 20 s | T4 `POST /snapshot` runs the *whole* pipeline (17 s+, would exceed 20 s under load and double-run analysis); T1 `get_snapshot` / frame provider take a still in ≤1 s | still-only capture with an id the frontend can hand back to analyze | `bridge/api.py:camera_capture` — one still via FrameGrabber (or `capture.get_snapshot`), registered in the bridge still index as `still_<ts>_<rand>` → path; returns the snapshot object. **Deliberate deviation**: does *not* wrap `/snapshot` (see § 4.6) | direct |
| `POST /api/camera/analyze` | 60 s | `app.server.analyze(path, source)` → `transcribe.build_page_twin` (real chain; stores + broadcasts on `/events`); `transcribe.low_confidence`; T3's per-line extras `bbox`, `crop_path`, `context_crop_path`, `readings`, `uncertain_spans` | accept `image.base64` **and** `image.snapshotId`; write `runtime/uploads/<id>.jpg`; judging layer (status/note/summary/hints); H+9: per-step `bbox`, `cropUrl`, `contextCropUrl`, `readings{page,line,reread,agree,notes}`, `uncertainSpans` + top-level `imageSize` for T6's inspector | `bridge/analyze.py` — decode → file → `server.analyze` → `bridge/tutor.py:judge_twin` (ONE Claude call with verbatim lines + crossed-out flags + confidences; labels copied verbatim from the twin, never from the model); fallbacks: crossed_out→`unclear` "crossed out", conf < 0.6→`unclear`, `_error`/no lines→`steps=[]`, summary says analysis failed; 60 s budget, never 500 | compose |
| `POST /api/reading` | 10 s (ext. 4 s) | nothing (vision never stored reading) | JSON file store, upsert by id, newest first | `bridge/store.py:ReadingStore` → `runtime/reading/records.json` (thread lock, atomic write); returns the stored record | new |
| `POST /api/reading/screenshot` | 10 s | nothing | store JPEG + sidecar record; ≥1 MB body | `bridge/store.py:save_screenshot` → `runtime/reading/shots/<id>.jpg` + `<id>.json`; 2xx `{stored: id}`; idempotent | new |
| `GET /api/reading/history?limit=` | 10 s (polled 15 s) | nothing | `{items:[{id,title,url,durationSec,timestamp,excerpt,favicon}]}` newest first | `bridge/api.py:reading_history` from ReadingStore; `excerpt` = stored `text` or "" | new |
| `DELETE /api/reading/:id` | 10 s | nothing | 200 `{deleted:id}`; 200 even if unknown | `bridge/api.py:reading_delete` | new |
| `DELETE /api/reading/history` | 10 s | nothing | bulk clear (optional; UI falls back to one-by-one) | `bridge/api.py:reading_clear` — **declared before** `/{id}` so "history" isn't taken as an id | new |
| `POST /api/chat` | 90 s | twin from `app.store.latest()` / `bridge_api.latest_twin()`; reading records from ReadingStore; `build_page_twin` for an attached still; Anthropic SDK (T3's `transcribe.client` is strict-JSON + few-shot prefix: not reusable for prose) | tutor prompt + context assembly + consent gating + `sources[]` | `bridge/tutor.py:chat` — system = tutor about the student's *own* work, quotes twin lines verbatim, never "fixes" the transcription; context = twin (if `includeNotebook`), reading titles/urls (if `includeReading`), stored text only if `includeReadingText`; `image` present → `server.analyze` first; `sources` = `{type:notebook,id,title,capturedAt,imageUrl:/files/<dewarped>}` + `{type:reading,...}`; 90 s budget (pipeline ≤ 45 s, chat call ≤ 40 s) | compose |
| `POST /api/tutor/message` (multipart) | 45 s | same as chat | multipart parsing; `requestId` echo; `petExpression`; per-`sessionId` history (memory) | `bridge/api.py:tutor_message` → `tutor.chat`; response `{requestId, transcript: message, replyText, replyAudioUrl: null, petExpression}`; history dict keyed by sessionId (last 20 turns); an attached `image` runs the pipeline — if that would blow the 45 s budget the bridge falls back to the latest stored twin and says so in the reply (§ 4.9) | compose |
| `POST /api/tutor/voice` (multipart) | 45 s | nothing; `ffmpeg` is on this Mac (`/opt/homebrew/bin/ffmpeg`), `faster-whisper` wheel downloads cleanly, no `whisper` CLI | speech-to-text; TTS | `bridge/stt.py` — `faster_whisper` if importable (model `base`, CPU int8; `ffmpeg` decodes webm/m4a → 16 kHz wav) → transcript → same brain; else **501 `{"error":"voice not built yet"}`** so the UI shows "not built yet". TTS: `replyAudioUrl: null` for the demo | new / defer (TTS) |

Not in the frontend contract but served through the bridge unchanged: all of T4's routes (`/twin/*`, `/snapshot`,
`/upload`, `WS /events`, `/watch`, `/status`, `/telemetry`, `/files/*`, `/`, `/label`).

## 4. Gaps, conflicts and decisions

1. **CORS** — T4's app has no CORS middleware; the dashboard on :5173 would be blocked on every call. Bridge adds
   `CORSMiddleware(allow_origins=[http://localhost:5173, http://127.0.0.1:5173], methods *, headers *)`. The extension
   is exempt (host permission), but it still needs `/api/status` to answer 2xx for its connection dot.
2. **Port 8000 ownership** — `uvicorn app.server:app` (PID 12727) holds it in REAL mode. Hand-off: when
   `bridge.server:app` passes its tests, T5 asks in NOTES_T5 › For other terminals; T4 stops its uvicorn; T5 starts
   `uvicorn bridge.server:app --host 0.0.0.0 --port 8000`. Same `runtime/twins/` store, so `/twin/latest` survives.
3. **JSON body size** — Starlette/uvicorn impose no request-body limit by default (h11's limit is on headers), so the
   contract's ≥ 2–3 MB is already met; the bridge adds a test posting a 3 MB base64 image to prove it, and documents
   that any future reverse proxy (nginx default 1 MB) must raise `client_max_body_size`.
4. **Snapshot shape mismatch** — frontend `{id, imageUrl, capturedAt, deviceId}` vs twin `{snapshot_id,
   image.original_path, captured_at, source}`. Adapter: `id=snapshot_id` (or `still_…` for un-analysed stills),
   `imageUrl=/files/<original_path>` (relative; the frontend resolves against its backend URL),
   `capturedAt=captured_at`, `deviceId=source` (`webcam` | `pi` | `upload`).
5. **Camera shared by three readers** — `capture.source._webcam()` is a process-wide singleton but `Webcam.read()` is
   not thread-safe: T4's `/snapshot` (worker thread), T4's watch loop (`wait_for_stable`, its own 5 fps loop) and the
   bridge's MJPEG grabber could call `read()` concurrently. Bridge: a single grabber thread with a lock, installed as
   `pipeline.set_frame_provider` so `/snapshot` goes through it. Remaining hole: the **watch loop** (`POST /watch`)
   bypasses the provider. Decision for the demo: don't run the watch loop while the MJPEG stream is open; asked T1
   (NOTES_T5) to add a lock inside `Webcam.read()` so it becomes safe.
6. **`/api/camera/capture` vs `POST /snapshot`** — `/snapshot` runs the whole pipeline (17 s now, 25–33 s under
   contention) while the UI waits 20 s, and the UI calls analyze right after, which would run the pipeline twice.
   Decision: capture takes a still only (≤1 s) and analyze runs the pipeline once. T4's `/snapshot` is untouched.
7. **Frame provider overrides `?source=`** — with the bridge's provider installed, T4's `/snapshot?source=pi` takes
   the still from the bridge grabber (configured source), not from `pi`. Acceptable: one source per demo.
8. **Twin → steps vocabulary** — twin `status ∈ active|crossed_out|illegible`, frontend `status ∈ correct|error|unclear`.
   Mapping: `crossed_out` → `unclear` (note "crossed out"), `illegible` → `unclear`, `confidence <
   transcribe.low_confidence (0.6)` → `unclear`, otherwise the judging call decides `correct|error`. `label` is the
   verbatim `latex` (fallback `text`) — the model's output is never used for labels. Lines are ordered by `order`.
9. **Latency vs UI timeouts** — pipeline 10.7 s (T4's clean H+7 measure) to 17 s typical, 33 s contended, worst seen 65 s (bursty API; T4 H+7) + one judging call 4–9 s. The bridge caps the pipeline at 45 s so the 60 s analyze window always gets an answer. Analyze (60 s)
   fits; chat with an image (90 s) fits; **Pip tutor with an image (45 s) is tight**: bridge gives the pipeline at
   most 25 s there, then falls back to the latest stored twin and says "based on your last analysed page". Mitigation
   Henry can flip: `SV_MODEL=claude-haiku-5-5` for the judging/chat call (not for T3's transcription).
10. **Problem-line prime** — T3 reads the problem line as `f'(x)=x^{2}\sin x` (prime added) at 0.55–0.92 depending on
    the fix state. The bridge must *not* paper over it: the step shows whatever the twin says; the judge is told the
    confidence and `uncertain_spans` so it can say "unclear" rather than "error".
11. **Route order** — `DELETE /api/reading/history` must be registered before `DELETE /api/reading/{id}`.
12. **`/api/status` polled by two clients every 10 s** — the camera probe must be cheap: reuse an already-open shared
    webcam; a real `Webcam.open()` probe runs at most once per 5 s and never while the grabber owns the camera.
13. **No reading store exists anywhere** — the dashboard's Reading Memory and the extension's sync have no backing.
    Bridge adds a JSON file store (no SpacetimeDB for the demo). `text` is stored only when the extension sent it
    (user consent), and is handed to Claude only when `includeReadingText=true`.
14. **Prose Claude call** — T3's `transcribe.client.ask_json` is strict-JSON with a cached few-shot *transcription*
    prefix and must not be reused for tutoring (its examples would bias the judge). The bridge builds its own thin
    Anthropic call (`bridge/tutor.py`), structured JSON for the judge, plain text for chat; same `SV_MODEL` /
    `ANTHROPIC_API_KEY`; `ai.available=false` when the key is missing and the tutor answers with an honest error.
15. **Voice** — no local `whisper`; `faster-whisper` installs cleanly as a wheel (needs the `base` model download,
    ~150 MB, first run). If the install or model download fails on this Mac, `/api/tutor/voice` returns 501 and the UI
    shows "not built yet" (contract-approved). TTS is out of scope: `replyAudioUrl: null`.
16. **T3's `_error` twin** (H+6) — `build_page_twin` now returns `quality.ok=False, lines=[], _error=...` instead of
    raising. T4's `build_twin` still validates it (schema-valid) and stores it as the latest twin. The bridge treats
    `_error` or `lines=[]` as "nothing readable": `steps=[]`, summary explains, `status 200`.
17. **Mock fallback leaks** — in real mode before the first snapshot `GET /twin/latest` serves the mock twin flagged
    `_fallback`. The bridge never shows a fallback twin as the student's work: `includeNotebook` context and
    `camera/latest` ignore twins with `_fallback`.
18. **Frontend consumes relative URLs** — `imageUrl` and `replyAudioUrl` are resolved against the dashboard's backend
    URL, so the bridge returns `/files/...` paths, which also works when Henry switches the base URL to the venue IP.

19. **Illegible lines have empty labels** — the twin gives `latex=""`/`text=""` for `illegible`; the bridge keeps the label
    empty and puts "illegible in the photo" in the note (the UI renders the note). 60+ such steps appear when T1 says
    `no_page` (hand-held sheet); fine for honesty, noisy for the demo — keep the page flat under the mount.

## 5. Verification (H+7, 2026-10-24 13:30–13:45 PT)

Setup: bridge started as `uvicorn bridge.server:app --host 127.0.0.1 --port 8001` (REAL mode, `source env.sh`) next
to T4's server on :8000, so nothing had to stop; dashboard `npm run dev` on :5173 with Settings › Backend set to
`http://127.0.0.1:8001`. Screenshots and raw responses: `runtime/debug/bridge/`.

| Check | Result |
|---|---|
| `pytest bridge/tests` | **43 passed** (1.2 s). Full repo `pytest -q`: 274 passed, 5 failed — all five in `layout/tests/test_segment_synth.py` (T2's in-progress synth tests), none in bridge/app/transcribe/capture/eval. |
| `GET /api/status` + CORS | 200 with `access-control-allow-origin: http://localhost:5173`; `camera.connected: true` (webcam index 2 opened once by the probe), `ai.available: true`, model `claude-sonnet-5-5`, `voice.available: true`. |
| Settings › Backend › Test | **"Connected in 14 ms · backend 0.1.0"**; after Save the red Offline banner disappeared and the "not built yet" list is **empty** (voice included — STT installed). `ui_dashboard_connected.jpg`. |
| `POST /api/camera/analyze` with `eval/testset/synthetic_demo.jpg` as base64 (webcam shape) | 200 in **18.2 s** (page 0.29 s, layout 0.16 s, transcribe 11.5 s, judge ≈6 s). Steps: L0 `f(x)=x^{\wedge}2\sin x` conf 0.60 → `unclear`; **L1 `f'(x)=2x\cdot\cos x` → `status: error`** (label verbatim; note "the derivative of a product … both factors need to be involved"); L2 `=2\cos x` → `unclear` "crossed out"; L3 → `unclear` (depends on L1). Summary names the product rule; 3 hints. `smoke_analyze_response.json`. |
| Dashboard "Analyze my page" (browser webcam still) | 200 in 10.1 s; the still showed a shirt, not a page → summary "This page could not be read; nearly every line was illegible … no mathematics here to check yet", all steps `unclear`. Honest failure, no 500. `ui_notebook_analyze_webcam.jpg`. |
| Overhead camera (hardware) mode: `GET /api/camera/stream` → `POST /api/camera/capture` → analyze by `snapshotId` | MJPEG shows **LIVE** in the UI within ~2 s (`ui_notebook_mjpeg_live.jpg`); capture 53 ms; analyze 21.1 s (pipeline 16.1 s, 65 lines of which 54 illegible on a hand-held printed sheet, T1 `no_page`); summary "mostly a problem statement … no readable student calculations", topics Newton's laws / inclined plane, 3 hints. `ui_notebook_hardware_analyze_summary.jpg`, `…_hints.jpg`. |
| `POST /api/reading` → Reading Memory page | record stored under `runtime/reading/records.json`, listed newest-first in the UI ("Product rule — Wikipedia · 1m 30s"), nav badge shows 1. `ui_reading_memory.jpg`. |
| `POST /api/chat` (curl and UI) | UI question with notebook still: 200 in 18.8 s, reply quotes the verbatim line `f'(x) = 2x · cos x`, says "in the photo from 1:32 PM", sources chips "Notebook snapshot" + "Product rule — Wikipedia". `ui_tutor_chat_reply.jpg`. Consent gating verified by test (`SECRET PAGE TEXT` never reaches the prompt unless `includeReadingText`). |
| `POST /api/tutor/message` | `requestId` echoed, `replyAudioUrl: null`, `petExpression: curious`, history kept per `sessionId` (second turn saw the first). |
| `POST /api/tutor/voice` | faster-whisper `base` loaded in 82 s on first use (one-time download, now cached). A `say`-generated 1.9 s webm/opus question transcribed **exactly** ("Where did I go wrong in my derivative?") in 1.65 s; reply 200. Garbage audio → 502 `{"error": "could not understand the recording…"}`, not a crash. |
| T4 routes through the bridge | `/twin/latest`, `/status`, `/upload`, `/files/...` all 200 in tests and live; the twin stored by analyze validates against `page_twin.schema.json` (test). |
| 3 MB JSON body | accepted (handler reached; rejected only as "not a JPEG"), no 413. |

| H+9 inspector fields (in-process, real chain, synthetic page) | 200 in 8.9 s; `imageSize` 1700×2200; every step has `bbox`, `cropUrl`/`contextCropUrl` that `/files/` serves (200), `readings.page`/`line` verbatim with `agree: true`, `uncertainSpans`; `GET /twin/{snapshotId}` → 200. `runtime/debug/bridge/h9_analyze_response.json`. **Not yet on the live :8000** — that process predates the change and needs Henry to restart it (kill was denied to the terminal). |

What did not work / caveats:
- The Chrome **extension** was not loaded unpacked in this pass (needs Henry's Chrome profile and a site approval); its
  endpoints were exercised with the exact payloads from `background.js` via curl/tests instead. Load `../extension/`
  at `chrome://extensions` → Developer mode → Load unpacked, set its backend URL to the bridge, approve a site, read 5 s.
- Hand-held printed sheets give T1 `no_page` and T2 60+ noisy "lines"; the judge stays honest but the step list is long.
  A flat page under the mount (the real demo) gives 4 clean lines (see the synthetic result above).
- The in-UI hardware Analyze left the live preview toggled off afterwards (frontend behaviour or my click — to confirm).
- Voice TTS is not built (`replyAudioUrl: null`), as agreed.

### H+9 addition — analyze step shape (for T6's notebook inspector)

```json
{ "snapshotId": "snap_…", "analyzedAt": "…", "summary": "…", "topics": [], "hints": [],
  "imageUrl": "/files/runtime/uploads/still_….jpg", "dewarpedUrl": "/files/runtime/dewarped/still_…_dewarped.jpg",
  "imageSize": {"width": 1700, "height": 2200},
  "steps": [ { "id": "L1", "label": "f'(x)=2x\\cdot\\cos x", "status": "error", "note": "…",
               "confidence": 0.92, "lineStatus": "active",
               "bbox": [128.0, 342.0, 522.0, 71.0],
               "cropUrl": "/files/runtime/crops/still_…_dewarped/line_001.png",
               "contextCropUrl": "/files/runtime/crops/still_…_dewarped/line_001_ctx.png",
               "readings": {"page": "f'(x)=2x\\cdot\\cos x", "line": "f'(x)=2x\\cdot\\cos x", "reread": null, "agree": true, "notes": []},
               "uncertainSpans": [] } ] }
```
`label` stays the verbatim twin `latex` (or `text`); `readings.*` are the raw per-pass strings (`null` = pass did not run,
`""` = pass said illegible); `agree` uses T3's rule (`transcribe.compare.readings_agree`). The full twin is at
`GET /twin/{snapshotId}`.

## Change log
- H+9 (T5): analyze steps gained `bbox`, `cropUrl`, `contextCropUrl`, `readings`, `uncertainSpans`; top-level `imageSize` (relay from Henry for T6). Bridge serves :8000 since H+8.
- H+7 (T5): bridge built and verified live on :8001 (§ 5); gap 19 added; hand-off to :8000 requested in NOTES_T5.
- H+6 (T5): first version — module analysis, data flow, 13-endpoint mapping, 18 gaps/decisions.
