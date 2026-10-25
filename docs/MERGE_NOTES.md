# Branch integration — October 24, 2026

Integrated the latest fetched `origin/main` (`1d4ef4e`), `origin/ethan`
(`e472bfb`), and `origin/feat/pdf-reading` (`c702cf4`) on local `main`.
The recent uncommitted UI work was saved first as `13ee45f`.

## Choices

- Main's paper styling, white chat/notebook panels, shortened instructions,
  dashboard conversation links, and sidebar fill/press animation are preserved.
- Ethan's math rendering, click-to-talk, silence detection, voice reply input,
  and playback fixes are merged. Launcher speech transcription defaults on;
  `SV_STT=0` still disables it. The empty `.env.example` setup template is retained.
- The PDF branch's URL extraction and popup panel are merged. Its remote PDF.js
  loader was replaced with the locally bundled official `pdfjs-dist@6.4.299`
  parser/worker and a Chrome offscreen document. No additional all-site dashboard
  bridge injection was retained.
- Late-arriving PDF text now updates both the reading record and popup state.
  Manual extraction uses a backend-compatible hashed record ID, verifies the tab
  and site approval, and respects consent. Downloads are limited to 20 MB; text
  extraction reads at most 10 pages and stores at most 4,000 characters.

## Checks

- 56 Node tests: extension capture/popup policies, PDF integration, math parser,
  reading deletion, and conversation links.
- 77 Python tests: launcher and bridge API.
- Vite production build passes. Existing large-bundle warning remains.
- Frontend lint: no errors; two existing set-state-in-effect warnings remain.
- Browser smoke test: the actual packaged PDF.js parser and worker extracted the
  exact expected text from a synthetic one-page PDF.

The full installed Chrome extension flow and physical microphone/camera were not
exercised. Reload the unpacked extension and refresh the dashboard. Restart the
launcher to adopt the new speech-transcription default. Scanned, locked, local,
or inaccessible authenticated PDF URLs may still require screen capture.
