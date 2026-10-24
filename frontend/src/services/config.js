// Central runtime configuration for the dashboard.
// The backend URL can come from (in priority order):
//   1. The Settings page (persisted in localStorage)
//   2. VITE_API_BASE_URL at build time
//   3. The default below
// No secrets live here — API keys belong on the backend only.

export const DEFAULT_API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const SETTINGS_STORAGE_KEY = 'synapse.settings.v1'

export const READING_SECONDS = { min: 1, max: 10, default: 5 }

export const DEFAULT_SETTINGS = {
  apiBaseUrl: DEFAULT_API_BASE_URL,
  readingTrackingEnabled: false,
  minReadingSeconds: 5,
  voiceDemo: false, // "Demo voice": scripted Pip replies while the backend isn't ready
  shareReadingTextWithTutor: false,
  allowedSites: [],
  blockedSites: ['mail.google.com', 'web.whatsapp.com', 'messenger.com', 'discord.com'],
}

export function normalizeBaseUrl(url) {
  return (url || '').trim().replace(/\/+$/, '')
}

export function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_SETTINGS }
    const { dataMode: _legacy, ...saved } = JSON.parse(raw)
    const merged = { ...DEFAULT_SETTINGS, ...saved }
    // Older saves used 15/30/60s; the threshold is now 1–10s.
    const m = merged.minReadingSeconds
    if (!Number.isInteger(m) || m < 1 || m > 10) merged.minReadingSeconds = DEFAULT_SETTINGS.minReadingSeconds
    return merged
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // Storage can be unavailable (private mode); settings stay in memory.
  }
}
