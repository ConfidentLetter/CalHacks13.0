const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')
const { webcrypto } = require('node:crypto')
const policy = require('../study-policy.js')

function worker(options = {}) {
  const saved = []
  const target = { tabId: 4, windowId: 2, url: 'https://school.edu/problems/1' }
  const current = { id: 4, windowId: 2, url: target.url, active: true }
  let captured = 0
  let uploads = []
  const initial = { ...target, sessionId: 'study-test', running: true, timed: true,
    generation: 'generation', intervalSec: 10, lastAttemptAt: 0 }
  const context = vm.createContext({
    StudyPolicy: policy, crypto: webcrypto, AbortController, Date, URL,
    chrome: {
      storage: { session: { get: async () => ({ studyCapture: initial }), set: async (data) => { saved.push(structuredClone(data)) } } },
      runtime: { id: 'extension-id', getURL: (name) => `chrome-extension://extension-id/${name}` },
      tabs: {
        get: async () => ({ ...current }), query: async () => [{ ...current }],
        captureVisibleTab: async () => { captured++; if (options.onCapture) await options.onCapture(current); return 'data:image/jpeg;base64,FRAME' },
      },
      windows: { get: async () => ({ focused: options.focused !== false }) },
      scripting: { executeScript: async (args) => args.files ? [] : [{ result: { sensitive: Boolean(options.password), url: current.url } }] },
      permissions: { contains: async () => { if (options.noBroad) throw new Error('Manual capture requested broad permissions'); return true } },
    },
    getSettings: async () => ({ consentGiven: true, dashboardUrl: 'http://localhost:5173', backendUrl: 'http://localhost:8000' }),
    siteStatus: async () => ({ state: options.siteState || 'approved' }),
    ALL_URLS: { origins: ['<all_urls>'] },
    shrink: async () => { if (options.onShrink) await options.onShrink(current); return { base64: 'FRAME' } },
    fetchWithTimeout: async (url, args) => {
      uploads.push({ url, args })
      if (options.upload) return options.upload(url, args)
      return { ok: !options.backendFailure, status: options.backendFailure ? 502 : 200 }
    },
  })
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../study-capture.js'), 'utf8') + '\nthis.api = { studyBegin, studyStop, studyCapture, studyHeartbeat, studyPopupHandler, studyResumeHeartbeat, viewChanged: () => { studyViewEpoch++ }, state: async () => { await studyLoaded; return {...studyState} } }', context)
  return { api: context.api, current, target, saved, captured: () => captured, uploads: () => uploads }
}

test('manual capture uses activeTab without requesting broad capture permission', async () => {
  const w = worker({ noBroad: true })
  await w.api.studyBegin({ ...w.target, sessionId: 'study-test' }, false)
  assert.equal(w.captured(), 1)
  assert.equal(w.uploads().length, 1)
  const payload = JSON.parse(w.uploads()[0].args.body)
  assert.equal(payload.sessionId, 'study-test')
  assert.deepEqual(Object.keys(payload.image).sort(), ['base64', 'capturedAt', 'mimeType', 'source'])
  assert.equal(payload.image.source, 'screen')
  assert.equal((await w.api.state()).running, false)
  assert.equal(JSON.stringify(w.saved).includes('FRAME'), false)
})

test('manual capture failure persists as an explicit error after the popup closes', async () => {
  const w = worker({ backendFailure: true })
  await w.api.studyBegin({ ...w.target, sessionId: 'study-test' }, false)
  const state = await w.api.state()
  assert.equal(state.error, true)
  assert.match(state.status, /HTTP 502/)
  assert.equal(state.running, false)
})

test('tab switched during capture discards the image', async () => {
  const w = worker({ onCapture: (current) => { current.active = false } })
  await w.api.studyCapture('generation')
  assert.equal(w.captured(), 1)
  assert.equal(w.uploads().length, 0)
  assert.match((await w.api.state()).status, /discarded/)
})

test('URL changed during image shrinking discards the image before upload', async () => {
  const w = worker({ onShrink: (current) => { current.url = 'http://localhost:5173/#/capture' } })
  await w.api.studyCapture('generation')
  assert.equal(w.uploads().length, 0)
})

test('password fields, unapproved sites and unfocused windows prevent captures', async () => {
  for (const options of [{ password: true }, { siteState: 'not-allowed' }, { siteState: 'blocked' }, { focused: false }]) {
    const w = worker(options)
    await w.api.studyCapture('generation')
    assert.equal(w.captured(), 0)
    assert.equal(w.uploads().length, 0)
  }
})

test('Stop during capture invalidates the frame before upload', async () => {
  let release
  let started
  const waiting = new Promise((resolve) => { release = resolve })
  const capturing = new Promise((resolve) => { started = resolve })
  const w = worker({ onCapture: async () => { started(); await waiting } })
  const pending = w.api.studyCapture('generation')
  await capturing
  await w.api.studyStop()
  release()
  await pending
  assert.equal(w.uploads().length, 0)
  assert.equal((await w.api.state()).running, false)
  assert.equal((await w.api.state()).status, 'Stopped')
})

test('Stop aborts an in-flight upload and ignores its later success', async () => {
  let release, started
  const waiting = new Promise((resolve) => { release = resolve })
  const sending = new Promise((resolve) => { started = resolve })
  const w = worker({ upload: async () => { started(); await waiting; return { ok: true } } })
  const pending = w.api.studyCapture('generation')
  await sending
  await w.api.studyStop()
  assert.equal(w.uploads()[0].args.signal.aborted, true)
  release()
  await pending
  assert.equal((await w.api.state()).status, 'Stopped')
})

test('concurrent heartbeats never duplicate an in-flight request; failures never queue frames', async () => {
  let release, started
  const waiting = new Promise((resolve) => { release = resolve })
  const sending = new Promise((resolve) => { started = resolve })
  const w = worker({ upload: async () => { started(); await waiting; return { ok: false } } })
  const pending = w.api.studyCapture('generation')
  await sending
  await w.api.studyHeartbeat({ url: w.target.url }, { tab: w.current })
  assert.equal(w.uploads().length, 1)
  release()
  await pending
  assert.match((await w.api.state()).status, /could not process/)
  assert.equal(JSON.stringify(w.saved).includes('FRAME'), false)
  await w.api.studyHeartbeat({ url: w.target.url }, { tab: w.current })
  assert.equal(w.uploads().length, 1)
})

test('popup actions reject tab senders and heartbeat rejects other tabs and URLs', async () => {
  const w = worker()
  const handler = w.api.studyPopupHandler(() => true)
  assert.throws(() => handler({}, { id: 'extension-id', tab: w.current, url: w.target.url }), /popup/)
  assert.equal(handler({}, { id: 'extension-id', url: 'chrome-extension://extension-id/popup.html' }), true)
  await w.api.studyHeartbeat({ url: w.target.url }, { tab: { ...w.current, id: 8 } })
  await w.api.studyHeartbeat({ url: `${w.target.url}#changed` }, { tab: w.current })
  assert.equal(w.captured(), 0)
})


test('activation away and back during capture discards frame even if final tab matches', async () => {
  let w
  w = worker({ onCapture: () => { w.api.viewChanged() } })
  await w.api.studyCapture('generation')
  assert.equal(w.uploads().length, 0)
  assert.match((await w.api.state()).status, /discarded/)
})


test('heartbeat stops itself after Stop and target reload can restore a running timer', async () => {
  const w = worker()
  assert.equal(await w.api.studyResumeHeartbeat(4, { status: 'complete' }, w.current), true)
  assert.equal(await w.api.studyResumeHeartbeat(4, { status: 'complete' }, { ...w.current, url: 'https://other.edu/' }), false)
  await w.api.studyStop()
  assert.equal(await w.api.studyResumeHeartbeat(4, { status: 'complete' }, w.current), false)
  assert.equal((await w.api.studyHeartbeat({ url: w.target.url }, { tab: w.current })).stop, true)
})
