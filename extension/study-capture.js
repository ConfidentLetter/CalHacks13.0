// Explicit study uploads are independent of passive snapshot storage and queues.
const STUDY_KEY = 'studyCapture'
const STUDY_LOG_KEY = 'studyCaptureLogs'
const STUDY_LOG_LIMIT = 150
let studyState = null
let studyLogs = []
let studyEpoch = 0
// Detect an away-and-back race even when final tab/URL checks happen to match.
let studyViewEpoch = 0
chrome.tabs.onActivated?.addListener(() => { studyViewEpoch++ })
chrome.tabs.onUpdated?.addListener((id, change, tab) => {
  if (change.url || change.status === 'loading') studyViewEpoch++
  studyResumeHeartbeat(id, change, tab).catch(() => {})
})
chrome.windows.onFocusChanged?.addListener(() => { studyViewEpoch++ })
let studyBusy = false
let studyController = null
const studyLoaded = chrome.storage.session.get(STUDY_KEY).then((stored) => {
  studyState = stored[STUDY_KEY] || { sessionId: `study-${crypto.randomUUID()}`, running: false, status: 'Ready', intervalSec: 5 }
  return studyState
})
const studyLogsLoaded = chrome.storage.session.get(STUDY_LOG_KEY).then((stored) => {
  studyLogs = Array.isArray(stored[STUDY_LOG_KEY]) ? stored[STUDY_LOG_KEY].slice(-STUDY_LOG_LIMIT) : []
  return studyLogs
})
let studyLogWrites = Promise.resolve()
let lastHeartbeatLogAt = 0

async function studyLog(event, details = {}) {
  await studyLogsLoaded
  const entry = { at: new Date().toISOString(), event, ...details }
  studyLogs = [...studyLogs, entry].slice(-STUDY_LOG_LIMIT)
  studyLogWrites = studyLogWrites.then(() => chrome.storage.session.set({ [STUDY_LOG_KEY]: studyLogs }))
  await studyLogWrites
}

async function studyGetLogs() {
  await studyLogsLoaded
  await studyLogWrites
  return studyLogs.slice()
}

async function studyUpdate(patch, generation) {
  await studyLoaded
  if (generation && studyState.generation !== generation) return
  studyState = { ...studyState, ...patch }
  await chrome.storage.session.set({ [STUDY_KEY]: studyState })
}

async function studyTargetVisible(target, allowUnfocused = false) {
  const [tabs, window] = await Promise.all([
    chrome.tabs.query({ active: true, windowId: target.windowId }),
    chrome.windows.get(target.windowId).catch(() => null),
  ])
  return StudyPolicy.matchesTarget(target, tabs[0], allowUnfocused || window?.focused)
}

async function studyEligibility(target, allowUnfocused = false) {
  const settings = await getSettings()
  if (!settings.consentGiven) {
    await studyLog('eligibility_blocked', { reason: 'consent_missing' })
    throw new Error('Enable StudBud and allow this website first.')
  }
  if (!StudyPolicy.safeStudyUrl(target.url, settings.dashboardUrl)) {
    await studyLog('eligibility_blocked', { reason: 'unsafe_url' })
    throw new Error('Sensitive pages and the dashboard cannot be captured.')
  }
  const status = await siteStatus(target.url)
  if (status.state !== 'approved') {
    await studyLog('eligibility_blocked', { reason: 'site_not_approved', siteState: status.state })
    throw new Error('Allow current website before study capture. Blocked websites cannot be captured.')
  }
  if (!(await studyTargetVisible(target, allowUnfocused))) {
    await studyLog('eligibility_blocked', { reason: 'target_not_visible', tabId: target.tabId, windowId: target.windowId })
    throw new Error('Paused: return to the original study tab and URL in its focused window.')
  }
  // Inspect every accessible frame: password fields must block deliberate captures, too.
  const frames = await chrome.scripting.executeScript({
    target: { tabId: target.tabId, allFrames: true },
    func: () => ({ sensitive: Boolean(document.querySelector('input[type="password"]')), url: location.href }),
  }).catch(() => null)
  if (!frames?.length || frames.some(({ result }) => !result || result.sensitive)) {
    await studyLog('eligibility_blocked', { reason: 'page_safety_check_failed' })
    throw new Error('This page cannot be safely checked or contains a password field.')
  }
  return settings
}

async function studyStop(status = 'Stopped') {
  ++studyEpoch
  studyController?.abort()
  await studyUpdate({ running: false, generation: crypto.randomUUID(), busyUntil: 0, error: false, status })
  return { ...studyState }
}

async function studyBegin(msg, timed) {
  const epoch = ++studyEpoch
  studyController?.abort()
  await studyLoaded
  if (!StudyPolicy.validSessionId(msg.sessionId)) throw new Error('Invalid study session ID.')
  if (timed && !StudyPolicy.validInterval(msg.intervalSec)) throw new Error('Choose 5, 10, 20, 30, or 60 seconds.')
  if (studyBusy) throw new Error('A study capture is still finishing. Try again shortly.')
  const current = await chrome.tabs.get(msg.tabId).catch(() => null)
  const target = { tabId: msg.tabId, windowId: msg.windowId, url: msg.url }
  if (!StudyPolicy.matchesTarget(target, current, true)) throw new Error('The study tab changed. Reopen the popup on the study page.')
  // Starting from the extension popup can make the browser report the window as unfocused.
  // Timed heartbeats still require focus before they capture any image.
  await studyEligibility(target, true)
  if (timed && !(await chrome.permissions.contains(ALL_URLS))) {
    await studyLog('start_blocked', { reason: 'capture_permission_missing' })
    throw new Error('Timed captures require Chrome’s visible-tab capture permission.')
  }
  if (epoch !== studyEpoch) return { ...studyState }
  const tileSignature = studyState.sessionId === msg.sessionId &&
    studyState.tabId === target.tabId && studyState.windowId === target.windowId &&
    studyState.url === target.url ? studyState.tileSignature : null
  const generation = crypto.randomUUID()
  await studyUpdate({ ...target, sessionId: msg.sessionId, generation, running: true, timed,
    intervalSec: timed ? msg.intervalSec : 5, lastAttemptAt: 0, tileSignature, busyUntil: 0, error: false,
    status: timed ? 'Change-aware capture started — close this popup to begin' : 'Capturing…' })
  await studyLog('capture_started', { mode: timed ? 'change_aware' : 'manual', tabId: target.tabId, windowId: target.windowId,
    intervalSec: timed ? msg.intervalSec : null })
  if (timed) {
    try {
      await chrome.scripting.executeScript({ target: { tabId: target.tabId }, files: ['study-heartbeat.js'] })
      await studyLog('heartbeat_script_injected', { tabId: target.tabId })
    } catch {
      await studyLog('heartbeat_script_failed', { tabId: target.tabId })
      await studyStop('Could not start the study tab heartbeat. Reopen the popup and try again.')
      throw new Error('Could not start timed capture on this page.')
    }
    return { ...studyState }
  }
  return studyCapture(generation)
}

async function studyCapture(generation) {
  if (studyBusy) return { ...studyState }
  studyBusy = true
  try {
    await studyLoaded
  } catch (err) {
    studyBusy = false
    throw err
  }
  if (!StudyPolicy.isCurrent(studyState, generation)) {
    studyBusy = false
    return { ...studyState }
  }
  const target = { ...studyState }
  studyController = new AbortController()
  const controller = studyController
  const allowUnfocused = !target.timed
  let stage = 'checking'
  let requestStarted = false
  try {
    const settings = await studyEligibility(target, allowUnfocused)
    if (!StudyPolicy.isCurrent(studyState, generation)) return { ...studyState }
    // Check before and after capture because Chrome can photograph a different active tab.
    if (!(await studyTargetVisible(target, allowUnfocused))) throw new Error('Paused: return to the original study tab and URL.')
    const viewEpoch = studyViewEpoch
    stage = 'capturing'
    const dataUrl = await chrome.tabs.captureVisibleTab(target.windowId, { format: 'jpeg', quality: 80 })
    if (!StudyPolicy.isCurrent(studyState, generation)) return { ...studyState }
    if (!(await studyTargetVisible(target, allowUnfocused)) || viewEpoch !== studyViewEpoch) throw new Error('Study tab changed during capture; image discarded.')
    stage = 'processing'
    const image = await shrink(dataUrl)
    await studyLog('screenshot_processed', { width: image.width, height: image.height, mode: target.timed ? 'change_aware' : 'manual' })
    const changedTiles = target.tileSignature
      ? TileDiff.changedTiles(target.tileSignature, image.sig)
      : []
    await studyLog('tile_comparison', { baseline: Boolean(target.tileSignature), changedTileCount: changedTiles.length, changedTiles })
    if (target.tileSignature && !changedTiles.length) {
      await studyLog('capture_skipped', { reason: 'no_meaningful_tile_changes' })
      if (!target.timed) {
        await studyUpdate({ running: false, error: false, status: 'No meaningful changes — no image sent.' }, generation)
      }
      return { ...studyState }
    }
    if (target.timed && target.lastAttemptAt && Date.now() - target.lastAttemptAt < target.intervalSec * 1000) {
      await studyLog('capture_skipped', { reason: 'cooldown', remainingMs: Math.max(0, target.intervalSec * 1000 - (Date.now() - target.lastAttemptAt)) })
      return { ...studyState }
    }
    await studyEligibility(target, allowUnfocused)
    if (viewEpoch !== studyViewEpoch) throw new Error('Study tab changed during capture; image discarded.')
    if (!StudyPolicy.isCurrent(studyState, generation) || controller.signal.aborted) return { ...studyState }
    const capturedAt = new Date().toISOString()
    const sendChangedTiles = Boolean(target.tileSignature) &&
      changedTiles.length <= TileDiff.GRID_SIZE * TileDiff.GRID_SIZE / 2
    let payloadImage = { base64: image.base64, mimeType: 'image/jpeg', capturedAt, source: 'screen' }
    if (sendChangedTiles) {
      const atlas = await changedTileAtlas(dataUrl, changedTiles)
      payloadImage = {
        ...payloadImage,
        base64: atlas.base64,
        delta: { grid: TileDiff.GRID_SIZE, frameWidth: atlas.frameWidth, frameHeight: atlas.frameHeight, tiles: atlas.tiles },
      }
    }
    await studyLog('upload_started', { coverage: payloadImage.delta ? 'changed_tiles' : 'full_frame',
      changedTileCount: changedTiles.length })
    requestStarted = true
    await studyUpdate({ lastAttemptAt: Date.now(), busyUntil: Date.now() + 65_000, error: false,
      status: 'Sending changed study tiles to AI…' }, generation)
    if (viewEpoch !== studyViewEpoch) throw new Error('Study tab changed during capture; image discarded.')
    if (!StudyPolicy.isCurrent(studyState, generation) || controller.signal.aborted) return { ...studyState }
    stage = 'uploading'
    const endpoint = `${settings.backendUrl}/api/study/observe`
    const request = {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
      body: JSON.stringify({ sessionId: target.sessionId, image: payloadImage }),
    }
    let response = await fetchWithTimeout(endpoint, request, 45_000)
    await studyLog('upload_response', { status: response.status, ok: response.ok, coverage: payloadImage.delta ? 'changed_tiles' : 'full_frame' })
    if (!response.ok && response.status === 409 && payloadImage.delta) {
      payloadImage = { base64: image.base64, mimeType: 'image/jpeg', capturedAt, source: 'screen' }
      request.body = JSON.stringify({ sessionId: target.sessionId, image: payloadImage })
      response = await fetchWithTimeout(endpoint, request, 45_000)
      await studyLog('full_frame_retry_response', { status: response.status, ok: response.ok })
    }
    if (!response.ok) throw new Error(`Study service could not process this image${response.status ? ` (HTTP ${response.status})` : ''}. Check the backend and try again.`)
    if (StudyPolicy.isCurrent(studyState, generation)) {
      await studyUpdate({ error: false, tileSignature: Array.from(image.sig),
        status: target.timed ? 'Watching for changes — only changed tiles are sent to AI.'
          : sendChangedTiles ? `Sent ${changedTiles.length} changed 4×4 tiles to AI.` : 'Study image sent. Open tutor for feedback.',
        lastCapturedAt: capturedAt }, generation)
    }
  } catch (err) {
    await studyLog('capture_failed', { stage, errorName: err?.name || 'Error',
      reason: err?.message?.startsWith('Paused:') ? 'target_not_visible'
        : err?.message?.startsWith('Study tab changed') ? 'target_changed'
          : stage === 'capturing' ? 'screenshot_failed'
            : stage === 'processing' ? 'image_processing_failed'
              : stage === 'uploading' ? 'backend_request_failed' : 'eligibility_or_start_failed' })
    if (StudyPolicy.isCurrent(studyState, generation)) {
      const fallback = stage === 'uploading'
        ? 'Could not reach the study tutor. Check the backend connection and try again. No image was queued.'
        : stage === 'capturing'
          ? 'Chrome could not take a screenshot. Reopen the extension on this tab and try again.'
          : stage === 'processing'
            ? 'The screenshot could not be prepared. Try Capture now again.'
            : 'The study tab could not be checked. Reload the page and reopen the extension.'
      const safe = err.message?.startsWith('Paused:') || /^(Sensitive pages|Allow current|This page|Study tab changed|Study service)/.test(err.message || '')
        ? err.message : fallback
      await studyUpdate({ error: true, status: safe }, generation)
    }
  } finally {
    studyBusy = false
    if (studyController === controller) studyController = null
    if (requestStarted) await studyUpdate({ busyUntil: 0, ...(!target.timed ? { running: false } : {}) }, generation)
  }
  return { ...studyState }
}

async function studyResumeHeartbeat(tabId, change, tab) {
  if (change.status !== 'complete') return false
  await studyLoaded
  if (!studyState.running || !studyState.timed || tabId !== studyState.tabId || tab?.url !== studyState.url) return false
  await chrome.scripting.executeScript({ target: { tabId }, files: ['study-heartbeat.js'] })
  return true
}

async function studyHeartbeat(msg, sender) {
  await studyLoaded
  const matchesStudy = studyState.running && studyState.timed && sender.tab?.id === studyState.tabId &&
    sender.tab?.windowId === studyState.windowId && sender.tab?.url === studyState.url && msg.url === studyState.url
  if (!matchesStudy) {
    await studyLog('heartbeat_rejected', { running: Boolean(studyState.running), timed: Boolean(studyState.timed),
      senderTabMatches: sender.tab?.id === studyState.tabId, senderWindowMatches: sender.tab?.windowId === studyState.windowId,
      senderUrlMatches: sender.tab?.url === studyState.url, messageUrlMatches: msg.url === studyState.url })
    return { stop: true }
  }
  if (Date.now() - lastHeartbeatLogAt >= 10_000) {
    lastHeartbeatLogAt = Date.now()
    await studyLog('heartbeat_received', { tabId: sender.tab.id })
  }
  if (!StudyPolicy.isCurrent(studyState, studyState.generation) ||
      !StudyPolicy.matchesTarget(studyState, sender.tab, true) || studyBusy ||
      studyState.busyUntil > Date.now()) {
    if (!studyBusy && studyState.busyUntil <= Date.now() &&
        !StudyPolicy.matchesTarget(studyState, sender.tab, true)) {
      await studyLog('heartbeat_waiting', { reason: 'study_tab_not_active' })
    }
    return
  }
  return studyCapture(studyState.generation)
}

function studyPopupHandler(handler) {
  return (msg, sender) => {
    if (sender.id !== chrome.runtime.id || sender.tab || sender.url !== chrome.runtime.getURL('popup.html')) throw new Error('Study capture requires the extension popup.')
    return handler(msg)
  }
}
