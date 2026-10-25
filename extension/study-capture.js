// Explicit study uploads are independent of passive snapshot storage and queues.
const STUDY_KEY = 'studyCapture'
let studyState = null
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
  studyState = stored[STUDY_KEY] || { sessionId: `study-${crypto.randomUUID()}`, running: false, status: 'Ready', intervalSec: 20 }
  return studyState
})

async function studyUpdate(patch, generation) {
  await studyLoaded
  if (generation && studyState.generation !== generation) return
  studyState = { ...studyState, ...patch }
  await chrome.storage.session.set({ [STUDY_KEY]: studyState })
}

async function studyTargetVisible(target) {
  const [tabs, window] = await Promise.all([
    chrome.tabs.query({ active: true, windowId: target.windowId }),
    chrome.windows.get(target.windowId).catch(() => null),
  ])
  return StudyPolicy.matchesTarget(target, tabs[0], window?.focused)
}

async function studyEligibility(target) {
  const settings = await getSettings()
  if (!settings.consentGiven) throw new Error('Enable StudBud and allow this website first.')
  if (!StudyPolicy.safeStudyUrl(target.url, settings.dashboardUrl)) throw new Error('Sensitive pages and the dashboard cannot be captured.')
  const status = await siteStatus(target.url)
  if (status.state !== 'approved') throw new Error('Allow current website before study capture. Blocked websites cannot be captured.')
  if (!(await studyTargetVisible(target))) throw new Error('Paused: return to the original study tab and URL in its focused window.')
  // Inspect every accessible frame: password fields must block deliberate captures, too.
  const frames = await chrome.scripting.executeScript({
    target: { tabId: target.tabId, allFrames: true },
    func: () => ({ sensitive: Boolean(document.querySelector('input[type="password"]')), url: location.href }),
  }).catch(() => null)
  if (!frames?.length || frames.some(({ result }) => !result || result.sensitive)) {
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
  if (timed && !StudyPolicy.validInterval(msg.intervalSec)) throw new Error('Choose 10, 20, 30, or 60 seconds.')
  if (studyBusy) throw new Error('A study capture is still finishing. Try again shortly.')
  const current = await chrome.tabs.get(msg.tabId).catch(() => null)
  const target = { tabId: msg.tabId, windowId: msg.windowId, url: msg.url }
  if (!StudyPolicy.matchesTarget(target, current, true)) throw new Error('The study tab changed. Reopen the popup on the study page.')
  await studyEligibility(target)
  if (timed && !(await chrome.permissions.contains(ALL_URLS))) throw new Error('Timed captures require Chrome’s visible-tab capture permission.')
  if (epoch !== studyEpoch) return { ...studyState }
  const generation = crypto.randomUUID()
  await studyUpdate({ ...target, sessionId: msg.sessionId, generation, running: true, timed,
    intervalSec: timed ? msg.intervalSec : 20, lastAttemptAt: 0, busyUntil: 0, error: false, status: timed ? 'Timed capture started — close this popup to begin' : 'Capturing…' })
  if (timed) {
    try {
      await chrome.scripting.executeScript({ target: { tabId: target.tabId }, files: ['study-heartbeat.js'] })
    } catch {
      await studyStop('Could not start the study tab heartbeat. Reopen the popup and try again.')
      throw new Error('Could not start timed capture on this page.')
    }
    return { ...studyState }
  }
  return studyCapture(generation)
}

async function studyCapture(generation) {
  await studyLoaded
  if (studyBusy || !StudyPolicy.isCurrent(studyState, generation)) return { ...studyState }
  studyBusy = true
  const target = { ...studyState }
  studyController = new AbortController()
  const controller = studyController
  let stage = 'checking'
  try {
    await studyUpdate({ lastAttemptAt: Date.now(), busyUntil: Date.now() + 65_000, error: false, status: 'Checking study tab…' }, generation)
    const settings = await studyEligibility(target)
    if (!StudyPolicy.isCurrent(studyState, generation)) return { ...studyState }
    // Recheck after scripting and immediately around captureVisibleTab. Discard any raced frame.
    if (!(await studyTargetVisible(target))) throw new Error('Paused: return to the original study tab and URL.')
    const viewEpoch = studyViewEpoch
    stage = 'capturing'
    const dataUrl = await chrome.tabs.captureVisibleTab(target.windowId, { format: 'jpeg', quality: 80 })
    if (!StudyPolicy.isCurrent(studyState, generation)) return { ...studyState }
    if (!(await studyTargetVisible(target)) || viewEpoch !== studyViewEpoch) throw new Error('Study tab changed during capture; image discarded.')
    stage = 'processing'
    const image = await shrink(dataUrl)
    await studyEligibility(target)
    if (viewEpoch !== studyViewEpoch) throw new Error('Study tab changed during capture; image discarded.')
    if (!StudyPolicy.isCurrent(studyState, generation) || controller.signal.aborted) return { ...studyState }
    await studyUpdate({ status: 'Sending study image to AI…' }, generation)
    if (viewEpoch !== studyViewEpoch) throw new Error('Study tab changed during capture; image discarded.')
    if (!StudyPolicy.isCurrent(studyState, generation) || controller.signal.aborted) return { ...studyState }
    const capturedAt = new Date().toISOString()
    stage = 'uploading'
    const response = await fetchWithTimeout(`${settings.backendUrl}/api/study/observe`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
      body: JSON.stringify({ sessionId: target.sessionId, image: { base64: image.base64, mimeType: 'image/jpeg', capturedAt, source: 'screen' } }),
    }, 45_000)
    if (!response.ok) throw new Error(`Study service could not process this image${response.status ? ` (HTTP ${response.status})` : ''}. Check the backend and try again.`)
    if (StudyPolicy.isCurrent(studyState, generation)) {
      await studyUpdate({ error: false, status: 'Study image sent. Open tutor for feedback.', lastCapturedAt: capturedAt }, generation)
    }
  } catch (err) {
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
    await studyUpdate({ busyUntil: 0, ...(!target.timed ? { running: false } : {}) }, generation)
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
  if (!studyState.running || !studyState.timed || sender.tab?.id !== studyState.tabId || sender.tab?.windowId !== studyState.windowId || sender.tab?.url !== studyState.url || msg.url !== studyState.url) return { stop: true }
  if (Date.now() - (studyState.lastAttemptAt || 0) < studyState.intervalSec * 1000) return
  if (!StudyPolicy.isDue(studyState, sender.tab, true, Date.now(), studyBusy)) return
  return studyCapture(studyState.generation)
}

function studyPopupHandler(handler) {
  return (msg, sender) => {
    if (sender.id !== chrome.runtime.id || sender.tab || sender.url !== chrome.runtime.getURL('popup.html')) throw new Error('Study capture requires the extension popup.')
    return handler(msg)
  }
}
