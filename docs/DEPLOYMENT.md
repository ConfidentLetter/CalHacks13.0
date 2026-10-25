# Deploy StudBud

The React dashboard is a static Vite application suitable for Vercel. The Python
vision/tutoring backend is a separate, long-running service with local data storage;
this frontend deployment does not deploy that service.

## Connect GitHub to Vercel

1. Commit the project files to your GitHub repository. Keep `.env`, keys, database
   files, and local runtime folders out of commits (the repository ignores these).
2. In Vercel, choose **Add New → Project**, import the GitHub repository, and select
   **Vite** as the framework.
3. Set **Root Directory** to `frontend` if this repository starts at the StudBud
   application folder. If your GitHub repository contains the outer `CalHacks2026`
   folder structure with this app in `synapse`, use `synapse/frontend` instead.
4. Build command: `npm run build`. Output directory: `dist`. Install command: `npm ci`.
5. Set `VITE_API_BASE_URL` to the HTTPS URL of your deployed Python backend, without
   `/api` or a trailing slash. Set it for Production and Preview as needed.
6. Deploy. Vercel supplies an HTTPS website address. The app uses hash routes, so
   its dashboard is at `https://YOUR-SITE.vercel.app/#/dashboard`.

Vercel automatically deploys commits pushed to the configured production branch
(usually `main`), and creates preview deployments for pull requests. Changes to
`VITE_API_BASE_URL` require a new deployment because Vite embeds it during build.
In an existing browser, Settings → Backend URL can override this build default.

Never put an AI provider key in a `VITE_*` variable: those values are public in the
browser bundle. Keep `ANTHROPIC_API_KEY` exclusively in backend secret settings.

## Backend requirements

For use from any device, the Python backend must be hosted at a public HTTPS
address with persistent storage. A frontend pointing at `localhost:8000` connects
to each visitor's own computer, not your Mac. The backend entry point is
`bridge.server:app`, run from `synapse_vision` using the bridge requirements.
Configure a writable persistent data directory using the existing backend storage
settings, and run in real mode with camera source `upload` (browser cameras supply
images; the server should not open a physical camera).

Set `SV_CORS_ORIGINS=https://YOUR-SITE.vercel.app` on the backend. Add other exact
origins separated by commas when needed. CORS does not authenticate users. This
prototype has shared reading/session data and no per-user access control; before
exposing a paid AI backend or private study history publicly, add authentication,
per-user storage isolation, and usage limits. A static frontend deployment alone
can be shared, but tutoring and backend history require the reachable backend.

## Chrome extension with the hosted dashboard

The extension currently injects its dashboard bridge only on localhost. For your
specific deployed site, add `https://YOUR-SITE.vercel.app/*` to both
`host_permissions` and the dashboard bridge's `content_scripts[0].matches` in
`extension/manifest.json`. Do not replace these with all websites. Reload the
unpacked extension in `chrome://extensions`, then refresh the hosted dashboard.
In the extension's settings set Dashboard URL to your hosted site and Backend URL
to your HTTPS backend. Grant the extension access to that backend when Chrome asks.
A hosted website does not install the extension automatically.

The browser camera continues to use the visiting device's camera, including an
available iPhone Continuity Camera on a Mac. Camera access requires HTTPS or
localhost and the user's browser permission.

References: [Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite),
[Git deployments](https://vercel.com/docs/git),
[environment variables](https://vercel.com/docs/environment-variables).
