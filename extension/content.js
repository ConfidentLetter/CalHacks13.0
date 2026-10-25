// StudBud reading detector.
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
  let minSec = 5
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

  // Detect and extract PDF from URL using PDF.js
  async function tryExtractPdfFromUrl() {
    if (document.contentType !== 'application/pdf') return null
    try {
      // Load PDF.js library
      if (typeof window.pdfjsLib === 'undefined') {
        await new Promise((resolve, reject) => {
          const script = document.createElement('script')
          script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js'
          script.onload = resolve
          script.onerror = reject
          document.head.appendChild(script)
        })
      }

      const pdf = window.pdfjsLib
      pdf.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'

      const doc = await pdf.getDocument(location.href).promise
      const texts = []

      for (let i = 1; i <= Math.min(doc.numPages, 10); i++) {
        try {
          const page = await doc.getPage(i)
          const content = await page.getTextContent()
          const pageText = content.items.map(item => (item.str || '').trim()).filter(s => s).join(' ')
          if (pageText) texts.push(`[Page ${i}] ${pageText}`)
        } catch {}
      }

      return { pages: doc.numPages, text: texts.join('\n'), error: null }
    } catch (err) {
      return null
    }
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
      if (payload.isPdf) {
        // Try to extract PDF text asynchronously
        tryExtractPdfFromUrl().then(result => {
          if (result?.text) {
            const followupPayload = { ...payload, text: result.text, pdfPages: result.pages }
            try {
              chrome.runtime.sendMessage(followupPayload).catch(() => {})
            } catch {}
          }
        })
        payload.text = ''
      } else {
        payload.text = extractReadableText()
      }
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

  // Follow the user's 1–10s threshold, including changes made while this page is open.
  const applyThreshold = (settings) => {
    const n = settings?.minReadingSeconds
    if (Number.isInteger(n) && n >= 1 && n <= 10) minSec = n
  }
  chrome.storage.local.get('settings').then(({ settings }) => applyThreshold(settings))
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.settings) applyThreshold(changes.settings.newValue)
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
