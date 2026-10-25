const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')
const { webcrypto } = require('node:crypto')
const policy = require('../study-policy.js')
const tileDiff = require('../tile-diff.js')

function worker(options = {}) {
  const saved = []
  const target = { tabId: 4, windowId: 2, url: 'https://school.edu/problems/1' }
  const current = { id: 4, windowId: 2, url: target.url, active: true }
  let captured = 0
  let uploads = []
  const initial = { ...target, sessionId: 'study-test', running: true, timed: true,
    generation: 'generation', intervalSec: 10, lastAttemptAt: 0, tileSignature: null }
  const context = vm.createContext({
    StudyPolicy: policy, TileDiff: tileDiff, crypto: webcrypto, AbortController, Date, URL,
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
    shrink: async () => {
      if (options.onShrink) await options.onShrink(current)
      const signature = typeof options.signature === 'function' ? options.signature() : options.signature
      return { base64: 'FRAME', width: 1280, height: 720, sig: signature || new Array(4096).fill(0) }
    },
    changedTileAtlas: async (_dataUrl, tiles) => ({ base64: 'PATCH', tiles, frameWidth: 1280, frameHeight: 720 }),
    fetchWithTimeout: async (url, args) => {
      uploads.push({ url, args: { ...args } })
      if (options.upload) return options.upload(url, args)
      return { ok: !options.backendFailure, status: options.backendFailure ? 502 : 200 }
    },
  })
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../study-capture.js'), 'utf8') + '\nthis.api = { studyBegin, studyStop, studyCapture, studyHeartbeat, studyPopupHandler, studyResumeHeartbeat, getLogs: studyGetLogs, update: studyUpdate, viewChanged: () => { studyViewEpoch++ }, state: async () => { await studyLoaded; return {...studyState} } }', context)
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

test('manual and timed capture can start from the popup while capture still requires focus', async () => {
  const manual = worker({ focused: false })
  await manual.api.studyBegin({ ...manual.target, sessionId: 'study-test' }, false)
  assert.equal(manual.captured(), 1)
  assert.equal(manual.uploads().length, 1)

  const timed = worker({ focused: false })
  await timed.api.studyBegin({ ...timed.target, sessionId: 'study-test', intervalSec: 10 }, true)
  assert.equal(timed.captured(), 0)
  await timed.api.studyHeartbeat({ url: timed.target.url }, { tab: timed.current })
  assert.equal(timed.captured(), 0)
  assert.equal(timed.uploads().length, 0)
})

test('capture diagnostics record progress and skip reasons without page URLs or image data', async () => {
  const w = worker({ focused: false })
  await w.api.studyBegin({ ...w.target, sessionId: 'study-test', intervalSec: 10 }, true)
  await w.api.studyHeartbeat({ url: w.target.url }, { tab: w.current })
  const logs = await w.api.getLogs()
  assert.ok(logs.some((entry) => entry.event === 'capture_started' && entry.mode === 'change_aware'))
  assert.ok(logs.some((entry) => entry.event === 'heartbeat_script_injected'))
  assert.ok(logs.some((entry) => entry.event === 'eligibility_blocked' && entry.reason === 'target_not_visible'))
  const exported = JSON.stringify(logs)
  assert.equal(exported.includes(w.target.url), false)
  assert.equal(exported.includes('FRAME'), false)
})

test('manual captures reuse the baseline, upload changed tiles, and skip unchanged frames', async () => {
  let signature = new Array(4096).fill(0)
  const w = worker({ signature: () => signature })
  await w.api.studyBegin({ ...w.target, sessionId: 'study-test' }, false)
  assert.equal(JSON.parse(w.uploads()[0].args.body).image.delta, undefined)

  for (const offset of [16 * 64 + 16 + 2, 16 * 64 + 16 + 3, 16 * 64 + 16 + 4,
    16 * 64 + 16 + 5, 16 * 64 + 16 + 6]) {
    signature[offset] = 255
  }
  await w.api.studyBegin({ ...w.target, sessionId: 'study-test' }, false)
  const changed = JSON.parse(w.uploads()[1].args.body).image
  assert.deepEqual(changed.delta.tiles, [5])
  assert.equal(changed.base64, 'PATCH')

  await w.api.studyBegin({ ...w.target, sessionId: 'study-test' }, false)
  assert.equal(w.uploads().length, 2)
  assert.equal((await w.api.state()).running, false)
  assert.match((await w.api.state()).status, /No meaningful changes/)
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

test('continuous study capture sends one full frame then only changed tiles', async () => {
  let signature = new Array(4096).fill(0)
  const w = worker({ signature: () => signature })
  const sender = { tab: { ...w.current } }
  await w.api.studyHeartbeat({ url: w.target.url }, sender)
  assert.equal(w.uploads().length, 1)
  assert.equal(JSON.parse(w.uploads()[0].args.body).image.delta, undefined)

  await w.api.studyHeartbeat({ url: w.target.url }, sender)
  assert.equal(w.uploads().length, 1)

  for (const offset of [16 * 64 + 16 + 2, 16 * 64 + 16 + 3, 16 * 64 + 16 + 4,
    16 * 64 + 16 + 5, 16 * 64 + 16 + 6]) {
    signature[offset] = 255
  }
  await w.api.update({ lastAttemptAt: Date.now() - 11_000 }, 'generation')
  await w.api.studyHeartbeat({ url: w.target.url }, sender)
  const payload = JSON.parse(w.uploads()[1].args.body)
  assert.deepEqual(payload.image.delta.tiles, [5])
  assert.equal(payload.image.base64, 'PATCH')
  assert.equal((await w.api.state()).status, 'Watching for changes — only changed tiles are sent to AI.')
})

test('a changed-tile request retries with a full frame when the server has lost its baseline', async () => {
  let signature = new Array(4096).fill(0)
  const w = worker({
    signature: () => signature,
    upload: (_url, args) => JSON.parse(args.body).image.delta
      ? { ok: false, status: 409 }
      : { ok: true, status: 200 },
  })
  const sender = { tab: { ...w.current } }
  await w.api.studyHeartbeat({ url: w.target.url }, sender)
  for (const offset of [16 * 64 + 18, 16 * 64 + 19, 16 * 64 + 20, 16 * 64 + 21, 16 * 64 + 22]) signature[offset] = 255
  await w.api.update({ lastAttemptAt: Date.now() - 11_000 }, 'generation')
  await w.api.studyHeartbeat({ url: w.target.url }, sender)
  assert.equal(w.uploads().length, 3)
  assert.ok(JSON.parse(w.uploads()[1].args.body).image.delta)
  assert.equal(JSON.parse(w.uploads()[2].args.body).image.delta, undefined)
  assert.equal((await w.api.state()).tileSignature[16 * 64 + 18], 255)
})


test('heartbeat stops itself after Stop and target reload can restore a running timer', async () => {
  const w = worker()
  assert.equal(await w.api.studyResumeHeartbeat(4, { status: 'complete' }, w.current), true)
  assert.equal(await w.api.studyResumeHeartbeat(4, { status: 'complete' }, { ...w.current, url: 'https://other.edu/' }), false)
  await w.api.studyStop()
  assert.equal(await w.api.studyResumeHeartbeat(4, { status: 'complete' }, w.current), false)
  assert.equal((await w.api.studyHeartbeat({ url: w.target.url }, { tab: w.current })).stop, true)
})
