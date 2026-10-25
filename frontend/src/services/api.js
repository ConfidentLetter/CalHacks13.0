// Centralized backend client for the StudBud dashboard.
//
// Every exported function resolves to `{ data }` from the real backend, or throws an
// ApiError. There is no simulated data: if the backend is offline, the UI shows that.
// See docs/BACKEND_INTEGRATION.md for the request/response contracts.

import { DEFAULT_SETTINGS, normalizeBaseUrl } from './config.js'

const DEFAULT_TIMEOUT_MS = 10_000
const NOT_IMPLEMENTED = new Set([404, 405, 501])

const runtime = {
  baseUrl: normalizeBaseUrl(DEFAULT_SETTINGS.apiBaseUrl),
}

// ---- connection store (consumed via useConnection) --------------------------

let connection = {
  baseUrl: runtime.baseUrl,
  backend: 'unknown', // 'unknown' | 'online' | 'offline'
  lastCheckedAt: 0,
  missing: {}, // endpoint → true when the backend answered 404/405/501 (not built yet)
}
const listeners = new Set()

function setConnection(patch) {
  connection = { ...connection, ...patch }
  listeners.forEach((fn) => fn())
}

export function getConnection() {
  return connection
}

export function subscribeConnection(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function markEndpoint(endpoint, missing) {
  const wasMissing = Boolean(connection.missing[endpoint])
  if (wasMissing === missing && connection.backend === 'online') return
  const { [endpoint]: _removed, ...rest } = connection.missing
  setConnection({
    missing: missing ? { ...rest, [endpoint]: true } : rest,
    backend: 'online',
    lastCheckedAt: Date.now(),
  })
}

export function configureApi({ apiBaseUrl }) {
  const baseUrl = normalizeBaseUrl(apiBaseUrl)
  if (baseUrl === runtime.baseUrl) return
  runtime.baseUrl = baseUrl
  setConnection({ baseUrl, backend: 'unknown', lastCheckedAt: 0, missing: {} })
}

// ---- HTTP -------------------------------------------------------------------

export class ApiError extends Error {
  constructor(message, { status = 0, network = false, endpoint = '' } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.network = network
    this.endpoint = endpoint
  }
}

async function http(method, path, body, { baseUrl = runtime.baseUrl, timeoutMs = DEFAULT_TIMEOUT_MS, cache } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let res
  try {
    res = await fetch(`${baseUrl}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      ...(cache ? { cache } : {}),
    })
  } catch (err) {
    const timedOut = err?.name === 'AbortError'
    throw new ApiError(timedOut ? 'Request timed out.' : 'Could not reach the StudBud backend.', {
      network: true,
      endpoint: path,
    })
  } finally {
    clearTimeout(timer)
  }

  if (!res.ok) {
    let detail = ''
    try {
      const j = await res.json()
      detail = j.error || j.message || j.detail || ''
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail || `Backend responded with HTTP ${res.status}.`, { status: res.status, endpoint: path })
  }
  if (res.status === 204) return null
  return res.json()
}

async function call(endpoint, realFn) {
  try {
    const data = await realFn()
    markEndpoint(endpoint, false)
    return { data }
  } catch (err) {
    if (err.network) setConnection({ backend: 'offline', lastCheckedAt: Date.now() })
    else if (NOT_IMPLEMENTED.has(err.status)) {
      markEndpoint(endpoint, true)
      err.message = `${endpoint} isn’t implemented on the backend yet.`
    } else markEndpoint(endpoint, false)
    throw err
  }
}

// ---- response normalization -------------------------------------------------

export function resolveUrl(url) {
  if (!url) return null
  if (/^(https?:|data:|blob:)/.test(url)) return url
  return `${runtime.baseUrl}${url.startsWith('/') ? '' : '/'}${url}`
}

function normalizeSnapshot(s) {
  if (!s) return null
  const imageUrl = s.imageBase64
    ? `data:${s.mimeType || 'image/jpeg'};base64,${s.imageBase64}`
    : resolveUrl(s.imageUrl)
  return { ...s, imageUrl, capturedAt: s.capturedAt || s.timestamp || null }
}

export function normalizeReading(r) {
  return {
    ...r,
    id: String(r.id),
    title: r.title || r.url,
    durationSec: Number(r.durationSec ?? r.duration ?? 0),
    timestamp: r.timestamp || r.createdAt || new Date().toISOString(),
    excerpt: r.excerpt ?? r.text ?? '',
    source: r.source || 'backend',
  }
}

// ---- endpoints --------------------------------------------------------------

/** GET /api/status — also used as the backend health check. */
export function getStatus() {
  return call('GET /api/status', () => http('GET', '/api/status', null, { timeoutMs: 3000 }))
}

/** Probe a backend URL without changing global state (Settings → Test connection). */
export async function testConnection(baseUrl) {
  const started = performance.now()
  const data = await http('GET', '/api/status', null, { baseUrl: normalizeBaseUrl(baseUrl), timeoutMs: 3000 })
  return { data, latencyMs: Math.round(performance.now() - started) }
}

/** GET /api/camera/latest[?fresh=true] — fresh asks the camera for a new frame now (optional). */
export async function getLatestSnapshot({ fresh = false } = {}) {
  const res = await call(
    'GET /api/camera/latest',
    () => http('GET', `/api/camera/latest${fresh ? '?fresh=true' : ''}`)
  )
  return { ...res, data: normalizeSnapshot(res.data) }
}

/**
 * Live camera stream URL. The backend may report `camera.streamUrl` (absolute or relative) and
 * `camera.streamType` ('mjpeg' | 'video') in GET /api/status; otherwise we assume MJPEG at
 * GET /api/camera/stream. This is only a URL — the browser connects to it directly.
 */
export function getStreamInfo(camera) {
  return {
    url: resolveUrl(camera?.streamUrl || '/api/camera/stream'),
    type: camera?.streamType === 'video' ? 'video' : 'mjpeg',
  }
}

/**
 * POST /api/camera/capture — hardware adapter only: ask the Pi/ESP32 for one still right now.
 * Returns the new snapshot. 404/501 → reported as not implemented; never faked.
 */
export async function captureNow() {
  const res = await call('POST /api/camera/capture', () => http('POST', '/api/camera/capture', {}, { timeoutMs: 20_000 }))
  return { ...res, data: normalizeSnapshot(res.data) }
}

/** Turn a captured frame (from CameraProvider.captureFrame) into the API's `image` field. */
function frameBody(frame) {
  if (!frame) return undefined
  return frame.source === 'hardware'
    ? { source: 'hardware', snapshotId: frame.snapshotId, capturedAt: frame.capturedAt }
    : {
        source: 'webcam',
        mimeType: frame.mimeType,
        base64: frame.base64,
        width: frame.width,
        height: frame.height,
        capturedAt: frame.capturedAt,
      }
}

/** POST /api/camera/analyze { image } — analyze one still grabbed from the live camera. */
export function analyzeFrame(frame) {
  return call('POST /api/camera/analyze', () =>
    http('POST', '/api/camera/analyze', { image: frameBody(frame) }, { timeoutMs: 110_000 }),
  )
}

// ---- page twins (T4 routes served through the bridge, same origin) ----------

/** GET /twin/:id — the full page twin: lines with bbox/crops/readings, image size, changes. */
export function getTwin(snapshotId) {
  return call('GET /twin/:id', () => http('GET', `/twin/${encodeURIComponent(snapshotId)}`))
}

/**
 * GET /twin/latest — newest stored twin. In real mode before any snapshot the server returns the mock twin
 * flagged `_fallback`; that is never shown as the student's work, so it resolves to `null` here.
 */
export async function getLatestTwin() {
  const res = await call('GET /twin/latest', () => http('GET', '/twin/latest'))
  return { ...res, data: res.data?._fallback ? null : res.data }
}

/** POST /api/reading — save a reading record (the extension posts here too). */
export async function saveReading(record) {
  const res = await call(
    'POST /api/reading',
    () => http('POST', '/api/reading', record)
  )
  return { ...res, data: normalizeReading(res.data) }
}

/** GET /api/reading/history?limit=N */
export async function getReadingHistory({ limit = 100 } = {}) {
  const res = await call(
    'GET /api/reading/history',
    () => http('GET', `/api/reading/history?limit=${limit}`)
  )
  const items = Array.isArray(res.data) ? res.data : res.data?.items || []
  return { ...res, data: items.map(normalizeReading) }
}

/** DELETE /api/reading/:id */
export function deleteReading(id) {
  return call(
    'DELETE /api/reading/:id',
    () => http('DELETE', `/api/reading/${encodeURIComponent(id)}`)
  )
}

/**
 * Clear all reading history. Tries the optional bulk endpoint
 * DELETE /api/reading/history first, then falls back to deleting one by one.
 */
export function clearReadingHistory() {
  return call(
    'DELETE /api/reading/history',
    async () => {
      try {
        return await http('DELETE', '/api/reading/history')
      } catch (err) {
        if (!NOT_IMPLEMENTED.has(err.status)) throw err
        const history = await http('GET', '/api/reading/history?limit=1000')
        const items = Array.isArray(history) ? history : history?.items || []
        await Promise.all(items.map((r) => http('DELETE', `/api/reading/${encodeURIComponent(r.id)}`)))
        return { cleared: true, count: items.length }
      }
    }
  )
}

/** POST /api/chat { message, history, includeNotebook, includeReading, includeReadingText } */
export function sendChat({
  message,
  history = [],
  includeNotebook = true,
  includeReading = true,
  includeReadingText = false,
  frame = null,
}) {
  // `image` is the single still captured when the question was asked — not a video stream.
  const body = { message, history, includeNotebook, includeReading, includeReadingText, image: frameBody(frame) }
  return call(
    'POST /api/chat',
    () => http('POST', '/api/chat', body, { timeoutMs: 90_000 })
  )
}

// Shared session for deliberate screen capture and changed/stable camera stills.
export function observeStudy(sessionId, image, force = false) {
  return call('POST /api/study/observe', () =>
    http('POST', '/api/study/observe', { sessionId, image, force }, { timeoutMs: 90_000 }))
}

export function sendStudyMessage(sessionId, message) {
  return call('POST /api/study/message', () =>
    http('POST', '/api/study/message', { sessionId, message }, { timeoutMs: 90_000 }))
}

export function getStudySession(sessionId) {
  return call('GET /api/study/session', () =>
    http('GET', `/api/study/session/${encodeURIComponent(sessionId)}`, null, { cache: 'no-store' }))
}

export function clearStudySession(sessionId) {
  return call('DELETE /api/study/session', () =>
    http('DELETE', `/api/study/session/${encodeURIComponent(sessionId)}`, null, { timeoutMs: 90_000 }))
}
