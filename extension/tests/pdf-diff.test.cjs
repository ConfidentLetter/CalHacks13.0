const test = require('node:test')
const assert = require('node:assert/strict')
const pdf = require('../pdf-diff.js')

// Synthetic "screen": a toolbar strip on top and a PDF page of text lines below.
const SW = 128
const SH = 160
const TOOLBAR = 20
function screen({ page = 1, scroll = 0, toolbarShade = 230, noise = 0 } = {}) {
  const px = new Uint8ClampedArray(SW * SH * 4)
  let seed = 7
  for (let y = 0; y < SH; y++) {
    for (let x = 0; x < SW; x++) {
      let v = 250
      if (y < TOOLBAR) v = toolbarShade
      else {
        const line = Math.floor((y - TOOLBAR + scroll) / 8)
        const ink = (y - TOOLBAR + scroll) % 8 < 3 && x > 8 && x < 20 + ((line * 37 + page * 53) % 100)
        if (ink) v = 40
      }
      if (noise) { seed = (seed * 16807) % 2147483647; v = Math.max(0, Math.min(255, v + ((seed % (2 * noise + 1)) - noise))) }
      const i = (y * SW + x) * 4
      px[i] = px[i + 1] = px[i + 2] = v
      px[i + 3] = 255
    }
  }
  return px
}

/** Crop + box-downsample like the worker's drawImage step. */
function frame(px, crop, documentId = 'doc-a') {
  const area = crop || { x: 0, y: 0, width: SW, height: SH }
  const { w, h } = pdf.sampleSize(area.width, area.height)
  const out = new Uint8ClampedArray(w * h * 4)
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const sx0 = area.x + Math.floor((x * area.width) / w)
      const sx1 = area.x + Math.floor(((x + 1) * area.width) / w)
      const sy0 = area.y + Math.floor((y * area.height) / h)
      const sy1 = area.y + Math.floor(((y + 1) * area.height) / h)
      for (let c = 0; c < 3; c++) {
        let sum = 0
        let n = 0
        for (let yy = sy0; yy < Math.max(sy1, sy0 + 1); yy++) for (let xx = sx0; xx < Math.max(sx1, sx0 + 1); xx++) { sum += px[(yy * SW + xx) * 4 + c]; n++ }
        out[(y * w + x) * 4 + c] = sum / n
      }
      out[(y * w + x) * 4 + 3] = 255
    }
  }
  return { key: pdf.baselineKey({ documentId, crop, imageWidth: SW, imageHeight: SH }), w, h, pixels: out }
}

const pdfCrop = pdf.cropToPixels({ x: 0, y: TOOLBAR / 2, width: SW / 2, height: (SH - TOOLBAR) / 2 }, { width: SW / 2, height: SH / 2 }, { width: SW, height: SH })
const saveOk = async () => {}

test('first automatic capture is saved and becomes the baseline', async () => {
  const baselines = new Map()
  const r = await pdf.observe(baselines, 1, frame(screen({ page: 30 }), pdfCrop), {}, saveOk)
  assert.equal(r.action, 'save')
  assert.equal(r.reason, 'first')
  assert.ok(baselines.get(1))
})

test('1. identical PDF screenshots (with JPEG-like noise) are discarded', async () => {
  const baselines = new Map()
  await pdf.observe(baselines, 1, frame(screen({ page: 30 }), pdfCrop), {}, saveOk)
  for (let i = 0; i < 5; i++) {
    const r = await pdf.observe(baselines, 1, frame(screen({ page: 30, noise: 4 }), pdfCrop), {}, saveOk)
    assert.equal(r.action, 'unchanged')
  }
})

test('2. a different PDF page is saved and records changed regions', async () => {
  const baselines = new Map()
  await pdf.observe(baselines, 1, frame(screen({ page: 30 }), pdfCrop), {}, saveOk)
  const r = await pdf.observe(baselines, 1, frame(screen({ page: 31 }), pdfCrop), {}, saveOk)
  assert.equal(r.action, 'save')
  assert.ok(r.diff.changedRegions.length >= 1)
  assert.equal(r.diff.regions.length, 16)
  const again = await pdf.observe(baselines, 1, frame(screen({ page: 32 }), pdfCrop), {}, saveOk)
  assert.equal(again.action, 'save')
})

test('3. toolbar-only changes outside the crop are discarded; without a crop they count', async () => {
  const baselines = new Map()
  await pdf.observe(baselines, 1, frame(screen({ page: 30 }), pdfCrop), {}, saveOk)
  assert.equal((await pdf.observe(baselines, 1, frame(screen({ page: 30, toolbarShade: 120 }), pdfCrop), {}, saveOk)).action, 'unchanged')
  const full = new Map()
  await pdf.observe(full, 1, frame(screen({ page: 30 })), {}, saveOk)
  assert.equal((await pdf.observe(full, 1, frame(screen({ page: 30, toolbarShade: 120 })), {}, saveOk)).action, 'save')
})

test('4. scrolling within the PDF is a meaningful change', async () => {
  const baselines = new Map()
  await pdf.observe(baselines, 1, frame(screen({ page: 30 }), pdfCrop), {}, saveOk)
  assert.equal((await pdf.observe(baselines, 1, frame(screen({ page: 30, scroll: 13 }), pdfCrop), {}, saveOk)).action, 'save')
})

test('5. manual capture always saves, even when identical, and moves the baseline', async () => {
  const baselines = new Map()
  await pdf.observe(baselines, 1, frame(screen({ page: 30 }), pdfCrop), {}, saveOk)
  assert.equal((await pdf.observe(baselines, 1, frame(screen({ page: 30 }), pdfCrop), { manual: true }, saveOk)).action, 'save')
  await pdf.observe(baselines, 1, frame(screen({ page: 31 }), pdfCrop), { manual: true }, saveOk)
  // The next automatic frame of the manually saved page is not a duplicate.
  assert.equal((await pdf.observe(baselines, 1, frame(screen({ page: 31 }), pdfCrop), {}, saveOk)).action, 'unchanged')
})

const gateBase = { consent: true, siteState: 'approved', safeUrl: true, incognito: false, autoConsent: true, hasCapturePermission: true,
  manual: false, tab: { id: 4, windowId: 2, active: true }, target: { tabId: 4, windowId: 2 }, focused: true }

test('6. unauthorized, blocked, incognito, and restricted pages are never captured', () => {
  assert.equal(pdf.captureGate(gateBase), 'ok')
  for (const siteState of ['not-allowed', 'blocked', 'needs-permission', 'restricted']) {
    assert.equal(pdf.captureGate({ ...gateBase, siteState }), 'not-approved')
    assert.equal(pdf.captureGate({ ...gateBase, siteState, manual: true }), 'not-approved')
  }
  assert.equal(pdf.captureGate({ ...gateBase, incognito: true, manual: true }), 'restricted')
  assert.equal(pdf.captureGate({ ...gateBase, safeUrl: false }), 'restricted')
  assert.equal(pdf.captureGate({ ...gateBase, consent: false, manual: true }), 'no-consent')
  assert.equal(pdf.captureGate({ ...gateBase, autoConsent: false }), 'no-auto-consent')
})

test('7. switching tabs, windows, or losing focus pauses automatic capture', () => {
  assert.equal(pdf.captureGate({ ...gateBase, tab: { ...gateBase.tab, id: 9 } }), 'paused')
  assert.equal(pdf.captureGate({ ...gateBase, tab: { ...gateBase.tab, active: false } }), 'paused')
  assert.equal(pdf.captureGate({ ...gateBase, tab: { ...gateBase.tab, windowId: 3 } }), 'paused')
  assert.equal(pdf.captureGate({ ...gateBase, focused: false }), 'paused')
})

test('8. a different document, crop, or viewport size resets the baseline', async () => {
  const baselines = new Map()
  await pdf.observe(baselines, 1, frame(screen({ page: 30 }), pdfCrop, 'doc-a'), {}, saveOk)
  const r = await pdf.observe(baselines, 1, frame(screen({ page: 30 }), pdfCrop, 'doc-b'), {}, saveOk)
  assert.equal(r.reason, 'first')
  const recrop = await pdf.observe(baselines, 1, frame(screen({ page: 30 }), { ...pdfCrop, y: pdfCrop.y + 4 }, 'doc-b'), {}, saveOk)
  assert.equal(recrop.reason, 'first')
  assert.notEqual(pdf.baselineKey({ documentId: 'd', crop: null, imageWidth: 100, imageHeight: 50 }),
    pdf.baselineKey({ documentId: 'd', crop: null, imageWidth: 200, imageHeight: 100 }))
})

test('9. a failed save does not move the baseline', async () => {
  const baselines = new Map()
  await pdf.observe(baselines, 1, frame(screen({ page: 30 }), pdfCrop), {}, saveOk)
  const before = baselines.get(1)
  await assert.rejects(pdf.observe(baselines, 1, frame(screen({ page: 31 }), pdfCrop), {}, async () => { throw new Error('quota') }))
  assert.equal(baselines.get(1), before)
  // Page 31 is retried and saved once storage works again.
  assert.equal((await pdf.observe(baselines, 1, frame(screen({ page: 31 }), pdfCrop), {}, saveOk)).action, 'save')
})

test('10. missing Chrome capture permission blocks smart interval with a clear reason', () => {
  assert.equal(pdf.captureGate({ ...gateBase, hasCapturePermission: false }), 'no-permission')
  assert.equal(pdf.captureGate({ ...gateBase, hasCapturePermission: false, manual: true }), 'ok')
})

test('blank or still-rendering frames are never saved automatically', () => {
  const blank = { key: 'k', w: 64, h: 64, pixels: new Uint8ClampedArray(64 * 64 * 4).fill(250) }
  assert.equal(pdf.decide(null, blank).action, 'blank')
  assert.equal(pdf.decide(null, blank, { manual: true }).action, 'save')
})

test('crop math scales DOM rects by the screenshot/viewport ratio and clips to the image', () => {
  // devicePixelRatio 2: a 100×100 CSS rect at (10,10) becomes 200×200 at (20,20).
  assert.deepEqual(pdf.cropToPixels({ x: 10, y: 10, width: 100, height: 100 }, { width: 500, height: 400 }, { width: 1000, height: 800 }),
    { x: 20, y: 20, width: 200, height: 200 })
  assert.deepEqual(pdf.cropToPixels({ x: -50, y: 300, width: 200, height: 500 }, { width: 500, height: 400 }, { width: 1000, height: 800 }),
    { x: 0, y: 600, width: 300, height: 200 })
  assert.equal(pdf.cropToPixels({ x: 0, y: 0, width: 5, height: 5 }, { width: 500, height: 400 }, { width: 1000, height: 800 }), null)
  assert.deepEqual(pdf.fractionToPixels({ x: 0.5, y: 0.25, width: 0.5, height: 0.5 }, { width: 1000, height: 800 }), { x: 500, y: 200, width: 500, height: 400 })
  assert.equal(pdf.validInterval(10), true)
  for (const v of [4, 301, 10.5, '10']) assert.equal(pdf.validInterval(v), false)
})
