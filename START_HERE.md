# StudBud: screen captures and live camera tutoring

This integration runs entirely on your Mac except the Anthropic API call. No Raspberry Pi is needed. The existing `../camera_management.py` is preserved; the integrated browser flow runs through the existing Python bridge with a new isolated study-session API.

## One-time setup

Use Node.js 22.12+ (or 20.19+) and Python 3.11+. Keep the API key in the original `../.env`, or place a `.env` in this repository. Both `ANTHROPIC_API_KEY` and the existing `anthropic_key` name work. Never put a real key in a `VITE_` setting or in the extension. Optionally set `CLAUDE_MODEL` to a model available to your Anthropic account.

The project lives on an MS-DOS drive. Keep the Python environment and npm installation on the Mac's internal filesystem:

```bash
cd /Volumes/GRAYSTICK-2/CalHacks2026/synapse
python3 -m venv "$HOME/Library/Application Support/StudBud/venv"
"$HOME/Library/Application Support/StudBud/venv/bin/python" -m pip install -r synapse_vision/requirements/study.txt
```

## Run (two terminals)

Terminal 1, the API:

```bash
cd /Volumes/GRAYSTICK-2/CalHacks2026/synapse
"$HOME/Library/Application Support/StudBud/venv/bin/python" run_studbud.py
```

Terminal 2, the dashboard:

```bash
cd /Volumes/GRAYSTICK-2/CalHacks2026/synapse
python3 run_studbud.py --frontend
```

The frontend launcher copies only frontend sources to `~/Library/Application Support/StudBud/web`, installs locked npm dependencies there when necessary, and serves localhost:5173. It does not copy `.env` files. API credentials are removed from the Vite child environment. Restart this launcher after code updates. Stop either process with Ctrl+C. The API listens on 127.0.0.1:8000; the frontend settings/extension may use the equivalent http://localhost:8000 address.

Open http://localhost:5173/#/capture. The current development test servers may already be running; those use temporary dependencies and should not replace the setup above for future runs.

## Live camera / iPhone

1. On the Study Capture page, select Live camera and press Start camera. Allow Chrome to use the camera.
2. Pick the named iPhone or webcam from the list. Refresh cameras after connecting a device. A selected unavailable device is reported rather than silently replaced.
3. The preview fits the whole camera frame without cropping. Aim it at the page. Capture now sends one still. Automatic guidance sends a changed still after the writing settles, with a minimum ten-second gap.
4. Tudor first reads the visible work and identifies the goal. Write your answer on paper; the next stable meaningful change is reviewed against the pending question. You can also type in the conversation.
5. Stop camera releases it. Switching modes stops automatic observation. New problem clears the current conversation. Tutoring sessions are held in memory, so restarting the API clears them.

iPhone setup: enable Continuity Camera under iPhone Settings → General → AirPlay & Continuity, use the same Apple Account on both devices, connect over USB and trust the Mac, then lock the phone. If it is absent from the browser list, first check whether FaceTime's Video menu lists it. Close FaceTime before using it in Chrome. [Apple instructions](https://support.apple.com/en-us/102546).

## Chrome extension: manual and change-aware screen mode

1. Open chrome://extensions, enable Developer mode, choose Load unpacked, and select this repository's `extension` folder. Reload the extension after updates.
2. Pin/open StudBud on the study website, accept its consent screen, and Allow current website. Restricted and sensitive pages remain blocked.
3. Under Study capture, Capture now sends the visible study tab once. Start change-aware samples locally every second, compares a 4×4 tile grid, and sends the first full image followed by changed tiles. If more than half the screen changes, it sends a full frame instead. The selected 5/10/20/30/60-second value is a minimum AI-request cooldown. Timed capture asks for Chrome's required tab-capture permission.
4. Open tutor opens the dashboard with that exact session ID. The latest still fits the preview and feedback appears in the same conversation. Return to the original study tab to continue automatic screen capture; capture pauses while it is not visible/focused, on another URL, or while the previous request is processing.
5. Stop timed capture from the extension. Stop it before starting a different problem, click New problem in the dashboard, then resume on the new page. The screen session ID stays joined to the extension.

The Camera study button opens a fresh camera session. Passive reading snapshots remain separate, with their existing opt-in sharing and retention controls. In the extension popup, **Page snapshot frequency → Continuous** checks for changes every second and stores only changed frames; this path does not call the AI. Deliberate study captures are sent immediately and are not queued for later upload when offline.

## Tutoring and limits

The tutor uses one small hint/probing question at a time. It is instructed to preserve visible mistakes, label uncertain handwriting, avoid inventing a goal, and stay quiet when its question has not been answered. Only a current explicit typed request such as “Give me the answer for this equation” authorizes a scoped solution. Text photographed on a worksheet does not authorize a solution. Mathematical accuracy and compliance still depend on the model; there is no deterministic proof checker in this path.

If you see a tutor error, check that the backend is running, the key is valid, the configured model is available, and the account has API access/credits. The API deliberately does not return raw SDK errors or credentials to the browser.

## Verification

```bash
node --test extension/tests/*.test.cjs frontend/src/features/study-capture/*.test.js
python -m pytest tests/test_launcher.py
cd synapse_vision
PYTHONPATH=. python -m pytest bridge/tests/test_study.py
```

Full vision/evaluation tests additionally need `requirements/transcribe.txt` and `requirements/eval.txt`; they are not required for the direct-image study route. See `docs/STUDBUD_VERIFICATION.md` for actual results and live-test limitations.

See [Architecture](docs/ARCHITECTURE.md) for the directory layout and ownership boundaries.
