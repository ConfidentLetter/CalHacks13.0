# Synapse — Backend Integration Guide

This guide is for the backend / Claude / SpacetimeDB / camera teammates. It covers what the dashboard
and the Chrome extension will send you, and what they expect back.

**These endpoints are a proposal.** The frontend has **no fake data**: every button calls these endpoints,
and until they exist, the UI shows "not connected" or error states.

## How the frontend talks to you

- All dashboard requests go through **`frontend/src/services/api.js`**. Nothing else calls `fetch`.
- The backend base URL defaults to `http://localhost:8000`. You can change it in **Settings → Backend
  connection** or with the env var `VITE_API_BASE_URL`.
- The extension posts reading records straight to `POST /api/reading` from `extension/background.js`.
- If the backend is unreachable, a red **Offline** banner appears. If an endpoint returns **404 / 405 / 501**,
  the banner lists it as "not built on the backend yet". Any other error is shown next to the button that triggered it.
- Error bodies: `{ "error": "Human-readable message" }`. The UI shows this text.
- JSON everywhere. Timestamps are ISO-8601 strings.

### CORS (required)

The dashboard runs on `http://localhost:5173`, so allow that origin:

```python
# FastAPI example
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
```

The extension has host permission for `http://localhost/*` and `http://127.0.0.1/*`, so it isn't blocked
by CORS. If you host the backend somewhere other than localhost, tell the frontend team so the manifest can be updated.

**Never send API keys to the frontend.** The Claude key and SpacetimeDB credentials stay server-side.

---

## Endpoints

### `GET /api/status`
Health check. The dashboard polls it every 10s, and the extension calls it to show its connection dot.

```json
{
  "ok": true,
  "version": "0.1.0",
  "camera": { "connected": true,
              "streamUrl": "/api/camera/stream", "streamType": "mjpeg" },
  "reading": { "eventsToday": 4 },
  "ai": { "available": true, "model": "claude-sonnet-5-5" }
}
```
`camera.connected` must reflect the real hardware. The UI shows "Not connected" when it's false.

### `GET /api/camera/stream` (new — live preview)
The live preview for the hardware adapter. The laptop/USB webcam doesn't use this: it streams straight from the browser via getUserMedia.
- **Preferred: MJPEG**, `Content-Type: multipart/x-mixed-replace; boundary=frame`. The browser shows it directly in an `<img>`.
  On a Pi, `picamera2` + a small MJPEG server (or `mjpg-streamer`) works. On an ESP32-CAM, the stock `CameraWebServer` `/stream` already serves this format.
- Alternatively, browser-playable video (HLS/MP4): report `"streamType": "video"` in `/api/status`.
- If the stream lives on the device itself rather than the backend, add `"streamUrl": "http://<pi-ip>:8080/stream"` to `camera` in
  `GET /api/status` (absolute or relative). The UI uses that URL instead of `/api/camera/stream`.
- The UI only shows **LIVE** after a real frame arrives. If no frame arrives within 10s, it shows an error with a retry button.
  It only connects while `camera.connected` is true.

### `GET /api/camera/latest[?fresh=true]`
Returns the latest snapshot. `fresh=true` comes from the "Refresh Snapshot" button. You may trigger an
immediate capture or ignore the flag. While capturing, the dashboard polls this every 10s.

```json
{
  "id": "snap_123",
  "imageUrl": "/snapshots/snap_123.jpg",   // absolute, or relative to the backend URL
  "capturedAt": "2026-10-24T03:10:00Z",
  "deviceId": "pi-desk-1"
}
```
Instead of `imageUrl` you can send `"imageBase64": "...", "mimeType": "image/jpeg"`.
If there is no snapshot yet, return `null` with status 200 (a 404 would be reported as "not implemented").

### `POST /api/camera/capture` (hardware adapter only)
Used only when the student picks "Overhead camera (Pi / ESP32 stream)". It takes one still right now, at the moment of a question or Analyze. Respond with the same snapshot object as
`GET /api/camera/latest`. Until this is implemented, the button shows a "not implemented on the backend yet" error,
and the UI never pretends a picture was taken.
```json
// request: {}
// response
{ "id": "snap_124", "imageUrl": "/snapshots/snap_124.jpg", "capturedAt": "2026-10-24T03:11:02Z", "deviceId": "pi-desk-1" }
```

### `POST /api/camera/analyze`
Runs Claude Vision on **one still** grabbed from the live camera when the student presses "Analyze my page".
The UI waits up to 60s.

```json
// request — webcam still (laptop/USB camera, captured in the browser)
{ "image": { "source": "webcam", "mimeType": "image/jpeg", "base64": "/9j/4AAQ…", "width": 1600, "height": 900,
             "capturedAt": "2026-10-24T11:11:20Z" } }
// request — hardware still (Pi/ESP32 adapter; the frame came from POST /api/camera/capture)
{ "image": { "source": "hardware", "snapshotId": "snap_124", "capturedAt": "2026-10-24T11:11:20Z" } }
// response
{
  "snapshotId": "snap_123",
  "analyzedAt": "2026-10-24T03:10:05Z",
  "summary": "Projectile problem; setup correct but final division drops a factor of 2.",
  "topics": ["Kinematics"],
  "steps": [
    { "label": "v² = v₀² − 2gh", "status": "correct", "note": "" },
    { "label": "h = 144 / 9.8", "status": "error", "note": "Divide by 19.6, not 9.8." }
  ],
  "hints": ["Sanity check with h = v₀·t/2."]
}
```
`status` is one of `correct | error | unclear`. All fields except `summary` are optional.

### `POST /api/reading`
Sent by the extension, and by the dashboard's "Add page" form. **Upsert by `id`.** The extension
re-posts the same `id` as the reading duration grows.

```json
{
  "id": "ext-lq2x8f-a1b2c3",        // client-generated, stable
  "title": "Projectile motion — Wikipedia",
  "url": "https://en.wikipedia.org/wiki/Projectile_motion",
  "domain": "en.wikipedia.org",
  "favicon": "https://en.wikipedia.org/favicon.ico",
  "startedAt": "2026-10-24T03:00:00Z",
  "timestamp": "2026-10-24T03:00:31Z",
  "durationSec": 412,
  "source": "extension",            // "extension" | "manual"
  "text": "…up to 4000 chars…"      // ONLY present if the user enabled text sharing
}
```
Respond with the stored record (any 2xx). Records stay queued in the extension until it gets a 2xx.

### `POST /api/reading/screenshot`
Sent by the extension **only if the user turns on "Upload snapshots to backend"** (off by default).
While someone actively reads an approved site (e.g. Canvas), the extension captures the visible tab every 10s
(10/30/60 is configurable). It skips frames where nothing changed, and never captures grade, inbox, profile,
or quiz-taking pages. Images are JPEG, downscaled to at most 1280px wide (~100–200 KB each).

```json
{
  "id": "shot-lq2x8f-ab12",                 // client-generated; treat as idempotent
  "sessionId": "ext-lq2x8f-a1b2c3",         // matches the reading record id from POST /api/reading
  "url": "https://bcourses.berkeley.edu/courses/123/pages/week-4",
  "title": "Week 4 — Kinematics",
  "capturedAt": "2026-10-24T03:10:00Z",
  "mimeType": "image/jpeg",
  "width": 1280,
  "height": 720,
  "imageBase64": "/9j/4AAQ…"
}
```
Respond with any 2xx. Snapshots stay queued in the extension (last 20 kept) until they're accepted. Good uses:
run Claude Vision on them for the tutor's reading context, or store them in SpacetimeDB next to the reading record.
Raise your server's JSON body limit to at least 1 MB.

### `GET /api/reading/history?limit=100`
```json
{ "items": [ { "id": "...", "title": "...", "url": "...", "durationSec": 412, "timestamp": "...", "excerpt": "...", "favicon": "..." } ] }
```
A bare array also works. Sort newest first. The dashboard polls this every 15s. That polling is what
"live updates" means until you push SpacetimeDB subscriptions. `excerpt` is the stored `text` (or empty).

### `DELETE /api/reading/:id`
`200 { "deleted": "id" }` or `204`. If the id doesn't exist, return 200/204 rather than 404.

### `DELETE /api/reading/history` (optional)
Bulk clear for **Settings → Clear reading history**. If it isn't implemented (404/405), the dashboard
falls back to deleting records one at a time.

### `POST /api/chat`
The UI allows up to 90s before timing out.

```json
// request
{
  "message": "Did I make a mistake in my latest notebook work?",
  "history": [ { "role": "user", "content": "..." }, { "role": "assistant", "content": "..." } ],
  "includeNotebook": true,        // user toggle: use latest snapshot(s)
  "includeReading": true,         // user toggle: use reading titles/URLs
  "includeReadingText": false,    // user consent: may use stored page text
  "image": { "source": "webcam", "mimeType": "image/jpeg", "base64": "…", "width": 1600, "height": 900,
             "capturedAt": "2026-10-24T11:11:35Z" }   // optional: ONE still taken when the question was sent
}
// response
{
  "reply": "Your setup is right, but…",
  "sources": [
    { "type": "notebook", "id": "snap_123", "title": "Notebook snapshot", "capturedAt": "...", "imageUrl": "/snapshots/snap_123.jpg" },
    { "type": "reading", "id": "ext-…", "title": "Projectile motion — Wikipedia", "url": "https://…" }
  ]
}
```
Plain text with `\n\n` between paragraphs renders well. Respect `includeReadingText=false`: don't send
stored page text to Claude when it's false.

---

## Testing your endpoint against the UI
1. Run the backend on `:8000`, then `cd frontend && npm run dev`.
2. **Settings → Backend connection → Test**. It should say "Connected in N ms".
3. The red banner disappears once the backend is reachable and every endpoint is implemented.

## Where to change things
| Need | File |
|---|---|
| Endpoint paths / payload shapes | `frontend/src/services/api.js` |
| Default backend URL | `frontend/src/services/config.js` or `VITE_API_BASE_URL` |
| Extension sync logic | `extension/background.js` → `flush()` |

## Live camera model (important for the AI side)
- There is **no interval capture** any more. The live preview is shown only in the browser and is never recorded or uploaded.
- The AI gets exactly **one still** per question or Analyze click, in `image`. Please don't describe it as "watching" the page.
  Answer about the still, and feel free to say "in the photo from 11:11…".
- `image.base64` is a JPEG up to 1600px wide (~150–400 KB). Raise your JSON body limit to at least 2 MB.
