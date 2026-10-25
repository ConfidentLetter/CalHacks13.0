// Relays messages between the StudBud dashboard page and the extension.
// Runs on the local and deployed dashboards, gated by <meta name="synapse-dashboard">.

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

  async function mutate(msg, command, result) {
    let payload = result
    try {
      const response = await chrome.runtime.sendMessage(command)
      if (response?.error) throw new Error(response.error)
      await pushState()
    } catch (err) {
      payload = { error: err.message || 'Extension deletion failed' }
    }
    window.postMessage({ source: FROM_EXTENSION, type: 'mutation-result', requestId: msg.requestId, payload }, location.origin)
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
        mutate(msg, { type: 'bridge:delete', id: msg.payload?.id }, { deletedIds: [String(msg.payload?.id)] })
        break
      case 'clear-readings':
        mutate(msg, { type: 'bridge:clear' }, { cleared: true })
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
