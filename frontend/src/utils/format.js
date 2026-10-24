export function formatDuration(totalSec) {
  const s = Math.max(0, Math.round(totalSec || 0))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}

export function timeAgo(iso, now = Date.now()) {
  if (!iso) return '—'
  const diff = Math.round((now - new Date(iso).getTime()) / 1000)
  if (diff < 10) return 'just now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export function formatClock(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export function formatDateTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function domainOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url || ''
  }
}

export function isToday(iso) {
  return new Date(iso).toDateString() === new Date().toDateString()
}

/** Accepts "docs.python.org", "https://docs.python.org/3/", "*.example.com" → bare host. */
export function normalizeSite(input) {
  const raw = (input || '').trim().toLowerCase()
  if (!raw) return ''
  const withScheme = /^[a-z]+:\/\//.test(raw) ? raw : `https://${raw.replace(/^\*\./, '')}`
  try {
    return new URL(withScheme).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

export function cx(...parts) {
  return parts.filter(Boolean).join(' ')
}

/** Short unique id; works on plain-http LAN URLs where crypto.randomUUID is unavailable. */
export function uid() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
