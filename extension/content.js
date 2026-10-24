// Synapse reading detector.
// Injected ONLY into sites the user approved (see background.js → syncContentScripts).
// Counts "active reading" seconds: the tab must be visible, the window focused, and
// the user must have scrolled / moved / pressed a key within the idle window.
// It never reads form fields, inputs, or pages that contain password fields.

;(() => {
  if (window.__synapseReader) return
  window.__synapseReader = true

  const IDLE_LIMIT_MS = 60_000 // no interaction for 60s → not "actively reading"
  const SENSITIVE_URL = /(log-?in|sign-?in|sign-?up|auth|password|checkout|payment|billing|account|inbox|messages?|chat)/i

  const sessionId = `ext-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  const startedAt = new Date().toISOString()
  let activeSec = 0
  let lastInteraction = Date.now()
  let qualified = false
  let minSec = 30
  let textSent = false

  function isSensitivePage() {
    if (SENSITIVE_URL.test(location.pathname + location.search)) return true
    return Boolean(document.querySelector('input[type="password"]'))
  }

  function extractReadableText() {
    const root =
      document.querySelector('article') ||
      document.querySelector('main') ||
      document.querySelector('[role="main"]') ||
      document.body
    if (!root) return ''
    const clone = root.cloneNode(true)
    clone
      .querySelectorAll(
        'input, textarea, select, button, form, [contenteditable], script, style, noscript, nav, footer, aside, header, iframe, svg, [aria-hidden="true"], [hidden]',
      )
      .forEach((el) => el.remove())
    return (clone.innerText || clone.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 4000)
  }

  function isActive() {
    return (
      document.visibilityState === 'visible' && document.hasFocus() && Date.now() - lastInteraction < IDLE_LIMIT_MS
    )
  }

  function report(state) {
    const payload = {
      type: 'reading:progress',
      sessionId,
      startedAt,
      url: location.href,
      title: document.title || location.hostname,
      activeSec,
      state, // 'active' | 'idle' | 'hidden'
      qualified,
      isPdf: document.contentType === 'application/pdf',
    }
    if (qualified && !textSent) {
      payload.text = payload.isPdf ? '' : extractReadableText()
      textSent = true
    }
    try {
      chrome.runtime.sendMessage(payload).catch(() => {})
    } catch {
      // Extension was reloaded; this orphaned script just stops.
      clearInterval(timer)
    }
  }

  if (isSensitivePage()) return

  chrome.storage.local.get('settings').then(({ settings }) => {
    if (settings?.minReadingSeconds) minSec = settings.minReadingSeconds
  })

  const bump = () => (lastInteraction = Date.now())
  ;['scroll', 'wheel', 'mousemove', 'keydown', 'pointerdown', 'touchstart'].forEach((ev) =>
    window.addEventListener(ev, bump, { passive: true, capture: true }),
  )

  let lastState = null
  const timer = setInterval(() => {
    const state = document.visibilityState !== 'visible' ? 'hidden' : isActive() ? 'active' : 'idle'
    if (state === 'active') {
      activeSec += 1
      if (!qualified && activeSec >= minSec) qualified = true
    }
    // Report every second while active (drives the popup timer) and on state changes.
    if (state === 'active' || state !== lastState) report(state)
    lastState = state
  }, 1000)

  document.addEventListener('visibilitychange', () => report(document.visibilityState === 'visible' ? 'idle' : 'hidden'))
  window.addEventListener('pagehide', () => report('hidden'))
})()
