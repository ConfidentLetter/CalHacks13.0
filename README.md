# StudBud — Cal Hacks 13.0

**StudBud integration:** start with [START_HERE.md](START_HERE.md) for local/iPhone camera observation, manual/timed Chrome study captures, and one shared Socratic tutoring session. No Raspberry Pi is required for this flow.

See [Architecture](docs/ARCHITECTURE.md) for the component layout, test locations, and local runtime directories.

For GitHub-connected Vercel hosting, see [Deployment](docs/DEPLOYMENT.md).

Ambient AI study assistant: an overhead camera watches your notebook, a Chrome extension remembers what you
read, and an AI tutor answers questions using both.

| Folder | What | Owner |
|---|---|---|
| `frontend/` | React dashboard | frontend |
| `extension/` | Chrome extension (Manifest V3) | frontend |
| `docs/BACKEND_INTEGRATION.md` | API contracts for the backend team | shared |
| backend / hardware | Claude, SpacetimeDB, Pi/ESP32 camera | backend team |

## Quick start

```bash
cd frontend && npm install && npm run dev     # → http://localhost:5173
```
The dashboard shows real data only. Until the backend is up at `http://localhost:8000`, it shows an **Offline** banner and empty states.

## Load the Chrome extension
1. Open `chrome://extensions`.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and select the `extension/` folder.
4. Pin **StudBud** from the puzzle-piece menu and click it. Accept the consent screen.
5. Go to any website you want tracked (Canvas, Notion, Figma, YouTube, docs…), open the popup, click **Allow current website**, then approve Chrome's permission prompt. Each entry covers that domain and its subdomains.
6. Read actively (scroll or move the mouse) for 30s. The timer fills up and the page is saved.
7. With the dashboard open at `localhost:5173`, the page shows up live in **Reading Memory**, even without a backend.

After editing extension files, click the reload ↻ icon on the extension card. Tabs that were already open
need a page refresh to pick up the reader.

### Extension privacy model
- Nothing is tracked until you accept the consent screen. Each site needs your explicit approval and
  Chrome's own per-site permission prompt (`optional_host_permissions`).
- Active reading means the tab is visible, the window is focused, and you've interacted within the last 60s.
- Pages with password fields, and URLs that look like login, checkout, account, or messaging pages, are skipped.
  Inputs, forms, and editable areas are removed before text is extracted.
- Page text is stored locally and uploaded **only** if you enable "Share page text with backend".
- Records are queued in `chrome.storage.local` while the backend is offline and retried every minute.
- You can pause tracking, remove sites, or **Delete all stored data** from the popup.
- **Page snapshots (opt-in):** when you turn them on, StudBud captures the tab you're looking at every 10s, but only
  while you're actively reading an approved site such as Canvas. Chrome can't capture background tabs. A **REC**
  badge on the extension icon shows when snapshots are being taken. Grade, inbox, profile, and quiz-taking pages are
  never captured. Unchanged frames are skipped. The last 20 stay on your device and are uploaded only if you enable
  "Upload snapshots to backend". Turning snapshots on asks for Chrome's "read all sites" permission, because
  that's the only way Chrome allows tab capture.
- **PDFs:** On an approved online PDF tab, use **Read this PDF** in the popup. The bundled PDF.js parser
  saves up to 4,000 characters from the first 10 pages. Scanned or locked PDFs may need screen capture;
  local files are not supported. Text uploads still require the text-sharing setting. Chrome 116+ is required.
  `chrome://` pages and the Web Store can't be accessed by any extension.

## Manual test checklist
**Dashboard (no backend running)**
- [ ] A red Offline banner names the backend URL. Status cards say "Backend offline". No fake pages, snapshots, or replies appear.
- [ ] Each button gives honest feedback: Start Capture shows an error toast, Refresh Snapshot shows an error,
      and the Tutor shows an error bubble with "Try again".
- [ ] Reading Memory shows pages saved by the extension (when it's loaded), even without the backend.
- [ ] Settings: the camera toggle disables Start Capture. Adding a site rejects invalid input and duplicates.
      Test connection reports an error. Clear and Reset both ask for confirmation.
- [ ] At 375px width: hamburger menu works, and there's no horizontal scroll. Keyboard: Tab and arrow keys work; Esc closes dialogs.

**Dashboard (with the backend)**
- [ ] Settings → Test says "Connected in N ms", and the banner disappears.
- [ ] Start/Stop Capture, Refresh, Analyze My Work, Tutor chat, Add page, and Delete all hit the real endpoints.

**Extension**
- [ ] Popup shows the consent screen first. After accepting, it shows the current site.
- [ ] On `chrome://extensions`, the popup says it can't run there, and Save is disabled.
- [ ] Track a site, approve Chrome's prompt, and read. The timer advances only while you're interacting.
      Switching tabs pauses it. At 30s it shows "Saved ✓".
- [ ] Disable Tracking stops the timer. Enable resumes it.
- [ ] Save Current Page works on an unapproved page. On a login page (one with a password field), it refuses.
- [ ] With the backend offline, the count shows "N pending sync". Start the backend, click Sync now, and pending drops to 0.
- [ ] With the dashboard open, a new page appears in Reading Memory with a "New" highlight.
      Deleting it in the dashboard removes it from the extension.
- [ ] Delete all stored data (click twice) resets the counts.
- [ ] Click **+ Canvas** in Settings & privacy, open a Canvas course page, and turn on **Page snapshots**. While you
      scroll, the REC badge shows and a new thumbnail appears about every 10s. Switch tabs and capture stops.
      Open the Grades or Inbox page and the status says it's never captured.

