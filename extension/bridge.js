// Relays messages between the StudBud dashboard page and the extension.
// Matches localhost, but only activates on pages carrying <meta name="synapse-dashboard">.

;(() => {
  if (!document.querySelector('meta[name="synapse-dashboard"]')) return

  const FROM_PAGE = 'synapse-dashboard'
  const FROM_EXTENSION = 'synapse-extension'
  const toPage = (type, payload) => window.postMessage({ source: FROM_EXTENSION, type, payload }, location.origin)

  async function pushState(type = 'status') {
    try {
      const res = await chrome.runtime.sendMessage({ type: 'bridge:get' })
      if (!res) return
      toPage(type, res.info)
      toPage('readings', { items: res.readings })
    } catch {
      /* extension reloaded */
    }
  }

  window.addEventListener('message', (event) => {
    if (event.source !== window || event.origin !== location.origin) return
    const msg = event.data
    if (!msg || msg.source !== FROM_PAGE) return
    switch (msg.type) {
      case 'hello':
        pushState('hello')
        break
      case 'delete-reading':
        chrome.runtime.sendMessage({ type: 'bridge:delete', id: msg.payload?.id })
        break
      case 'clear-readings':
        chrome.runtime.sendMessage({ type: 'bridge:clear' })
        break
      case 'update-settings':
        chrome.runtime.sendMessage({ type: 'bridge:settings', settings: msg.payload || {} })
        break
    }
  })

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && (changes.records || changes.settings)) pushState('status')
  })

  pushState('hello')
})()
