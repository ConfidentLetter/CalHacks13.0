// Smart PDF screenshot observer. Visual only: captures the visible authorized tab, crops to the
// PDF area when known, and keeps a frame only when PdfDiff finds a meaningful change.
// Scheduling comes from pdf-heartbeat.js in the page (MV3: no worker timers or sub-minute alarms).
const PDF_KEY = 'pdfObserver'
const PDF_BASELINE_KEY = 'pdfBaseline'
const PDF_CONFIRM_MS = 1500 // a changed frame must look the same this much later (render settling)
const PDF_SAVE_MAX_WIDTH = 1600
const pdfBaselines = new Map() // tabId → last KEPT frame { key, w, h, pixels }
let pdfPending = null // changed frame waiting for confirmation { tabId, key, pixels, confirmAt }
let pdfBusy = false
let pdfState = null
const pdfLoaded = chrome.storage.session.get([PDF_KEY, PDF_BASELINE_KEY]).then((stored) => {
  pdfState = stored[PDF_KEY] || { running: false, status: 'Off', tone: '', saved: 0, skipped: 0 }
  const b = stored[PDF_BASELINE_KEY] // survive a worker restart without a duplicate save
  if (b?.b64) pdfBaselines.set(b.tabId, { key: b.key, w: b.w, h: b.h, pixels: Uint8ClampedArray.from(atob(b.b64), (c) => c.charCodeAt(0)) })
  return pdfState
})

async function pdfUpdate(patch, generation) {
  await pdfLoaded
  if (generation && pdfState.generation !== generation) return
  pdfState = { ...pdfState, ...patch }
  await chrome.storage.session.set({ [PDF_KEY]: pdfState })
}

function pdfForget(tabId) {
  pdfBaselines.delete(tabId)
  if (pdfPending?.tabId === tabId) pdfPending = null
  chrome.storage.session.get(PDF_BASELINE_KEY).then((s) => {
    if (s[PDF_BASELINE_KEY]?.tabId === tabId) chrome.storage.session.remove(PDF_BASELINE_KEY)
  })
}

// Runs in the page's top frame only. Cross-origin viewer frames are never read.
function detectPdfViewer() {
  const viewport = { width: innerWidth, height: innerHeight }
  const sensitive = Boolean(document.querySelector('input[type="password"]'))
  if (document.contentType === 'application/pdf') return { viewport, rect: null, documentId: location.href, page: null, sensitive, kind: 'direct' }
  const looksPdf = (s) => /\.pdf\b|application\/pdf|pdfjs|canvadoc|docviewer|viewer\.html/i.test(s || '')
  let best = null
  for (const el of document.querySelectorAll('embed, object, iframe, #viewerContainer, .pdfViewer')) {
    const src = el.getAttribute('src') || el.getAttribute('data') || ''
    const pdfLike = (el.type || '').includes('pdf') || looksPdf(src) || el.id === 'viewerContainer' || el.classList.contains('pdfViewer')
    if (!pdfLike) continue
    const r = el.getBoundingClientRect()
    const x = Math.max(0, r.left)
    const y = Math.max(0, r.top)
    const width = Math.min(viewport.width, r.right) - x
    const height = Math.min(viewport.height, r.bottom) - y
    if (width < 80 || height < 80) continue
    if (!best || width * height > best.area) {
      let documentId = location.href
      try { if (src) documentId = new URL(src, location.href).href } catch { /* keep page URL */ }
      best = { area: width * height, rect: { x, y, width, height }, documentId }
    }
  }
  // Only a real page-number control (pdf.js style) counts; never guess from page text.
  const input = document.querySelector('#pageNumber, input[aria-label*="page" i]')
  const n = input ? Number.parseInt(input.value, 10) : NaN
  return { viewport, rect: best?.rect || null, documentId: best?.documentId || null,
    page: Number.isInteger(n) && n > 0 ? n : null, sensitive, kind: best ? 'embedded' : 'none' }
}

async function pdfDocId(raw) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw))
  return `doc-${Array.from(new Uint8Array(digest).slice(0, 8), (b) => b.toString(16).padStart(2, '0')).join('')}`
}

async function pdfTabVisible(tabId, windowId, url) {
  const [tabs, win] = await Promise.all([
    chrome.tabs.query({ active: true, windowId }),
    chrome.windows.get(windowId).catch(() => null),
  ])
  const tab = tabs[0]
  return Boolean(win?.focused && tab && tab.id === tabId && !tab.pendingUrl && (!url || tab.url === url))
}

async function pdfGate(tab, manual) {
  const settings = await getSettings()
  const gate = PdfDiff.captureGate({
    consent: settings.consentGiven,
    siteState: (await siteStatus(tab.url)).state,
    safeUrl: StudyPolicy.safeStudyUrl(tab.url, settings.dashboardUrl),
    incognito: tab.incognito,
    autoConsent: settings.pdfAutoConsent,
    hasCapturePermission: await chrome.permissions.contains(ALL_URLS),
    manual,
    tab,
    target: pdfState.running ? pdfState : { tabId: tab.id, windowId: tab.windowId },
    focused: (await chrome.windows.get(tab.windowId).catch(() => null))?.focused,
  })
  return { settings, gate }
}

const PDF_GATE_TEXT = {
  'no-consent': 'Accept StudBud consent first.',
  restricted: 'This page can’t be captured (browser, incognito, dashboard, or sensitive page).',
  'not-approved': 'Paused — allow this website before PDF capture.',
  'no-auto-consent': 'Tick “Allow automatic screenshots” first.',
  'no-permission': 'Smart interval needs Chrome’s visible-tab capture permission.',
  paused: 'Paused — return to the PDF tab in a focused window.',
}

function pdfCropFor(settings, url) {
  return settings.pdfCrops?.[hostOf(url)] || { mode: 'auto' }
}

/** Capture → crop → sample → decide → save. Returns the observer state. */
async function pdfCapture(tab, { manual, generation }) {
  await pdfLoaded
  if (pdfBusy) return { ...pdfState, busy: true }
  pdfBusy = true
  let bitmap
  try {
    const { settings, gate } = await pdfGate(tab, manual)
    if (gate !== 'ok') {
      await pdfUpdate({ status: PDF_GATE_TEXT[gate], tone: gate === 'paused' || gate === 'not-approved' ? 'warn' : 'err' }, generation)
      return { ...pdfState, error: manual ? PDF_GATE_TEXT[gate] : undefined }
    }
    await pdfUpdate({ status: 'Capturing…', tone: '', lastAttemptAt: Date.now() }, generation)
    let viewer = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: detectPdfViewer })
      .then((r) => r?.[0]?.result).catch(() => null)
    if (!viewer) {
      // Chrome's own PDF viewer tab has no scriptable DOM; capture it whole.
      if (!/\.pdf(?:[?#]|$)/i.test(tab.url)) throw new Error('This page can’t be checked. Reload it and try again.')
      viewer = { viewport: null, rect: null, documentId: tab.url, page: null, sensitive: false, kind: 'direct' }
    }
    if (viewer.sensitive) throw new Error('This page has a password field and is never captured.')

    const viewEpoch = studyViewEpoch
    if (!(await pdfTabVisible(tab.id, tab.windowId, tab.url))) throw new Error(PDF_GATE_TEXT.paused)
    let dataUrl
    try {
      dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: 90 })
    } catch {
      throw new Error('Chrome refused the screenshot. Check the capture permission and keep the PDF tab focused.')
    }
    if (viewEpoch !== studyViewEpoch || !(await pdfTabVisible(tab.id, tab.windowId, tab.url))) {
      throw new Error('Tab changed during capture; image discarded.')
    }
    if (generation && pdfState.generation !== generation) return { ...pdfState }

    bitmap = await createImageBitmap(await (await fetch(dataUrl)).blob())
    const image = { width: bitmap.width, height: bitmap.height }
    const cropSetting = pdfCropFor(settings, tab.url)
    const crop = cropSetting.mode === 'custom' ? PdfDiff.fractionToPixels(cropSetting.rect, image)
      : cropSetting.mode === 'auto' && viewer.rect ? PdfDiff.cropToPixels(viewer.rect, viewer.viewport, image) : null
    const area = crop || { x: 0, y: 0, width: image.width, height: image.height }

    const { w, h } = PdfDiff.sampleSize(area.width, area.height)
    const tiny = new OffscreenCanvas(w, h)
    const tctx = tiny.getContext('2d', { willReadFrequently: true })
    tctx.drawImage(bitmap, area.x, area.y, area.width, area.height, 0, 0, w, h)
    const documentId = await pdfDocId(viewer.documentId || tab.url)
    const frame = { key: PdfDiff.baselineKey({ documentId, crop, imageWidth: image.width, imageHeight: image.height }),
      w, h, pixels: tctx.getImageData(0, 0, w, h).data }

    if (!manual) {
      const verdict = PdfDiff.decide(pdfBaselines.get(tab.id), frame)
      if (verdict.action === 'blank') {
        await pdfUpdate({ status: 'Waiting for the PDF to finish rendering…', tone: '' }, generation)
        return { ...pdfState }
      }
      if (verdict.action === 'unchanged') {
        pdfPending = null
        await pdfUpdate({ status: 'Unchanged — not saved', tone: '', skipped: (pdfState.skipped || 0) + 1 }, generation)
        return { ...pdfState }
      }
      // Changed: keep it only if it is still the same a moment later (page transitions, lazy rendering).
      const stable = pdfPending?.tabId === tab.id && pdfPending.key === frame.key &&
        !PdfDiff.compareGrid(pdfPending.pixels, frame.pixels, w, h).changed
      if (!stable) {
        pdfPending = { tabId: tab.id, key: frame.key, pixels: frame.pixels, confirmAt: Date.now() + PDF_CONFIRM_MS }
        await pdfUpdate({ status: 'Change detected — confirming…', tone: '' }, generation)
        return { ...pdfState }
      }
    }
    pdfPending = null

    const saved = await PdfDiff.observe(pdfBaselines, tab.id, frame, { manual }, async (verdict) => {
      // Keep the crop at native resolution, capped so 20 stored shots fit in extension storage.
      const scale = Math.min(1, PDF_SAVE_MAX_WIDTH / area.width)
      const out = new OffscreenCanvas(Math.round(area.width * scale), Math.round(area.height * scale))
      out.getContext('2d').drawImage(bitmap, area.x, area.y, area.width, area.height, 0, 0, out.width, out.height)
      const blob = await out.convertToBlob({ type: 'image/jpeg', quality: 0.8 })
      const capturedAt = new Date().toISOString()
      const shots = await getShots()
      shots.unshift({
        id: `pdf-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
        kind: 'pdf',
        captureMode: manual ? 'manual' : 'smart',
        url: tab.url,
        title: tab.title,
        tabId: tab.id,
        documentId,
        pageNumber: viewer.page,
        viewer: crop ? (cropSetting.mode === 'custom' ? 'custom-area' : viewer.kind) : 'full-tab',
        changedRegions: verdict.diff?.changedRegions || [],
        regionScores: verdict.diff ? verdict.diff.regions.map((r) => Number(r.fraction.toFixed(4))) : [],
        capturedAt,
        mimeType: 'image/jpeg',
        width: out.width,
        height: out.height,
        imageBase64: toBase64(await blob.arrayBuffer()),
        synced: false,
      })
      await setShots(shots) // throws on storage failure → baseline stays on the previous kept frame
      await pdfUpdate({ lastSavedAt: capturedAt })
    })
    const b = pdfBaselines.get(tab.id)
    chrome.storage.session.set({ [PDF_BASELINE_KEY]: { tabId: tab.id, key: b.key, w: b.w, h: b.h, b64: toBase64(b.pixels.buffer) } }).catch(() => {})
    flushShots() // uploads only when “Upload snapshots to backend” is on; otherwise stays local
    await pdfUpdate({ status: saved.reason === 'manual' ? 'Saved (manual)' : 'Saved — new PDF content', tone: 'ok', saved: (pdfState.saved || 0) + 1 })
    return { ...pdfState }
  } catch (err) {
    const message = String(err?.message || 'PDF capture failed.')
    await pdfUpdate({ status: `Error — ${message}`, tone: 'err' }, generation)
    return { ...pdfState, error: message }
  } finally {
    bitmap?.close()
    pdfBusy = false
  }
}

async function pdfPopupTab({ tabId, windowId, url }) {
  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab || tab.windowId !== windowId || tab.url !== url || !tab.active) throw new Error('The tab changed. Reopen the popup on the PDF.')
  return tab
}

async function pdfStart(msg) {
  await pdfLoaded
  if (!PdfDiff.validInterval(msg.intervalSec)) throw new Error('Choose an interval between 5 and 300 seconds.')
  const tab = await pdfPopupTab(msg)
  await setSettings({ pdfIntervalSec: msg.intervalSec })
  if (pdfState.running) await pdfStop() // one session at a time; gate against this tab
  const { gate } = await pdfGate(tab, false)
  if (gate !== 'ok') throw new Error(PDF_GATE_TEXT[gate])
  // A new session always starts from a fresh baseline and fresh counters.
  pdfBaselines.clear()
  pdfPending = null
  await chrome.storage.session.remove(PDF_BASELINE_KEY)
  await pdfUpdate({ running: true, tabId: tab.id, windowId: tab.windowId, intervalSec: msg.intervalSec, generation: crypto.randomUUID(),
    lastAttemptAt: 0, saved: 0, skipped: 0, lastSavedAt: null, status: 'Ready — watching this tab', tone: 'ok' })
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['pdf-heartbeat.js'] })
  } catch {
    // Chrome's built-in PDF viewer can't host the page timer.
    await pdfStop('Error — Smart interval can’t run on this viewer. Use Capture Current PDF Page.')
    throw new Error('Smart interval can’t run on this viewer. Use Capture Current PDF Page instead.')
  }
  return { ...pdfState }
}

async function pdfStop(status = 'Off') {
  await pdfLoaded
  pdfBaselines.clear()
  pdfPending = null
  await chrome.storage.session.remove(PDF_BASELINE_KEY)
  await pdfUpdate({ running: false, generation: crypto.randomUUID(), status, tone: status.startsWith('Error') ? 'err' : '' })
  return { ...pdfState }
}

async function pdfHeartbeat(msg, sender) {
  await pdfLoaded
  const tab = sender.tab
  if (!pdfState.running || tab?.id !== pdfState.tabId || tab.windowId !== pdfState.windowId) return { stop: true }
  if (pdfBusy || msg.url !== tab.url) return
  const now = Date.now()
  const confirming = pdfPending?.tabId === tab.id
  const due = confirming ? now >= pdfPending.confirmAt : now - (pdfState.lastAttemptAt || 0) >= pdfState.intervalSec * 1000
  if (!due) return
  return pdfCapture(tab, { manual: false, generation: pdfState.generation })
}

/** The user's dragged rectangle from pdf-crop.js, as fractions of the viewport. */
async function pdfSaveCrop(msg, sender) {
  const tab = sender.tab
  if (!tab || msg.url !== tab.url || (await siteStatus(tab.url)).state !== 'approved') throw new Error('Allow this website first.')
  const r = msg.rect || {}
  const ok = ['x', 'y', 'width', 'height'].every((k) => Number.isFinite(r[k])) && r.width > 0.05 && r.height > 0.05 &&
    r.x >= 0 && r.y >= 0 && r.x + r.width <= 1.001 && r.y + r.height <= 1.001
  if (!ok) throw new Error('Select a larger area.')
  const settings = await getSettings()
  await setSettings({ pdfCrops: { ...settings.pdfCrops, [hostOf(tab.url)]: { mode: 'custom', rect: r } } })
  pdfForget(tab.id) // a new crop is a new baseline
  await pdfUpdate({ status: 'Custom PDF area saved', tone: 'ok' })
  return true
}

async function pdfSetCropMode({ url, mode }) {
  if (!['auto', 'custom', 'full'].includes(mode)) throw new Error('Unknown crop mode.')
  const settings = await getSettings()
  const host = hostOf(url)
  const current = settings.pdfCrops?.[host] || {}
  await setSettings({ pdfCrops: { ...settings.pdfCrops, [host]: { ...current, mode } } })
  pdfBaselines.clear()
  pdfPending = null
  return true
}

async function pdfPopupState(url) {
  await pdfLoaded
  const settings = await getSettings()
  const crop = pdfCropFor(settings, url)
  return { ...pdfState, mode: settings.pdfMode, intervalSec: pdfState.running ? pdfState.intervalSec : settings.pdfIntervalSec,
    autoConsent: settings.pdfAutoConsent, cropMode: crop.mode, hasCustomArea: Boolean(crop.rect) }
}

// Pause immediately when the user leaves the PDF tab; resume status when they return.
async function pdfViewChanged() {
  await pdfLoaded
  if (!pdfState.running) return
  pdfPending = null
  const visible = await pdfTabVisible(pdfState.tabId, pdfState.windowId)
  await pdfUpdate(visible ? { status: 'Ready — watching this tab', tone: 'ok' } : { status: PDF_GATE_TEXT.paused, tone: 'warn' })
}
chrome.tabs.onActivated?.addListener(() => { pdfViewChanged().catch(() => {}) })
chrome.windows.onFocusChanged?.addListener(() => { pdfViewChanged().catch(() => {}) })
chrome.tabs.onUpdated?.addListener((tabId, change) => {
  pdfLoaded.then(async () => {
    if (!pdfState.running || tabId !== pdfState.tabId) return
    if (change.url || change.status === 'loading') pdfPending = null
    // The page timer dies with each navigation; re-add it (fails silently on unapproved sites).
    if (change.status === 'complete') await chrome.scripting.executeScript({ target: { tabId }, files: ['pdf-heartbeat.js'] })
  }).catch(() => {})
})
chrome.tabs.onRemoved?.addListener((tabId) => {
  pdfLoaded.then(() => {
    pdfForget(tabId)
    if (pdfState.running && pdfState.tabId === tabId) pdfStop('Off — PDF tab closed')
  })
})
