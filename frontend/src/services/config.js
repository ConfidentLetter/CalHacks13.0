// Central runtime configuration for the dashboard.
// The backend URL can come from (in priority order):
//   1. The Settings page (persisted in localStorage)
//   2. VITE_API_BASE_URL at build time
//   3. The default below
// No secrets live here — API keys belong on the backend only.

export const DEFAULT_API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const SETTINGS_STORAGE_KEY = 'synapse.settings.v1'

export const CAPTURE_INTERVALS = [30, 60, 120]

export const DEFAULT_SETTINGS = {
  apiBaseUrl: DEFAULT_API_BASE_URL,
  cameraEnabled: true,
  captureIntervalSec: 60,
  readingTrackingEnabled: true,
  minReadingSeconds: 30,
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
    return { ...DEFAULT_SETTINGS, ...saved }
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
