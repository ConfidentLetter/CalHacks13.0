# T5 — Bridge: connect the vision pipeline to the team's frontend

**How to use:** Henry pastes the launch message from `launch_T5.txt`; it tells you to read this file.

## Project context
Read `README.md`, `AGENTS.md`, `contracts/`, `config/vision.yaml`, `mocks/`, and the top status block + `## For other terminals` of every `NOTES_T*.md` first. Four terminals (T1 capture, T2 layout, T3 transcribe, T4 app/eval) have built the vision pipeline: snapshot → page detection/dewarp → line layout → verbatim transcription → page twin, served by `app/server.py` on port 8000 (`/snapshot`, `/upload`, `/twin/latest`, `/twin/{id}`, `WS /events`, viewer at `/`, label tool at `/label`, `/status`, `/files/<path>`).

A teammate (Micha) built the product frontend in a separate branch that is now merged into the repo root: `../frontend/` (React + Vite dashboard on http://localhost:5173), `../extension/` (Chrome MV3 reading tracker), and two contract documents **you must read in full**: `../docs/BACKEND_INTEGRATION.md` and `../docs/BACKEND_CONTRACT.md`. The frontend has no mock data: every button calls `http://localhost:8000/api/...` and shows "not built yet" until the endpoint exists. All its networking is in `../frontend/src/services/api.js` and `../frontend/src/services/voiceTutorClient.js`.

**Your job is the connection.** Nobody else owns the seam between the vision backend and the frontend. You own `bridge/`, `docs/CONNECTIONS.md` and `NOTES_T5.md`. You never edit `app/`, `capture/`, `layout/`, `transcribe/`, `eval/`, `contracts/`, `config/`, `mocks/`, `../frontend/` or `../extension/`. If a change is needed there, write it under `## For other terminals` in `NOTES_T5.md` (for the frontend, under `## For the frontend team`) and say it in your reply.

Rules of the repo apply: Python 3.11, tests with pytest under `bridge/tests/`, deps in `requirements/bridge.txt`, config via `app.config.get`, timing via `app.telemetry.log` with stage names `bridge.<step>`, model from env `SV_MODEL`, key from `ANTHROPIC_API_KEY`, never run git, never hard-code keys, never correct the student inside the transcription (judging correctness is allowed only in the tutor layer you build here, and it must quote the verbatim twin).

## Build in this order

### Step 1 (first 45 minutes): analysis — `docs/CONNECTIONS.md`
Read every module's public surface (`contracts/interfaces.md`, each folder's `__init__.py`, `app/server.py`, `app/API.md`) and the frontend contract docs. Write `docs/CONNECTIONS.md` with:
1. One paragraph per module: what it does, its entry points, what it returns, its latency (from NOTES/telemetry).
2. A data-flow diagram (text) from camera to frontend.
3. **A mapping table**: every endpoint the frontend calls (`GET /api/status`, `GET /api/camera/stream`, `GET /api/camera/latest`, `POST /api/camera/capture`, `POST /api/camera/analyze`, `POST /api/reading`, `POST /api/reading/screenshot`, `GET /api/reading/history`, `DELETE /api/reading/:id`, `DELETE /api/reading/history`, `POST /api/chat`, `POST /api/tutor/message`, `POST /api/tutor/voice`) → which existing vision function/route backs it, what is missing, and what you will build. Mark each as `direct` (thin adapter), `compose` (calls several modules), `new` (no backing yet), or `defer` (not for the demo).
4. Gaps and conflicts you found (shape mismatches, naming, CORS, body-size limits, port ownership). Put the ones other terminals must act on in `NOTES_T5.md › For other terminals`.
Finish this step and say so in your reply before writing code.

### Step 2 (by +2 h): the bridge app — `bridge/server.py`
- Do NOT fork T4's server. Import it and extend it: `from app.server import app as vision_app`, then `vision_app.include_router(bridge_router)` and `vision_app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173","http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])`, and export `app = vision_app`. Run with `uvicorn bridge.server:app --host 0.0.0.0 --port 8000`. One process, one port, all of T4's routes still work. Raise the JSON body limit to ≥ 3 MB.
- `bridge/api.py` — `APIRouter(prefix="/api")` implementing, in this order:
  1. `GET /api/status` — `ok`, `version`, `camera.connected` (real: try `capture.source` on the configured source; cache for 5 s), `camera.streamUrl: "/api/camera/stream"`, `camera.streamType: "mjpeg"`, `reading.eventsToday`, `ai.available/model`.
  2. `GET /api/camera/latest[?fresh=true]` and `POST /api/camera/capture` — wrap T4's latest snapshot / `POST /snapshot`; return the snapshot object with `imageUrl` under `/files/...`; `null` with 200 when nothing yet.
  3. `GET /api/camera/stream` — MJPEG `multipart/x-mixed-replace; boundary=frame` at ~5 fps from `capture.source` (reuse whatever frame grabber T1/T4 expose; never open the camera twice — if T4's server already holds it, read its latest frame file).
  4. `POST /api/camera/analyze` — accept both request shapes (`image.base64` webcam still, or `image.snapshotId`). Write the still to `runtime/uploads/<id>.jpg`, call `transcribe.build_page_twin(path)` (the real T1→T2→T3 chain), then build the response: `snapshotId`, `analyzedAt`, `summary`, `topics`, `steps[]` (one per twin line in reading order: `label` = the verbatim latex/text, `status` ∈ correct|error|unclear, `note`), `hints[]`. `status`/`note`/`summary`/`hints` come from ONE Claude call (`SV_MODEL`) that receives the verbatim twin lines (with crossed-out flags and confidences) and judges them; the labels themselves must stay verbatim from the twin. Lines with `status: crossed_out` → `unclear` with note "crossed out". Confidence < `transcribe.low_confidence` → `unclear`. 60 s timeout; on any failure return the twin lines with `unclear` and a `summary` saying analysis failed, never a 500.
  5. `POST /api/reading`, `POST /api/reading/screenshot`, `GET /api/reading/history`, `DELETE /api/reading/{id}`, `DELETE /api/reading/history` — `bridge/store.py`: a JSON file store under `runtime/reading/` (upsert by id, newest first, thread lock, screenshots saved as files with a sidecar record). No database needed for the demo.
  6. `POST /api/chat` — one Claude call: system prompt = tutor that answers about the student's own work; context = latest twin (if `includeNotebook`), reading titles/urls (if `includeReading`), stored text only if `includeReadingText`; if `image` is present, run `build_page_twin` on it first and use that twin. Return `reply` + `sources`. 90 s budget.
  7. `POST /api/tutor/message` (multipart) — same brain as `/api/chat`, response shape from `BACKEND_CONTRACT.md` (`requestId` echoed, `replyText`, `replyAudioUrl: null`, `petExpression`). Keep history per `sessionId` in memory.
  8. `POST /api/tutor/voice` — accept the multipart, run speech-to-text if a local `whisper` CLI or `faster_whisper` is importable (check with `shutil.which` / try-import; add to `requirements/bridge.txt` only if it installs cleanly on this Mac), else return 501 `{"error": "voice not built yet"}` so the UI shows "not built yet" instead of failing. TTS is `replyAudioUrl: null` for the demo.
- Every handler: try/except → `{"error": "<human message>"}` with a proper status; the server never dies. Log `bridge.<endpoint>` ms.
- Tests (`bridge/tests/`): every endpoint with FastAPI `TestClient`, Claude mocked, vision chain mocked with `mocks/page_twin_product_rule.json`; one test that the CORS header is present; one that `/twin/latest` from T4 still works through the bridge.

### Step 3 (by +3 h): prove the connection end to end
- `cd ../frontend && npm install && npm run dev`, open http://localhost:5173, Settings → Backend → Test must say "Connected". Walk every page; the red banner must disappear and the "not built yet" list must be empty except `/api/tutor/voice` if STT is unavailable.
- Press "Analyze my page" with the synthetic demo page (upload `eval/testset/synthetic_demo.jpg` through the webcam path by base64) and confirm the product-rule line comes back `status: error` with the verbatim label `f'(x)=2x\cdot\cos x`.
- Load `../extension/` unpacked in Chrome, read a page, confirm a record appears in Reading Memory.
- Record what worked and what didn't in `docs/CONNECTIONS.md › Verification`, with screenshots in `runtime/debug/bridge/`.

### Step 4 (ongoing): keep the seam honest
- Re-read `contracts/CHANGELOG.md` and every `NOTES_T*.md` status block before each step; when T1–T4 change a shape, adapt the bridge, not them.
- Keep `docs/CONNECTIONS.md` current — it is the document Henry hands to the frontend team and the judges' "how it works" slide.

## Done when
- `uvicorn bridge.server:app --port 8000` serves both T4's routes and every `/api/*` route in the frontend contract; `pytest bridge/tests` green; the dashboard shows no missing endpoints (voice may be 501); `docs/CONNECTIONS.md` has the module analysis, the mapping table, and the verification log.
