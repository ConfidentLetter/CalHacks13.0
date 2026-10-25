const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
const { webcrypto } = require('node:crypto')

function background() {
  const noopEvent = { addListener() {} }
  let receiver
  const context = vm.createContext({
    crypto: webcrypto, URL, AbortController,
    chrome: {
      storage: {
        local: { get: async () => ({}), set: async () => {} },
        session: { get: async () => ({}), set: async () => {} },
      },
      runtime: { id: 'test-extension', getURL: path => `chrome-extension://test-extension/${path}`,
        onMessage: { addListener(fn) { receiver = fn } }, onInstalled: noopEvent, onStartup: noopEvent },
      permissions: { onRemoved: noopEvent },
      alarms: { onAlarm: noopEvent },
      tabs: { onRemoved: noopEvent, onActivated: noopEvent, onUpdated: noopEvent },
      windows: { onFocusChanged: noopEvent },
    },
  })
  context.importScripts = (...files) => {
    for (const file of files) vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), context)
  }
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8') + '\nthis.popupState = handlers["popup:state"]', context)
  return { context, receive: (...args) => receiver(...args) }
}

test('classic MV3 worker loads shared scripts and exposes study state alongside passive settings', async () => {
  const { context } = background()
  const result = await context.popupState({ tabId: 4, url: 'chrome://newtab' })
  assert.match(result.study.sessionId, /^study-/)
  assert.equal(result.study.running, false)
  assert.equal(result.settings.screenshotsEnabled, false)
  assert.equal(result.shots.count, 0)
})

test('synchronous capture handler errors reach the popup instead of closing its message port', async () => {
  const worker = background()
  let reply
  const keepOpen = worker.receive({ type: 'popup:study-capture' }, {}, value => { reply = value })
  assert.equal(keepOpen, true)
  await new Promise(resolve => setImmediate(resolve))
  assert.match(reply.error, /requires the extension popup/)
})
