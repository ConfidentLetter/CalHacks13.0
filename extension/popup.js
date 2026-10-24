// Synapse popup. All state lives in background.js; this file only renders it.

const $ = (id) => document.getElementById(id)
const send = (type, data = {}) => chrome.runtime.sendMessage({ type, ...data })
const sitePatterns = (site) => [`*://${site}/*`, `*://*.${site}/*`]

let tab = null
let state = null
let confirmDeleteUntil = 0
let shownShotId = null
const ALL_URLS = { origins: ['<all_urls>'] }
const CANVAS_SITE = 'instructure.com'

function fmt(sec) {
  const s = Math.max(0, Math.floor(sec || 0))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function flash(text, tone = '') {
  const el = $('message')
  el.textContent = text
  el.className = `message ${tone}`
  clearTimeout(flash.t)
  flash.t = setTimeout(() => (el.textContent = ''), 4000)
}

// Runs inside the page (via chrome.scripting) for "Save Current Page".
// Skips pages with password fields and strips every form control.
function extractPageForSynapse() {
  if (document.querySelector('input[type="password"]')) return { sensitive: true }
  const isPdf = document.contentType === 'application/pdf'
  let text = ''
  if (!isPdf) {
    const root = document.querySelector('article') || document.querySelector('main') || document.querySelector('[role="main"]') || document.body
    const clone = root.cloneNode(true)
    clone
      .querySelectorAll('input, textarea, select, button, form, [contenteditable], script, style, noscript, nav, footer, aside, header, iframe, svg, [aria-hidden="true"], [hidden]')
      .forEach((el) => el.remove())
    text = (clone.innerText || clone.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 4000)
  }
  return { title: document.title, text, isPdf }
}

// ---- rendering --------------------------------------------------------------

function renderSite() {
  const { status, settings } = state
  $('site-title').textContent = tab?.title || 'No active tab'
  $('site-host').textContent = status.host || (tab?.url ? new URL(tab.url).protocol.replace(':', '') + ' page' : '')
  const icon = $('site-icon')
  if (tab?.favIconUrl && /^https?:|^data:/.test(tab.favIconUrl)) icon.src = tab.favIconUrl
  else icon.src = 'icons/icon32.png'

  const el = $('site-status')
  const action = $('site-action')
  action.hidden = true
  const tracking = settings.consentGiven && settings.trackingEnabled

  switch (status.state) {
    case 'restricted':
      el.textContent = 'Synapse can’t run on browser pages (chrome://, the Web Store, new tabs).'
      el.className = 'site-status'
      break
    case 'blocked':
      el.textContent = 'This site is on your blocked list and is never tracked.'
      el.className = 'site-status bad'
      action.hidden = false
      action.textContent = 'Unblock & track this site'
      break
    case 'not-allowed':
      el.textContent = 'Not approved — reading here is not tracked.'
      el.className = 'site-status'
      action.hidden = false
      action.textContent = `Track ${status.site}`
      break
    case 'needs-permission':
      el.textContent = 'On your allow list — Chrome needs your permission to read this site.'
      el.className = 'site-status warn'
      action.hidden = false
      action.textContent = 'Grant access'
      break
    case 'approved':
      el.textContent = tracking ? '✓ Approved — tracking active reading' : 'Approved — tracking is paused'
      el.className = `site-status ${tracking ? 'ok' : 'warn'}`
      action.hidden = false
      action.textContent = 'Stop tracking this site'
      break
  }
  $('save-page').disabled = status.state === 'restricted' || status.state === 'blocked'
}

function renderTimer() {
  const { live, settings, status } = state
  const min = settings.minReadingSeconds || 30
  const sec = live?.activeSec || 0
  const pct = Math.min(100, Math.round((sec / min) * 100))
  $('timer').textContent = fmt(sec)
  $('bar-fill').style.width = `${pct}%`
  $('bar').setAttribute('aria-valuenow', String(pct))

  const pill = $('timer-state')
  const hint = $('timer-hint')
  const tracking = settings.consentGiven && settings.trackingEnabled
  pill.className = 'pill'
  if (!tracking) {
    pill.textContent = 'Paused'
    hint.textContent = 'Tracking is paused. Nothing is being recorded.'
  } else if (status.state !== 'approved') {
    pill.textContent = 'Not tracking'
    hint.textContent = 'Approve this site to track reading here, or use “Save Current Page”.'
  } else if (!live) {
    pill.textContent = 'Waiting'
    hint.textContent = 'Scroll or move the mouse on the page to start the timer. Reload the tab if it was open before approval.'
  } else if (live.qualified) {
    pill.textContent = 'Saved ✓'
    pill.className = 'pill saved'
    hint.textContent = live.isPdf
      ? 'Saved title, URL and time. PDF text can’t be read from Chrome’s viewer.'
      : 'Saved to Reading Memory. Time keeps updating while you read.'
  } else if (live.state === 'active') {
    pill.textContent = 'Reading…'
    pill.className = 'pill active'
    hint.textContent = `Saves after ${min}s of active reading (${Math.max(0, min - sec)}s to go).`
  } else {
    pill.textContent = live.state === 'hidden' ? 'Tab hidden' : 'Idle'
    hint.textContent = 'Timer pauses when the tab isn’t visible/focused or you stop interacting.'
  }
}

const SHOT_STATUS = {
  ready: ['on — snapping this page while you read', 'on'],
  'not-approved': ['on — this site isn’t approved, so nothing is captured', 'warn'],
  'skipped-page': ['on — grades, inbox, profile & quiz pages are never captured', 'warn'],
  'no-permission': ['Chrome permission was removed — turn on again to re-grant', 'warn'],
  off: ['off', ''],
}

async function renderShots() {
  const { shots, settings } = state
  const on = settings.screenshotsEnabled
  const [text, tone] = SHOT_STATUS[on ? shots.here : 'off'] || SHOT_STATUS.off
  const status = $('shots-status')
  status.textContent = on && shots.here === 'ready' ? `on — every ${settings.screenshotIntervalSec}s while you read` : text
  status.className = `shots-status ${tone}`
  const toggle = $('shots-toggle')
  toggle.textContent = on ? 'Turn off' : 'Turn on'
  toggle.className = `btn ${on ? 'ghost' : 'secondary'}`
  const uploading = settings.uploadScreenshots
  $('shots-count').textContent = `${shots.count} ${uploading ? `saved · ${shots.pending} to upload` : 'stored on this device'}`
  $('shots-delete').disabled = !shots.count

  const thumb = $('shot-thumb')
  if (!shots.latestId) {
    thumb.hidden = true
    shownShotId = null
  } else if (shots.latestId !== shownShotId) {
    shownShotId = shots.latestId
    const { shots: stored = [] } = await chrome.storage.local.get('shots')
    const latest = stored[0]
    if (latest) {
      thumb.src = `data:${latest.mimeType};base64,${latest.imageBase64}`
      thumb.title = `${latest.title} · ${new Date(latest.capturedAt).toLocaleTimeString()}`
      thumb.hidden = false
    }
  }
}

async function renderSiteList() {
  const list = $('site-list')
  list.textContent = ''
  const sites = state.settings.allowedSites
  if (!sites.length) {
    const li = document.createElement('li')
    li.className = 'empty'
    li.textContent = 'No approved sites yet.'
    list.append(li)
    return
  }
  for (const site of sites) {
    const granted = await chrome.permissions.contains({ origins: sitePatterns(site) })
    const li = document.createElement('li')
    if (!granted) {
      li.className = 'pending'
      li.title = 'Allowed, but Chrome access not granted yet — visit the site and click “Grant access”.'
    }
    li.append(document.createTextNode(site))
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.textContent = '×'
    btn.setAttribute('aria-label', `Remove ${site}`)
    btn.addEventListener('click', async () => {
      await send('popup:remove-site', { site })
      flash(`Stopped tracking ${site}`)
      refresh()
    })
    li.append(btn)
    list.append(li)
  }
}

function render() {
  const { settings, savedCount, pendingCount } = state
  $('consent').hidden = settings.consentGiven
  $('main').hidden = !settings.consentGiven
  if (!settings.consentGiven) return

  renderSite()
  renderTimer()
  const tracking = settings.trackingEnabled
  const toggle = $('toggle-tracking')
  toggle.textContent = tracking ? 'Disable Tracking' : 'Enable Tracking'
  toggle.className = `btn ${tracking ? 'secondary' : 'primary'}`
  $('stats').textContent = `${savedCount} saved · ${pendingCount} pending sync`

  const share = $('share-text')
  share.checked = settings.shareText
  $('upload-shots').checked = settings.uploadScreenshots
  $('shot-interval').value = String(settings.screenshotIntervalSec)
  $('add-canvas').hidden = settings.allowedSites.includes(CANVAS_SITE)
  renderShots()
  if (document.activeElement !== $('backend-url')) $('backend-url').value = settings.backendUrl
  if (document.activeElement !== $('dashboard-url')) $('dashboard-url').value = settings.dashboardUrl
}

async function refresh({ full = true } = {}) {
  state = await send('popup:state', { tabId: tab?.id, url: tab?.url || '' })
  render()
  if (full && state.settings.consentGiven) renderSiteList()
}

async function checkConnection() {
  const online = await send('popup:check-backend')
  $('conn-dot').className = `dot ${online ? 'online' : 'offline'}`
  $('conn-text').textContent = online ? 'Backend connected' : 'Offline · saving locally'
}

// ---- actions ----------------------------------------------------------------

$('consent-btn').addEventListener('click', async () => {
  await send('popup:consent')
  flash('Tracking enabled. Approve a study site to begin.', 'ok')
  refresh()
})

$('toggle-tracking').addEventListener('click', async () => {
  const enabled = !state.settings.trackingEnabled
  await send('popup:set-tracking', { enabled })
  flash(enabled ? 'Tracking enabled' : 'Tracking paused — nothing will be recorded', enabled ? 'ok' : '')
  refresh()
})

$('site-action').addEventListener('click', async () => {
  const { status } = state
  if (status.state === 'approved') {
    await send('popup:remove-site', { site: status.site })
    flash(`Stopped tracking ${status.site}`)
    return refresh()
  }
  // permissions.request must run directly from the click — no awaits before it.
  const site = status.state === 'needs-permission' ? status.site : status.host
  let granted = false
  try {
    granted = await chrome.permissions.request({ origins: sitePatterns(site) })
  } catch (err) {
    return flash(`Chrome refused the request: ${err.message}`, 'err')
  }
  if (!granted) return flash('Permission not granted — this site won’t be tracked.', 'err')
  await send('popup:approve-site', { site, tabId: tab.id, unblock: status.state === 'blocked' ? status.site : null })
  flash(`Now tracking ${site}. Start reading!`, 'ok')
  refresh()
})

$('shots-toggle').addEventListener('click', async () => {
  if (state.settings.screenshotsEnabled) {
    await send('popup:update-settings', { patch: { screenshotsEnabled: false } })
    flash('Snapshots off')
    return refresh({ full: false })
  }
  // Chrome only allows captureVisibleTab with <all_urls>; request it straight from the click.
  let granted = false
  try {
    granted = await chrome.permissions.request(ALL_URLS)
  } catch (err) {
    return flash(`Chrome refused the request: ${err.message}`, 'err')
  }
  if (!granted) return flash('Snapshots need Chrome’s permission to capture the visible tab.', 'err')
  await send('popup:update-settings', { patch: { screenshotsEnabled: true } })
  flash(`Snapshots on — only on approved sites, every ${state.settings.screenshotIntervalSec}s while you read`, 'ok')
  refresh({ full: false })
})

$('shots-delete').addEventListener('click', async () => {
  await send('popup:delete-shots')
  flash('Snapshots deleted', 'ok')
  refresh({ full: false })
})

$('upload-shots').addEventListener('change', async (e) => {
  await send('popup:update-settings', { patch: { uploadScreenshots: e.target.checked } })
  flash(e.target.checked ? 'Snapshots will upload to the backend' : 'Snapshots stay on this device')
})

$('shot-interval').addEventListener('change', async (e) => {
  await send('popup:update-settings', { patch: { screenshotIntervalSec: Number(e.target.value) } })
  flash(`Snapshot every ${e.target.value}s`, 'ok')
})

$('add-canvas').addEventListener('click', async () => {
  let granted = false
  try {
    granted = await chrome.permissions.request({ origins: sitePatterns(CANVAS_SITE) })
  } catch (err) {
    return flash(`Chrome refused the request: ${err.message}`, 'err')
  }
  if (!granted) return flash('Permission not granted — Canvas won’t be tracked.', 'err')
  await send('popup:approve-site', { site: CANVAS_SITE, tabId: tab?.id })
  flash('Canvas approved. Reload any open Canvas tabs.', 'ok')
  refresh()
})

$('save-page').addEventListener('click', async () => {
  const btn = $('save-page')
  btn.disabled = true
  try {
    const [{ result } = {}] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractPageForSynapse,
    })
    if (!result) throw new Error('No response from page')
    if (result.sensitive) return flash('This page has a password field — Synapse won’t save it.', 'err')
    const now = new Date().toISOString()
    const res = await send('popup:save-page', {
      record: {
        id: `ext-manual-${Date.now().toString(36)}`,
        title: result.title || tab.title,
        url: tab.url,
        domain: new URL(tab.url).hostname.replace(/^www\./, ''),
        favicon: tab.favIconUrl || null,
        excerpt: result.text,
        startedAt: now,
        timestamp: now,
        durationSec: state.live?.activeSec || 0,
        isPdf: result.isPdf,
      },
    })
    flash(
      res?.online ? 'Page saved and synced ✓' : 'Page saved locally — will sync when the backend is online',
      'ok',
    )
  } catch (err) {
    flash(`Couldn’t read this page: ${err.message}`, 'err')
  } finally {
    btn.disabled = false
    refresh({ full: false })
  }
})

$('open-dashboard').addEventListener('click', () => {
  chrome.tabs.create({ url: state?.settings.dashboardUrl || 'http://localhost:5173' })
})

$('sync-now').addEventListener('click', async () => {
  const res = await send('popup:flush')
  const extra = res.shotsSent ? ` + ${res.shotsSent} snapshot${res.shotsSent === 1 ? '' : 's'}` : ''
  flash(res.online ? `Synced ${res.synced} record${res.synced === 1 ? '' : 's'}${extra}` : 'Backend offline — kept locally', res.online ? 'ok' : 'err')
  checkConnection()
  refresh({ full: false })
})

$('share-text').addEventListener('change', async (e) => {
  await send('popup:update-settings', { patch: { shareText: e.target.checked } })
  flash(e.target.checked ? 'Page text will be uploaded with new syncs' : 'Only title, URL and time will be uploaded')
})

for (const [id, key] of [
  ['backend-url', 'backendUrl'],
  ['dashboard-url', 'dashboardUrl'],
]) {
  $(id).addEventListener('change', async (e) => {
    const value = e.target.value.trim().replace(/\/+$/, '')
    if (!/^https?:\/\/\S+$/.test(value)) return flash('Enter a full http(s):// URL', 'err')
    await send('popup:update-settings', { patch: { [key]: value } })
    flash('Saved', 'ok')
    if (key === 'backendUrl') checkConnection()
  })
}

$('delete-all').addEventListener('click', async (e) => {
  if (Date.now() > confirmDeleteUntil) {
    confirmDeleteUntil = Date.now() + 4000
    e.target.textContent = 'Click again to permanently delete'
    setTimeout(() => (e.target.textContent = 'Delete all stored data'), 4000)
    return
  }
  confirmDeleteUntil = 0
  await send('popup:delete-all')
  e.target.textContent = 'Delete all stored data'
  flash('All stored reading data deleted', 'ok')
  refresh({ full: false })
})

// ---- boot -------------------------------------------------------------------

;(async () => {
  ;[tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  await refresh()
  checkConnection()
  setInterval(() => refresh({ full: false }), 1000)
})()
