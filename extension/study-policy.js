// Shared, side-effect-free rules, loaded by the worker and Node tests.
;(function (root) {
  const validSessionId = (id) => typeof id === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(id)
  const validInterval = (seconds) => [10, 20, 30, 60].includes(seconds)
  const matchesTarget = (target, tab, focused) => Boolean(target && tab && focused && tab.active &&
    tab.id === target.tabId && tab.windowId === target.windowId && tab.url === target.url && !tab.pendingUrl)
  function safeStudyUrl(url, dashboardUrl) {
    try {
      const page = new URL(url)
      if (!['https:', 'http:'].includes(page.protocol)) return false
      if (page.origin === new URL(dashboardUrl).origin) return false
      if (/^(chrome\.google\.com|chromewebstore\.google\.com)$/.test(page.hostname)) return false
      return !/(grades?|gradebook|conversations|inbox|messages?|profile|settings|account|log-?in|sign-?in|sign-?up|auth|password|checkout|payment|billing|chat|quizzes\/\d+\/take|take_quiz|exam)/i.test(page.pathname + page.search + page.hash)
    } catch { return false }
  }
  const isCurrent = (state, generation) => Boolean(state?.running && state.generation === generation)
  const isDue = (state, tab, focused, now, busy) => Boolean(state?.running && validInterval(state.intervalSec) &&
    !busy && !(state.busyUntil > now) && matchesTarget(state, tab, focused) && now - (state.lastAttemptAt || 0) >= state.intervalSec * 1000)
  const api = { validSessionId, validInterval, matchesTarget, safeStudyUrl, isCurrent, isDue }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.StudyPolicy = api
})(globalThis)
