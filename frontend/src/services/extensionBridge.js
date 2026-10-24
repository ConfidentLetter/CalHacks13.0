// Talks to the Synapse Chrome extension through window.postMessage.
// The extension injects extension/bridge.js into this dashboard page (only when
// the page carries <meta name="synapse-dashboard">), which relays messages to
// chrome.storage. This lets reading records captured by the extension show up
// here live, even when the backend is not running.

const FROM_PAGE = 'synapse-dashboard'
const FROM_EXTENSION = 'synapse-extension'

let state = {
  connected: false,
  info: null, // { version, trackingEnabled, allowedSites, blockedSites, pendingCount }
  readings: [],
  lastEventAt: 0,
}
const listeners = new Set()
let started = false

function set(patch) {
  state = { ...state, ...patch }
  listeners.forEach((fn) => fn())
}

export function getBridgeState() {
  return state
}

export function subscribeBridge(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function post(type, payload) {
  window.postMessage({ source: FROM_PAGE, type, payload }, window.location.origin)
}

function onMessage(event) {
  if (event.source !== window || event.origin !== window.location.origin) return
  const msg = event.data
  if (!msg || msg.source !== FROM_EXTENSION) return

  switch (msg.type) {
    case 'hello':
    case 'status':
      set({ connected: true, info: msg.payload || null })
      break
    case 'readings':
      set({
        connected: true,
        readings: (msg.payload?.items || []).map((r) => ({ ...r, source: 'extension' })),
        lastEventAt: Date.now(),
      })
      break
    default:
      break
  }
}

export function startBridge() {
  if (started || typeof window === 'undefined') return
  started = true
  window.addEventListener('message', onMessage)
  post('hello')
  // The content script may load after the app; retry the handshake briefly.
  let tries = 0
  const t = setInterval(() => {
    if (state.connected || ++tries > 10) return clearInterval(t)
    post('hello')
  }, 1000)
}

export const bridge = {
  deleteReading: (id) => post('delete-reading', { id }),
  clearReadings: () => post('clear-readings'),
  updateSettings: (settings) => post('update-settings', settings),
}
