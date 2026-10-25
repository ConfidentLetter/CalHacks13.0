importScripts('tile-diff.js', 'study-policy.js', 'study-capture.js', 'pdf-extract.js', 'pdf-diff.js', 'pdf-observer.js')

// StudBud background service worker (Manifest V3).
// - Registers the reading detector only on approved + permission-granted sites
// - Turns content-script progress into reading records after the minimum active time
// - Queues records in chrome.storage.local and syncs them to POST /api/reading
// - Takes opt-in page snapshots at a chosen interval or continuously when tiles change
// - Answers the popup and the dashboard bridge

const READER_ID = 'synapse-reader'
const FLUSH_ALARM = 'synapse-flush'
const MAX_RECORDS = 500

const DEFAULT_SETTINGS = {
  consentGiven: false,
  trackingEnabled: false,
  shareText: false,
  minReadingSeconds: 5, // 1–10s of active reading before a page is saved
  backendUrl: 'http://localhost:8000',
  dashboardUrl: 'https://stud-bud-xi.vercel.app',
  allowedSites: [],
  blockedSites: ['mail.google.com', 'web.whatsapp.com', 'messenger.com', 'discord.com', 'slack.com'],
  screenshotsEnabled: false,
  screenshotIntervalSec: 10,
  uploadScreenshots: false,
  // PDF observer: off until the user opts in; separate from text reading tracking.
  pdfMode: 'manual', // 'manual' | 'smart'
  pdfIntervalSec: 10,
  pdfAutoConsent: false,
  pdfCrops: {}, // host → { mode: 'auto' | 'custom' | 'full', rect? }
}

// ---- storage helpers --------------------------------------------------------

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings')
  const merged = { ...DEFAULT_SETTINGS, ...(settings || {}) }
  if (!validReadingSeconds(merged.minReadingSeconds)) merged.minReadingSeconds = DEFAULT_SETTINGS.minReadingSeconds
  if (![0, 10, 20, 30, 60].includes(merged.screenshotIntervalSec)) merged.screenshotIntervalSec = DEFAULT_SETTINGS.screenshotIntervalSec
  return merged
}

function validReadingSeconds(n) {
  return Number.isInteger(n) && n >= 1 && n <= 10
}

async function setSettings(patch) {
  const next = { ...(await getSettings()), ...patch }
  await chrome.storage.local.set({ settings: next })
  return next
}

async function getRecords() {
  const { records } = await chrome.storage.local.get('records')
  return records || []
}

async function setRecords(records) {
  await chrome.storage.local.set({ records: records.slice(0, MAX_RECORDS) })
}

// ---- site rules -------------------------------------------------------------

const hostOf = (url) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

const matchesSite = (host, site) => host === site || host.endsWith(`.${site}`)
const sitePatterns = (site) => [`*://${site}/*`, `*://*.${site}/*`]

function isRestrictedUrl(url) {
  return !/^https?:\/\//.test(url || '') || /^https:\/\/(chrome\.google\.com\/webstore|chromewebstore\.google\.com)/.test(url)
}

async function hasSitePermission(site) {
  return chrome.permissions.contains({ origins: sitePatterns(site) })
}

async function siteStatus(url) {
  const settings = await getSettings()
  if (isRestrictedUrl(url)) return { state: 'restricted', site: '' }
  const host = hostOf(url)
  const blocked = settings.blockedSites.find((s) => matchesSite(host, s))
  if (blocked) return { state: 'blocked', site: blocked, host }
  const allowed = settings.allowedSites.find((s) => matchesSite(host, s))
  if (!allowed) return { state: 'not-allowed', site: host, host }
  if (!(await hasSitePermission(allowed))) return { state: 'needs-permission', site: allowed, host }
  return { state: 'approved', site: allowed, host }
}

/** (Re)register content.js for every allowed, non-blocked site that has a granted permission. */
async function syncContentScripts() {
  const settings = await getSettings()
  const matches = []
  if (settings.consentGiven && settings.trackingEnabled) {
    for (const site of settings.allowedSites) {
      if (settings.blockedSites.some((b) => matchesSite(site, b))) continue
      if (await hasSitePermission(site)) matches.push(...sitePatterns(site))
    }
  }
  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [READER_ID] })
  if (existing.length) await chrome.scripting.unregisterContentScripts({ ids: [READER_ID] })
  if (matches.length) {
    await chrome.scripting.registerContentScripts([
      { id: READER_ID, js: ['content.js'], matches, runAt: 'document_idle', persistAcrossSessions: true },
    ])
  }
}

async function injectIntoTab(tabId) {
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] })
  } catch {
    /* restricted page or permission missing */
  }
}

// ---- reading sessions -------------------------------------------------------

async function handleProgress(msg, tab) {
  const settings = await getSettings()
  const status = await siteStatus(msg.url)
  if (!settings.trackingEnabled || status.state !== 'approved') return
  const previous = (await chrome.storage.session.get(`live:${tab.id}`))[`live:${tab.id}`]
  const priorPdf = previous?.url === msg.url ? previous : {}

  // Live state for the popup timer (cleared when the browser closes).
  await chrome.storage.session.set({
    [`live:${tab.id}`]: {
      sessionId: msg.sessionId,
      url: msg.url,
      title: msg.title,
      activeSec: msg.activeSec,
      state: msg.state,
      qualified: msg.qualified,
      isPdf: msg.isPdf,
      text: String(msg.text || priorPdf.text || '').slice(0, 4000),
      pdfPages: msg.pdfPages || priorPdf.pdfPages,
      at: Date.now(),
    },
  })

  await maybeSnapshot(msg, tab, settings)

  if (!msg.qualified) return

  const records = await getRecords()
  const idx = records.findIndex((r) => r.id === msg.sessionId)
  if (idx === -1) {
    records.unshift({
      id: msg.sessionId,
      title: msg.title,
      url: msg.url,
      domain: hostOf(msg.url),
      favicon: tab.favIconUrl || null,
      excerpt: String(msg.text || '').slice(0, 4000),
      pdfPages: msg.pdfPages,
      startedAt: msg.startedAt,
      timestamp: new Date().toISOString(),
      durationSec: msg.activeSec,
      isPdf: Boolean(msg.isPdf),
      synced: false,
    })
    await setRecords(records)
    flush()
  } else {
    const r = records[idx]
    // Only rewrite storage (and resync) when duration meaningfully changes.
    const newText = String(msg.text || '').slice(0, 4000)
    if (msg.activeSec - r.durationSec >= 10 || msg.state === 'hidden' || (newText && newText !== r.excerpt)) {
      records[idx] = { ...r, durationSec: msg.activeSec, title: msg.title || r.title,
        excerpt: newText || r.excerpt, pdfPages: msg.pdfPages || r.pdfPages, synced: false }
      await setRecords(records)
      if (newText) flush()
    }
  }
}

// ---- page snapshots ---------------------------------------------------------
// Chrome can only capture the visible tab of a window, and only with the
// <all_urls> permission, which the popup requests when snapshots are switched on.

const ALL_URLS = { origins: ['<all_urls>'] }
const MAX_SHOTS = 20
const SHOT_MAX_WIDTH = 1280
// Never photograph these parts of a site (grades, inbox, profiles, live quizzes), even when approved.
const SHOT_SKIP_PATH =
  /(grades?|gradebook|conversations|inbox|messages?|profile|settings|account|log-?in|sign-?in|quizzes\/\d+\/take|take_quiz|exam)/i

const lastShot = new Map() // tabId → { at, sig }

async function getShots() {
  const { shots } = await chrome.storage.local.get('shots')
  return shots || []
}

async function setShots(shots) {
  await chrome.storage.local.set({ shots: shots.slice(0, MAX_SHOTS) })
}

/** Why a snapshot would or wouldn't be taken on this URL right now. */
async function snapshotEligibility(settings, url) {
  if (!settings.screenshotsEnabled || !settings.consentGiven || !settings.trackingEnabled) return 'off'
  if (!(await chrome.permissions.contains(ALL_URLS))) return 'no-permission'
  if ((await siteStatus(url)).state !== 'approved') return 'not-approved'
  try {
    if (SHOT_SKIP_PATH.test(new URL(url).pathname)) return 'skipped-page'
  } catch {
    return 'not-approved'
  }
  return 'ready'
}

function setRecBadge(tabId, on) {
  chrome.action.setBadgeText({ tabId, text: on ? 'REC' : '' }).catch(() => {})
  if (on) {
    chrome.action.setBadgeBackgroundColor({ tabId, color: '#A4BA8D' }).catch(() => {})
    chrome.action.setBadgeTextColor?.({ tabId, color: '#494638' })?.catch?.(() => {})
  }
}

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(binary)
}

/** Downscale to ≤1280px wide JPEG and compute a 4×4 grid of local pixel signatures. */
async function shrink(dataUrl) {
  const bitmap = await createImageBitmap(await (await fetch(dataUrl)).blob())
  const scale = Math.min(1, SHOT_MAX_WIDTH / bitmap.width)
  const width = Math.max(4, Math.floor(bitmap.width * scale / TileDiff.GRID_SIZE) * TileDiff.GRID_SIZE)
  const height = Math.max(4, Math.floor(bitmap.height * scale / TileDiff.GRID_SIZE) * TileDiff.GRID_SIZE)
  const canvas = new OffscreenCanvas(width, height)
  canvas.getContext('2d').drawImage(bitmap, 0, 0, width, height)
  const blob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.6 })

  const tiny = new OffscreenCanvas(TileDiff.SAMPLE_SIZE, TileDiff.SAMPLE_SIZE)
  const tctx = tiny.getContext('2d')
  tctx.drawImage(canvas, 0, 0, TileDiff.SAMPLE_SIZE, TileDiff.SAMPLE_SIZE)
  const sig = TileDiff.grayscale(tctx.getImageData(0, 0, TileDiff.SAMPLE_SIZE, TileDiff.SAMPLE_SIZE).data)
  bitmap.close()

  return { base64: toBase64(await blob.arrayBuffer()), width, height, sig }
}

async function changedTileAtlas(dataUrl, tiles) {
  const bitmap = await createImageBitmap(await (await fetch(dataUrl)).blob())
  const scale = Math.min(1, SHOT_MAX_WIDTH / bitmap.width)
  const width = Math.max(4, Math.floor(bitmap.width * scale / TileDiff.GRID_SIZE) * TileDiff.GRID_SIZE)
  const height = Math.max(4, Math.floor(bitmap.height * scale / TileDiff.GRID_SIZE) * TileDiff.GRID_SIZE)
  const source = new OffscreenCanvas(width, height)
  source.getContext('2d').drawImage(bitmap, 0, 0, width, height)
  const tileWidth = width / TileDiff.GRID_SIZE
  const tileHeight = height / TileDiff.GRID_SIZE
  const columns = Math.min(TileDiff.GRID_SIZE, tiles.length)
  const rows = Math.ceil(tiles.length / TileDiff.GRID_SIZE)
  const atlas = new OffscreenCanvas(tileWidth * columns, tileHeight * rows)
  const ctx = atlas.getContext('2d')
  const ordered = [...tiles].sort((a, b) => a - b)
  ordered.forEach((tile, index) => {
    ctx.drawImage(source, (tile % TileDiff.GRID_SIZE) * tileWidth, Math.floor(tile / TileDiff.GRID_SIZE) * tileHeight,
      tileWidth, tileHeight, (index % columns) * tileWidth, Math.floor(index / columns) * tileHeight, tileWidth, tileHeight)
  })
  bitmap.close()
  const blob = await atlas.convertToBlob({ type: 'image/jpeg', quality: 0.75 })
  return { base64: toBase64(await blob.arrayBuffer()), tiles: ordered, frameWidth: width, frameHeight: height }
}

async function maybeSnapshot(msg, tab, settings) {
  const ready = msg.state === 'active' && (await snapshotEligibility(settings, msg.url)) === 'ready'
  setRecBadge(tab.id, ready)
  if (!ready) return

  const prev = lastShot.get(tab.id)
  if (settings.screenshotIntervalSec > 0 && prev && Date.now() - prev.at < settings.screenshotIntervalSec * 1000) return
  lastShot.set(tab.id, { ...prev, at: Date.now() }) // claim this slot before any await

  // captureVisibleTab photographs whatever is showing, so make sure it's still this page.
  const current = await chrome.tabs.get(tab.id).catch(() => null)
  if (!current?.active || current.url !== msg.url) return

  let shot
  try {
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: 80 })
    shot = await shrink(dataUrl)
  } catch {
    return // window not focused, devtools open, or Chrome refused
  }
  if (!TileDiff.changedTiles(prev?.sig, shot.sig).length) return // no meaningful tile changed
  lastShot.set(tab.id, { at: Date.now(), sig: shot.sig })

  const shots = await getShots()
  shots.unshift({
    id: `shot-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
    sessionId: msg.sessionId,
    url: msg.url,
    title: msg.title,
    capturedAt: new Date().toISOString(),
    mimeType: 'image/jpeg',
    width: shot.width,
    height: shot.height,
    imageBase64: shot.base64,
    synced: false,
  })
  await setShots(shots)
  flushShots()
}

let flushingShots = false
async function flushShots() {
  const settings = await getSettings()
  if (flushingShots || !settings.uploadScreenshots) return 0
  flushingShots = true
  let sent = 0
  try {
    const pending = (await getShots()).filter((s) => !s.synced).reverse() // oldest first
    for (const s of pending) {
      try {
        const { synced: _s, ...body } = s
        const res = await fetchWithTimeout(
          `${settings.backendUrl}/api/reading/screenshot`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
          10_000,
        )
        if (!res.ok) break
        sent++
        const latest = await getShots()
        await setShots(latest.map((x) => (x.id === s.id ? { ...x, synced: true } : x)))
      } catch {
        break // backend offline — keep them queued
      }
    }
  } finally {
    flushingShots = false
  }
  return sent
}

async function clearAllBadges() {
  lastShot.clear()
  for (const t of await chrome.tabs.query({})) setRecBadge(t.id, false)
}

// ---- backend sync -----------------------------------------------------------

async function fetchWithTimeout(url, opts = {}, ms = 4000) {
  const ctrl = new AbortController()
  const externalSignal = opts.signal
  const onAbort = () => ctrl.abort()
  if (externalSignal?.aborted) ctrl.abort()
  externalSignal?.addEventListener('abort', onAbort, { once: true })
  const t = setTimeout(() => ctrl.abort(), ms)
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal })
  } finally {
    clearTimeout(t)
    externalSignal?.removeEventListener('abort', onAbort)
  }
}

async function checkBackend() {
  const { backendUrl } = await getSettings()
  try {
    const res = await fetchWithTimeout(`${backendUrl}/api/status`, {}, 2500)
    return res.ok
  } catch {
    return false
  }
}

let flushing = false
async function flush() {
  if (flushing) return { synced: 0, pending: 0, online: false }
  flushing = true
  try {
    const settings = await getSettings()
    if (!settings.consentGiven) return { synced: 0, pending: 0, online: false }
    const records = await getRecords()
    const pending = records.filter((r) => !r.synced)
    let synced = 0
    for (const r of pending) {
      const body = {
        id: r.id,
        title: r.title,
        url: r.url,
        domain: r.domain,
        favicon: r.favicon,
        startedAt: r.startedAt,
        timestamp: r.timestamp,
        durationSec: r.durationSec,
        source: 'extension',
        // Page text is uploaded only with explicit consent.
        ...(settings.shareText && r.excerpt ? { text: r.excerpt } : {}),
      }
      try {
        const res = await fetchWithTimeout(`${settings.backendUrl}/api/reading`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!res.ok) break
        r.synced = true
        synced++
      } catch {
        break // backend offline — keep the rest queued
      }
    }
    if (synced) {
      // Re-read to avoid clobbering records updated while we were syncing.
      const latest = await getRecords()
      const done = new Map(pending.filter((r) => r.synced).map((r) => [r.id, r.durationSec]))
      await setRecords(latest.map((r) => (done.get(r.id) === r.durationSec ? { ...r, synced: true } : r)))
    }
    return { synced, pending: pending.length - synced, online: synced > 0 || (await checkBackend()) }
  } finally {
    flushing = false
  }
}

async function deleteRecords(ids) {
  const settings = await getSettings()
  const records = await getRecords()
  const removing = records.filter((r) => ids.includes(r.id))
  await setRecords(records.filter((r) => !ids.includes(r.id)))
  // Best effort: also remove already-synced copies from the backend.
  for (const r of removing.filter((x) => x.synced)) {
    fetchWithTimeout(`${settings.backendUrl}/api/reading/${encodeURIComponent(r.id)}`, { method: 'DELETE' }).catch(() => {})
  }
}

async function bridgeInfo() {
  const settings = await getSettings()
  const records = await getRecords()
  return {
    info: {
      version: chrome.runtime.getManifest().version,
      trackingEnabled: settings.consentGiven && settings.trackingEnabled,
      consentGiven: settings.consentGiven,
      minReadingSeconds: settings.minReadingSeconds,
      allowedSites: settings.allowedSites,
      blockedSites: settings.blockedSites,
      pendingCount: records.filter((r) => !r.synced).length,
    },
    readings: records.map(({ synced, ...r }) => ({ ...r, synced })),
  }
}

// ---- message router ---------------------------------------------------------

const handlers = {
  'reading:pdf': async (msg, sender) => {
    if (!sender.tab || sender.tab.url !== msg.url) throw new Error('PDF request does not match the study tab')
    const settings = await getSettings()
    if (!settings.consentGiven || !settings.trackingEnabled || SHOT_SKIP_PATH.test(new URL(msg.url).pathname) || (await siteStatus(msg.url)).state !== 'approved') throw new Error('Approve this study page before reading its PDF')
    return PDFExtractor.extractFromUrl(msg.url)
  },
  'popup:read-pdf': async ({ tabId, url }) => {
    if (!(await getSettings()).consentGiven) throw new Error('Accept StudBud consent before reading PDFs')
    const tab = await chrome.tabs.get(tabId)
    if (tab.url !== url || SHOT_SKIP_PATH.test(new URL(url).pathname) || (await siteStatus(url)).state !== 'approved') throw new Error('Approve this study tab before reading its PDF')
    const result = await PDFExtractor.extractFromUrl(url)
    if (result.error) throw new Error(result.error)
    if (!result.text) throw new Error('No readable text found. Use screen capture for scanned pages.')
    // Navigation during extraction must not save a document for a different tab.
    if ((await chrome.tabs.get(tabId)).url !== url) throw new Error('Study tab changed. Open the PDF and try again.')
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(url))
    const id = `ext-pdf-${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`
    const now = new Date().toISOString()
    const records = await getRecords()
    const previous = records.find((r) => r.id === id)
    await setRecords([{ ...previous, id, title: tab.title || 'PDF document', url, domain: hostOf(url),
      excerpt: result.text, pdfPages: result.pages, isPdf: true, synced: false,
      durationSec: previous?.durationSec || 0, startedAt: previous?.startedAt || now, timestamp: now },
      ...records.filter((r) => r.id !== id)])
    await chrome.storage.session.set({ [`live:${tabId}`]: {
      url, title: tab.title, isPdf: true, pdfPages: result.pages, text: result.text,
      activeSec: previous?.durationSec || 0, state: 'idle', qualified: true, at: Date.now(),
    } })
    flush()
    return { pages: result.pages }
  },
  'study:heartbeat': studyHeartbeat,
  'popup:study-capture': studyPopupHandler((msg) => studyBegin(msg, false)),
  'popup:study-start': studyPopupHandler((msg) => studyBegin(msg, true)),
  'popup:study-stop': studyPopupHandler(() => studyStop()),
  'popup:study-logs': studyPopupHandler(async () => ({ logs: await studyGetLogs() })),

  'pdf:heartbeat': pdfHeartbeat,
  'pdf:crop': (msg, sender) => pdfSaveCrop(msg, sender).catch(async (err) => {
    await pdfUpdate({ status: `Error — ${err.message}`, tone: 'err' })
    throw err
  }),
  'popup:pdf-capture': studyPopupHandler(async (msg) => pdfCapture(await pdfPopupTab(msg), { manual: true })),
  'popup:pdf-start': studyPopupHandler((msg) => pdfStart(msg)),
  'popup:pdf-stop': studyPopupHandler(() => pdfStop('Off — paused by you')),
  'popup:pdf-select-area': studyPopupHandler(async (msg) => {
    const tab = await pdfPopupTab(msg)
    if ((await siteStatus(tab.url)).state !== 'approved') throw new Error('Allow this website first.')
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['pdf-crop.js'] })
      .catch(() => { throw new Error('This viewer can’t show the area picker. Use “Whole visible tab”.') })
    return true
  }),
  'popup:pdf-settings': studyPopupHandler(async ({ url, mode, cropMode, autoConsent }) => {
    if (mode === 'manual' || mode === 'smart') {
      await setSettings({ pdfMode: mode })
      if (mode === 'manual') await pdfStop()
    }
    if (typeof autoConsent === 'boolean') {
      await setSettings({ pdfAutoConsent: autoConsent })
      if (!autoConsent) await pdfStop()
    }
    if (cropMode) await pdfSetCropMode({ url, mode: cropMode })
    return true
  }),

  'reading:progress': (msg, sender) => sender.tab && handleProgress(msg, sender.tab),

  'popup:state': async ({ tabId, url }) => {
    const [settings, records, status, live] = await Promise.all([
      getSettings(),
      getRecords(),
      siteStatus(url),
      chrome.storage.session.get(`live:${tabId}`),
    ])
    const liveState = live[`live:${tabId}`]
    const shots = await getShots()
    return {
      settings,
      status,
      live: liveState && liveState.url === url ? liveState : null,
      study: await studyLoaded.then(() => ({ ...studyState })),
      pdf: await pdfPopupState(url),
      savedCount: records.length,
      pendingCount: records.filter((r) => !r.synced).length,
      shots: {
        count: shots.length,
        pending: shots.filter((s) => !s.synced).length,
        latestId: shots[0]?.id || null,
        latestAt: shots[0]?.capturedAt || null,
        here: await snapshotEligibility(settings, url),
      },
    }
  },

  'popup:check-backend': () => checkBackend(),

  'popup:consent': async () => {
    await setSettings({ consentGiven: true, trackingEnabled: true })
    await syncContentScripts()
    return true
  },

  'popup:set-tracking': async ({ enabled }) => {
    await setSettings({ trackingEnabled: enabled })
    await syncContentScripts()
    return true
  },

  // Popup has already obtained the host permission via chrome.permissions.request.
  'popup:approve-site': async ({ site, tabId, unblock }) => {
    const s = await getSettings()
    await setSettings({
      allowedSites: s.allowedSites.includes(site) ? s.allowedSites : [...s.allowedSites, site],
      blockedSites: s.blockedSites.filter((b) => b !== site && b !== unblock),
    })
    await syncContentScripts()
    if (tabId) await injectIntoTab(tabId)
    return true
  },

  'popup:remove-site': async ({ site }) => {
    const s = await getSettings()
    await setSettings({ allowedSites: s.allowedSites.filter((x) => x !== site) })
    await chrome.permissions.remove({ origins: sitePatterns(site) }).catch(() => {})
    await syncContentScripts()
    return true
  },

  'popup:save-page': async ({ record }) => {
    const records = await getRecords()
    records.unshift({ ...record, synced: false })
    await setRecords(records)
    return flush()
  },

  'popup:update-settings': async ({ patch }) => {
    await setSettings(patch)
    await syncContentScripts()
    if (patch.screenshotsEnabled === false) await clearAllBadges()
    if (patch.uploadScreenshots) flushShots()
    return true
  },

  'popup:flush': async () => {
    const result = await flush()
    return { ...result, shotsSent: await flushShots() }
  },

  'popup:delete-shots': async () => {
    await setShots([])
    lastShot.clear()
    return true
  },

  'popup:delete-all': async () => {
    await studyStop()
    await pdfStop()
    await deleteRecords((await getRecords()).map((r) => r.id))
    await setShots([])
    await chrome.storage.session.clear()
    await clearAllBadges()
    return true
  },

  'bridge:get': () => bridgeInfo(),
  'bridge:delete': ({ id }) => deleteRecords([id]),
  'bridge:clear': async () => {
    await setRecords([])
    await setShots([])
    return true
  },
  'bridge:settings': async ({ settings: incoming }) => {
    const s = await getSettings()
    const patch = {}
    // The dashboard can pause tracking, but can never turn it on without in-extension consent.
    if (typeof incoming.trackingEnabled === 'boolean' && (s.consentGiven || !incoming.trackingEnabled)) {
      patch.trackingEnabled = incoming.trackingEnabled
    }
    if (Array.isArray(incoming.allowedSites)) patch.allowedSites = incoming.allowedSites
    if (Array.isArray(incoming.blockedSites)) patch.blockedSites = incoming.blockedSites
    if (validReadingSeconds(incoming.minReadingSeconds)) patch.minReadingSeconds = incoming.minReadingSeconds
    if (typeof incoming.backendUrl === 'string' && /^https?:\/\//.test(incoming.backendUrl)) {
      patch.backendUrl = incoming.backendUrl.replace(/\/+$/, '')
    }
    const changed = Object.keys(patch).some((k) => JSON.stringify(patch[k]) !== JSON.stringify(s[k]))
    if (changed) {
      await setSettings(patch)
      await syncContentScripts()
    }
    return changed
  },
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.target === 'pdf-offscreen') return false
  const handler = handlers[msg?.type]
  if (!handler) return false
  Promise.resolve().then(() => handler(msg, sender))
    .then(sendResponse)
    .catch((err) => sendResponse({ error: String(err?.message || err) }))
  return true // async response
})

// ---- lifecycle --------------------------------------------------------------

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({ settings: await getSettings() })
  await syncContentScripts()
  chrome.alarms.create(FLUSH_ALARM, { periodInMinutes: 1 })
})

chrome.runtime.onStartup.addListener(() => {
  syncContentScripts()
  chrome.alarms.create(FLUSH_ALARM, { periodInMinutes: 1 })
})

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === FLUSH_ALARM) {
    flush()
    flushShots()
  }
})

chrome.permissions.onRemoved.addListener(() => syncContentScripts())
chrome.tabs.onRemoved.addListener((tabId) => {
  studyLoaded.then(() => { if (studyState.tabId === tabId) studyStop('Study tab closed') })
  chrome.storage.session.remove(`live:${tabId}`)
  lastShot.delete(tabId)
})
