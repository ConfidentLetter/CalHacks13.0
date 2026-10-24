# Pip voice — backend contract (proposed)

For the backend teammate. These endpoints **do not exist yet**. The frontend is built and tested against a mock of this contract.
All frontend networking for this feature lives in `frontend/src/services/voiceTutorClient.js`.

## Endpoints
| | Default path | Override |
|---|---|---|
| Voice question | `POST /api/tutor/voice` | `VITE_TUTOR_VOICE_PATH` |
| Typed question | `POST /api/tutor/message` | `VITE_TUTOR_MESSAGE_PATH` |

The base URL is the dashboard's backend URL (Settings → Backend, default `http://localhost:8000`). Allow CORS from the dashboard origin.

### `POST /api/tutor/voice` — `multipart/form-data`
| Field | Required | Notes |
|---|---|---|
| `audio` | yes | The recording. The filename extension matches the real format: `question.webm` (Chrome/Firefox, Opus), `question.m4a` (Safari, AAC), or `.ogg` / `.aac`. Max 30s. |
| `audioMimeType` | yes | The exact recorder MIME type, e.g. `audio/webm;codecs=opus` or `audio/mp4`. Use this rather than guessing from the filename. |
| `sessionId` | yes | Anonymous per-tab ID (`s-…`). Use it to key conversation history. It carries no personal data. |
| `requestId` | yes | Unique per request (`r-…`). **Echo it back.** A Retry sends a new `requestId` with the same audio. |
| `image` | no | `notebook.jpg`, a JPEG up to 1600px wide. **One** still captured when the student pressed Hold to talk. |
| `imageCapturedAt` | no | ISO timestamp of that still. Present only when `image` is. |

### `POST /api/tutor/message` — `multipart/form-data`
Same as above, but with `message` (text) instead of `audio` / `audioMimeType`.

### Success — `200 application/json`
```json
{
  "requestId": "r-…",
  "transcript": "Where did I go wrong?",
  "replyText": "Look at the sign in your second line.",
  "replyAudioUrl": "/api/audio/r-….mp3",
  "petExpression": "encouraging"
}
```
- `transcript`: what you heard (voice only; the UI shows it under "You said"). For `/message` it may be omitted.
- `replyAudioUrl`: absolute, or relative to the backend. Must be playable by an `<audio>` element (mp3, wav, or ogg) and
  allowed by CORS. It can be `null`, in which case the UI shows text only.
- `petExpression`: one of `neutral | encouraging | curious | celebrating | thinking`. Unknown values fall back to neutral.

### Errors
Send a non-2xx status with `{ "error": "Human-readable message" }`. The UI shows that message with a **Retry** button.
`404` / `405` / `501` are shown as "not built yet". The client times out after **45s**.

## The backend owns
- Speech-to-text, the Claude calls, tutoring prompts, and conversation history (keyed by `sessionId`).
- Text-to-speech (e.g. Cartesia) and hosting the reply audio.
- **All provider API keys.** The browser never calls Anthropic or Cartesia.

## Assumptions to confirm
1. Multipart upload of up to ~1 MB of audio plus ~400 KB of image. Set the request size limit to at least 3 MB.
2. Reply audio is served from the same backend. If it's on a CDN, enable CORS on it.
3. `sessionId` lives only for the browser tab (sessionStorage). Expire history as you like.
4. The image is a single still, not video. Please don't phrase replies as if Pip continuously watches the student.

## Frontend guarantees
- The mic opens only while the button is held, and every track is stopped afterwards. Nothing records in the background.
- Recordings and stills stay in memory only. They're never put in localStorage or logged.
- One turn at a time. Responses to cancelled or superseded requests are ignored.
- **Demo voice** is a separate, clearly labeled mode with scripted replies. A failed live request never quietly turns into a demo reply.
