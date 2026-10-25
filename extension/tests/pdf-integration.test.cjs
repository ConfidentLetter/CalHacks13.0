const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
const { webcrypto } = require('node:crypto')
const root = path.join(__dirname, '..')

function worker() {
  let records = []
  let live
  const event = { addListener() {} }
  const context = vm.createContext({ crypto: webcrypto, URL, AbortController, TextEncoder,
    chrome: {
      runtime: { id: 'test', getURL: p => `chrome-extension://test/${p}`, onMessage: event, onInstalled: event, onStartup: event },
      storage: { local: { get: async () => ({}), set: async () => {} }, session: { get: async () => ({}), set: async value => { live = Object.values(value)[0] } } },
      permissions: { onRemoved: event }, alarms: { onAlarm: event },
      tabs: { onRemoved: event, onActivated: event, onUpdated: event }, windows: { onFocusChanged: event },
    },
  })
  context.importScripts = (...files) => files.forEach(file => vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context))
  vm.runInContext(fs.readFileSync(path.join(root, 'background.js'), 'utf8'), context)
  context.read = () => records
  context.write = value => { records = value }
  vm.runInContext(`getSettings = async () => ({ consentGiven: true, trackingEnabled: true }); siteStatus = async () => ({ state: 'approved' }); maybeSnapshot = async () => {}; flush = async () => {}; getRecords = async () => read(); setRecords = async value => write(value); this.progress = handleProgress; this.readPdf = handlers['popup:read-pdf']`, context)
  return { context, readPdf: context.readPdf, progress: context.progress, records: () => records, live: () => live }
}
test('PDF text arriving after a timer update is persisted and queued for resync', async () => {
  const w = worker()
  const msg = { sessionId: 'pdf-1', url: 'https://example.com/notes.pdf', title: 'Notes', activeSec: 5, qualified: true, isPdf: true, state: 'active' }
  await w.progress(msg, { id: 1 })
  await w.progress({ ...msg, text: '[Page 1] Newton laws', pdfPages: 2 }, { id: 1 })
  assert.equal(w.records()[0].excerpt, '[Page 1] Newton laws')
  assert.equal(w.live().pdfPages, 2)
  assert.equal(w.live().text, '[Page 1] Newton laws')
  assert.equal(w.records()[0].synced, false)
})

test('manual PDF extraction saves a safe, stable backend id and readable excerpt', async () => {
  const w = worker()
  w.context.chrome.tabs.get = async () => ({ id: 1, url: 'https://example.com/notes.pdf', title: 'Notes' })
  vm.runInContext(`PDFExtractor.extractFromUrl = async () => ({ text: 'PDF text', pages: 3 })`, w.context)
  await w.readPdf({ tabId: 1, url: 'https://example.com/notes.pdf' })
  await w.readPdf({ tabId: 1, url: 'https://example.com/notes.pdf' })
  assert.equal(w.records().length, 1)
  assert.match(w.records()[0].id, /^[A-Za-z0-9_.:-]{1,120}$/)
  assert.equal(w.records()[0].excerpt, 'PDF text')
})

test('PDF extraction refuses a changed or unapproved tab', async () => {
  const w = worker()
  w.context.chrome.tabs.get = async () => ({ url: 'https://other.example/page' })
  await assert.rejects(w.readPdf({ tabId: 1, url: 'https://example.com/notes.pdf' }), /Approve/)
  assert.equal(w.records().length, 0)
})

test('PDF parser uses one packaged offscreen document for concurrent extraction', async () => {
  let creates = 0
  const sent = []
  const context = vm.createContext({ chrome: {
    runtime: { getURL: p => `chrome-extension://test/${p}`, getContexts: async () => [],
      sendMessage: async msg => { sent.push(msg); return { text: 'Newton', pages: 1 } } },
    offscreen: { createDocument: async args => { creates++; assert.equal(args.url, 'pdf-offscreen.html') } },
  } })
  vm.runInContext(fs.readFileSync(path.join(root, 'pdf-extract.js'), 'utf8') + '\nthis.extract = PDFExtractor.extractFromUrl', context)
  const results = await Promise.all([context.extract('https://example.com/1.pdf'), context.extract('https://example.com/2.pdf')])
  assert.equal(creates, 1)
  assert.equal(results[0].text, 'Newton')
  assert.equal(sent[0].target, 'pdf-offscreen')
})
