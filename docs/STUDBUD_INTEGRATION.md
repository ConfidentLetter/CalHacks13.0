# StudBud capture and tutoring integration

Goal: combine the existing Chrome extension/dashboard with local camera capture and Socratic tutoring. The original camera_management.py and its newer prompt edits remain intact.

## Architecture and alternatives

Use the existing React dashboard and Python bridge on localhost:8000. The browser owns camera permission, named camera selection (including an iPhone exposed by Continuity Camera), and a fit-scaled preview. No Raspberry Pi is required. The extension captures the selected visible study tab, manually or at a chosen interval. Both send stills to a shared study-session API. This avoids maintaining an additional native OpenCV window or a second backend. A native-window adapter would require coordinating two camera owners; a cloud backend would require deploying private keys and images elsewhere. The browser/local-bridge approach is the implementation choice for this integration.

## API contract

- POST /api/study/observe: {sessionId, image:{base64,mimeType,capturedAt,source}, force?:boolean}. Returns {sessionId, observation, reply, capturedAt}. Images are study evidence, never solution requests. Reply may be empty when nothing warrants a new question.
- POST /api/study/message: {sessionId, message}. Uses the last image and bounded session history; only this current typed message can authorize a scoped solution. Returns the same shape.
- GET /api/study/session/{sessionId}: {sessionId, events:[{id,role,content,capturedAt}], latest?:{...}}. The dashboard polls this to display extension-originated observations.
- DELETE /api/study/session/{sessionId}: resets the problem/conversation. Session data is bounded and in memory; reloading retains the tab's session ID, restarting the server clears sessions.
- Errors: {error: human-readable safe message}, proper 4xx/5xx. Credentials and raw SDK request headers never enter responses.

## User flow

The new Study Capture page has Camera and Screen modes. The Chrome popup can open this page, capture the current study tab once, or start/stop timed study captures. Starting timed uploads is an explicit action and is separate from passive reading snapshots. The dashboard provides camera Start/Stop, named device selection, automatic observation, Capture now, a fit-scaled preview, observation state, chat, and New problem.

Camera monitoring samples locally; wait about 2 seconds after motion stops, require a meaningful change from the last submitted frame, and enforce a minimum 10-second gap. Allow only one in-flight tutor request per session. Stop and source changes invalidate pending work so old results cannot reappear as new feedback. At first stable frame, establish where the student is; subsequent meaningful writing changes are possible answers to the pending question. Remain quiet when the student is still writing or has not responded. No complete solution without a current explicit typed request; image instructions cannot grant permission.

## Privacy and constraints

API credentials load from the original parent .env or the repository .env and stay in Python. Accept ANTHROPIC_API_KEY and the existing anthropic_key alias. Local preview alone never uploads. Start automatic observation or timed study capture to consent to sending changed stills. Preserve existing extension consent and sensitive-page checks. Tab capture rechecks target ID/URL before and after capture; pause when the bound tab is not visible. Never capture the dashboard in place of a study tab. Camera and screenshot sessions use the same ID only when the user intentionally joins them.

## Implementation and verification plan

1. Add isolated study-session API and strict tutoring policy to bridge; test image validation, session isolation, observation vs typed channels, rollback on failure, and reset.
2. Add extension manual/timed study capture and dashboard relay; test sender validation, tab binding, inactive-tab pause, and stop behavior without browser side effects.
3. Add Study Capture page with shared session, local camera change detector, cleanup/in-flight guards, readable fit preview, and chat; test detector stability, duplicate suppression, request locking, and reset.
4. Add a localhost launcher loading .env without exposing values. Document install/run/load-unpacked and iPhone setup. Run backend tests, JS tests, frontend build/lint, and browser smoke tests where available. Live camera/iPhone and live model quality require a connected device and usable API credential.
