const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const { webcrypto } = require('node:crypto')

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const tick = () => new Promise(resolve => setImmediate(resolve))
function fixture() {
  return { settings: { consentGiven: true, trackingEnabled: true, allowedSites: [], minReadingSeconds: 5, screenshotIntervalSec: 20, dashboardUrl: 'http://localhost:5173', backendUrl: 'http://localhost:8000' }, status: { state: 'approved', host: 'example.com' }, shots: { count: 0 }, study: { sessionId: 'study-test', status: 'Ready', running: false, intervalSec: 20 }, savedCount: 0, pendingCount: 0 }
}
function popup(overrides = {}) {
  const elements = new Map()
  const element = () => ({ textContent: '', value: '20', style: {}, listeners: {}, setAttribute() {}, append() {}, addEventListener(type, fn) { this.listeners[type] = fn } })
  const document = { activeElement: null, getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id) }, createElement: element, createTextNode: text => text }
  const calls = []
  const intervals = []
  const chrome = { runtime: { sendMessage: async msg => { calls.push(msg); return overrides.send ? overrides.send(msg) : msg.type === 'popup:state' ? fixture() : msg.type === 'popup:study-logs' ? { logs: [] } : {} } }, tabs: { query: async () => [{ id: 1, windowId: 2, url: 'https://example.com', title: 'Study' }], create: overrides.create || (async () => {}) }, permissions: { contains: async () => true, request: overrides.permission || (async () => true) }, storage: { local: { get: async () => ({}) } } }
  const clipboard = { text: '', async writeText(text) { this.text = text } }
  const context = vm.createContext({ document, chrome, URL, navigator: { clipboard }, crypto: webcrypto, setTimeout: () => 1, clearTimeout() {}, setInterval: fn => intervals.push(fn), console })
  vm.runInContext(fs.readFileSync(require.resolve('../popup.js'), 'utf8'), context)
  return { context, calls, document, clipboard, get: id => document.getElementById(id), click: id => document.getElementById(id).listeners.click(), poll: () => intervals[0]() }
}

test('locks Study Start before the permission prompt resolves', async () => {
  const permission = deferred()
  let prompts = 0
  const p = popup({ permission: () => { prompts++; return permission.promise } })
  await tick()
  const first = p.click('study-start')
  const second = p.click('study-start')
  assert.equal(prompts, 1)
  assert.equal(p.get('study-now').disabled, true)
  permission.resolve(true)
  await Promise.all([first, second])
})

test('permission denial remains visible beside Study controls after polling', async () => {
  const p = popup({ permission: async () => false })
  await tick()
  await p.click('study-start')
  await p.poll()
  assert.match(p.get('study-status').textContent, /permission/i)
  assert.equal(p.get('study-start').disabled, false)
})

test('capture response errors remain visible beside Study controls', async () => {
  const p = popup({ send: async msg => msg.type === 'popup:state' ? fixture() : { error: 'Backend unavailable' } })
  await tick()
  await p.click('study-now')
  await p.poll()
  assert.match(p.get('study-status').textContent, /Backend unavailable/)
})

test('polling preserves a focused snapshot interval selection', async () => {
  const p = popup()
  await tick()
  p.document.activeElement = p.get('shot-interval')
  p.get('shot-interval').value = '60'
  await p.poll()
  assert.equal(p.get('shot-interval').value, '60')
})

test('continuous page snapshots are labeled as changed-frame capture', async () => {
  const current = fixture()
  current.settings.screenshotsEnabled = true
  current.settings.screenshotIntervalSec = 0
  current.shots.here = 'ready'
  const p = popup({ send: async msg => msg.type === 'popup:state' ? current : {} })
  await tick()
  assert.equal(p.get('shot-interval').value, '0')
  assert.match(p.get('shots-status').textContent, /continuous · changed frames only/)
})

test('an older state response cannot overwrite newer Study state', async () => {
  const old = deferred()
  let polls = 0
  const p = popup({ send: msg => {
    if (msg.type !== 'popup:state') return false
    polls++
    if (polls === 2) return old.promise
    const state = fixture()
    if (polls === 3) state.study = { ...state.study, running: true, status: 'Capturing…' }
    return state
  } })
  await tick()
  const first = p.poll()
  await p.poll()
  old.resolve(fixture())
  await first
  assert.equal(p.get('study-now').disabled, true)
  assert.match(p.get('study-status').textContent, /Capturing/)
})

test('opening Study Capture reports a tab creation failure in the card', async () => {
  const p = popup({ create: async () => { throw new Error('Tab creation failed') } })
  await tick()
  await assert.doesNotReject(async () => p.click('study-screen'))
  assert.match(p.get('study-status').textContent, /could not open/i)
})

test('state refresh failures show a recoverable connection error', async () => {
  let offline = false
  const p = popup({ send: async msg => { if (offline) throw new Error('Worker unavailable'); return msg.type === 'popup:state' ? fixture() : false } })
  await tick()
  offline = true
  await assert.doesNotReject(async () => p.poll())
  assert.match(p.get('study-status').textContent, /reconnect|unavailable|could not/i)
  assert.equal(p.get('study-start').disabled, true)
  offline = false
  await p.poll()
  assert.equal(p.get('study-start').disabled, false)
})

test('Study controls cannot submit before initial state arrives', async () => {
  const initial = deferred()
  const p = popup({ send: msg => msg.type === 'popup:state' ? initial.promise : false })
  await tick()
  await assert.doesNotReject(async () => p.click('study-now'))
  assert.equal(p.calls.filter(msg => msg.type === 'popup:study-capture').length, 0)
  initial.resolve(fixture())
  await tick()
})

test('Stop cancels a pending timed permission request before it can start capture', async () => {
  const permission = deferred()
  const p = popup({ permission: () => permission.promise })
  await tick()
  const start = p.click('study-start')
  await p.click('study-stop')
  permission.resolve(true)
  await start
  assert.equal(p.calls.filter(msg => msg.type === 'popup:study-start').length, 0)
})

test('Study card explains why capture is disabled on an unapproved page', async () => {
  const p = popup({ send: async msg => { const state = fixture(); state.status.state = 'not-allowed'; return msg.type === 'popup:state' ? state : false } })
  await tick()
  assert.equal(p.get('study-now').disabled, true)
  assert.match(p.get('study-status').textContent, /approve|allow/i)
})

test('manual capture gives immediate progress while the backend is responding', async () => {
  const capture = deferred()
  const p = popup({ send: msg => msg.type === 'popup:state' ? fixture() : msg.type === 'popup:study-capture' ? capture.promise : false })
  await tick()
  const request = p.click('study-now')
  assert.match(p.get('study-status').textContent, /captur|sending/i)
  assert.equal(p.get('study-now').disabled, true)
  capture.resolve({})
  await request
})

test('copy diagnostics exports capture logs without requesting page content', async () => {
  const entries = [{ at: '2026-10-25T08:00:00.000Z', event: 'heartbeat_received', tabId: 1 }]
  const p = popup({ send: async msg => msg.type === 'popup:state' ? fixture() : msg.type === 'popup:study-logs' ? { logs: entries } : {} })
  await tick()
  await p.click('study-copy-logs')
  assert.match(p.clipboard.text, /heartbeat_received/)
  assert.match(p.clipboard.text, /exportedAt/)
  assert.match(p.get('message').textContent, /Copied 1 capture diagnostic entries/)
})
