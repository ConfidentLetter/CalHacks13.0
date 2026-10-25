# Project structure

The working application root is `synapse/`. This is a small monorepo with one browser frontend, one extension, and one local Python API. Keep those component boundaries rather than introducing a framework or service for every feature.

```text
synapse/
├── README.md                         # Overview and links
├── START_HERE.md                     # Install, run, and manual checks
├── .env.example                     # Names/placeholders only; real .env is ignored
├── run_studbud.py                    # Single launcher for API or frontend
├── frontend/
│   ├── package.json / package-lock.json
│   └── src/
│       ├── pages/StudyCapture.jsx    # Study page composition and browser lifecycle
│       ├── features/study-capture/   # Frame gating, session-view guards, colocated tests
│       ├── context/                  # Shared app/camera/reading state
│       ├── services/                 # Backend client and extension bridge
│       ├── components/               # Shared UI and existing recognition views
│       └── utils/                    # Only genuinely shared utilities
├── extension/
│   ├── manifest.json                # Chrome entry point; paths remain stable
│   ├── background.js / popup.*       # Worker registration and popup UI
│   ├── study-*.js                   # Study capture, heartbeat, and pure policy
│   └── tests/                       # Extension worker/policy tests
├── synapse_vision/
│   ├── bridge/study.py              # Study API, bounded sessions, tutor policy
│   ├── bridge/tests/                # Backend feature tests
│   ├── requirements/study.txt       # Minimal runtime dependencies for this flow
│   ├── app/, capture/, layout/, transcribe/  # Existing vision pipeline
│   ├── contracts/, config/, mocks/  # Existing schemas, tuning, fixtures
│   └── runtime/                    # Ignored legacy pipeline output
├── tests/                          # Repository-level launcher tests
├── docs/
│   ├── ARCHITECTURE.md
│   ├── STUDBUD_INTEGRATION.md        # Integration decisions/API contract
│   ├── STUDBUD_VERIFICATION.md       # Human-readable verification summary
│   └── assets/                     # Documentation images, intentionally kept
├── artifacts/verification/          # Generated test logs, ignored
└── benchmate/                       # Separate upstream electronics project
```

## Simple placement rules

- Put route-level React UI in `pages/`; put study-only logic and its tests in `features/study-capture/`. Shared components and utilities must actually have shared consumers. Do not add barrel files or one-line forwarding layers.
- Keep browser HTTP requests in `services/api.js`, and camera ownership in `CameraProvider`. The extension owns tab screenshots; Python owns credentials and tutoring. Neither browser component opens a separate Python camera handle.
- Keep the study backend together in `bridge/study.py` while it remains a manageable feature module. Split routing and session logic only when size or a second consumer makes that useful; do not create controller/service/repository layers for this small in-memory feature.
- Keep tests beside their owning feature/component. Repository-level tests belong in `tests/`. Runtime requirements remain under the existing Python `requirements/` directory, rather than adding another dependency system.
- Keep credentials in an ignored `.env`. The launcher checks the app-root `.env`, then the original parent `.env` for compatibility. Environment variables take precedence. Only `.env.example` belongs in source control.
- Put generated logs and temporary verification output in ignored `artifacts/`; keep explanatory documentation and deliberate screenshots in `docs/`. Caches, local environments, runtime images, SQLite databases, and macOS `._*` metadata are ignored.

## Visual conventions

The extension and dashboard share cream paper, olive ink, butter highlights, sage accents, and compact softened corners: 6px sheets, 4px controls, and 3–4px labels. Circular shapes are reserved for functional dots, toggle knobs, and notebook punch details. Highlights are loose, overlapping SVG marker strokes behind the words, not rectangular bands. Keep them selective and retain the existing fonts. The extension tokens live in `extension/popup.css`; the dashboard theme/shared surface classes live in `frontend/src/index.css`.

Prefer text labels over decorative icons in navigation, actions and status messages. Previously icon-only buttons must retain a visible label and their accessible name. Keep purposeful animated loading indicators and the animated study buddy; preserve source images and page-annotation graphics. The browser-required extension toolbar assets remain separate from the popup's text-only wordmark.

Motion is CSS-only: approximately 140ms button responses, 180ms entrances, and small transform/opacity changes. Idle mascot motion is disabled; status pulses and skeleton sweeps stop after a few cycles. Loading indicators animate only while needed. Respect `prefers-reduced-motion`, and avoid backdrop blur, large animated shadows, or JavaScript animation loops.

## Source versus local runtime

The source tree can stay on the external drive. The launcher copies frontend source to `~/Library/Application Support/StudBud/web` and runs npm there because the drive does not support npm's executable symlinks. It refreshes only the managed `src/` and `public/` copies, preserving installed dependencies, so moved files do not linger there. Edit the external source tree, not this generated copy. A Python virtual environment should also live on the internal filesystem, as documented in START_HERE. New study sessions/images are bounded and in memory; the legacy recognition pipeline uses its existing ignored `synapse_vision/runtime/` directory. Do not move that older runtime or rename its packages without updating its file-serving contracts and tests.

`benchmate/` is retained from upstream and is not started by the StudBud launcher. The original `camera_management.py`, `main.py`, and their tests in the parent folder are a standalone prototype, not a second copy of the integrated backend. They are preserved for compatibility and the user's newer prompt work. New integration work belongs inside `synapse/`, not in both places.

## Test commands

```bash
# From the application root, with backend test dependencies available:
python -m pytest tests/test_launcher.py
PYTHONPATH=synapse_vision python -m pytest synapse_vision/bridge/tests/test_study.py
node --test extension/tests/*.test.cjs frontend/src/features/study-capture/*.test.js
```

For the complete vision suite, run `PYTHONPATH=. python -m pytest` from `synapse_vision/` after installing its transcription/evaluation test dependencies. Existing unrelated upstream test failures are recorded in STUDBUD_VERIFICATION.md.
