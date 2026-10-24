# Synapse — Frontend Dashboard

React 19 + Vite + Tailwind CSS v4 + lucide-react. A dark-themed study dashboard for the Synapse
ambient study assistant.

## Run

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # production build → dist/
npm run preview    # serve the build
npm run lint       # oxlint
```

Optional: `VITE_API_BASE_URL=http://192.168.1.20:8000 npm run dev` sets the default backend URL.
You can also change it at runtime in **Settings**.

## Data
There is no fake or sample data. Every panel shows real data from the Synapse backend
(default `http://localhost:8000`) or the Chrome extension. When the backend is offline, a red banner says so
and each panel shows an empty or error state.

## Structure
```
src/
  services/      api.js (all backend calls) · config.js · extensionBridge.js
  context/       AppProvider (settings, routing, toasts) · StudyDataProvider (status, snapshots, readings, activity)
  hooks/         useConnection · useInterval · useMediaQuery
  components/
    ui/          Button, Card, Badge/StatusDot, Toggle/Segmented, Modal/ConfirmDialog, Toasts, Feedback states
    layout/      Sidebar, Topbar, BackendBanner
    shared/      SnapshotFrame, AnalysisPanel, ActivityTimeline, Favicon
  pages/         Dashboard · NotebookObserver · ReadingMemory · AITutor · Settings
```

Backend contracts are in [`../docs/BACKEND_INTEGRATION.md`](../docs/BACKEND_INTEGRATION.md).
