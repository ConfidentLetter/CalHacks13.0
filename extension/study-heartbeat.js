// A page-owned timer wakes the MV3 worker; no images or page text cross this channel.
;(() => {
  if (window.__synapseStudyHeartbeat) return
  window.__synapseStudyHeartbeat = true
  const timer = setInterval(() => {
    if (document.visibilityState !== 'visible' || !document.hasFocus()) return
    try {
      chrome.runtime.sendMessage({ type: 'study:heartbeat', url: location.href }).then((response) => {
        if (response?.stop) {
          clearInterval(timer)
          window.__synapseStudyHeartbeat = false
        }
      }).catch(() => {})
    } catch { clearInterval(timer) }
  }, 1000)
})()
