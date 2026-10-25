// Page-owned timer for the PDF observer; wakes the MV3 worker only while this tab is visible and focused.
// No images or page text cross this channel.
;(() => {
  if (window.__synapsePdfHeartbeat) return
  window.__synapsePdfHeartbeat = true
  const timer = setInterval(() => {
    if (document.visibilityState !== 'visible' || !document.hasFocus()) return
    try {
      chrome.runtime.sendMessage({ type: 'pdf:heartbeat', url: location.href }).then((response) => {
        if (response?.stop) {
          clearInterval(timer)
          window.__synapsePdfHeartbeat = false
        }
      }).catch(() => {})
    } catch { clearInterval(timer) }
  }, 1000)
})()
