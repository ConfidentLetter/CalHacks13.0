// PDF observer rules: 16-region RGB comparison, crop math and baseline decisions.
// Side-effect free; loaded by the worker (importScripts) and by Node tests.
;(function (root) {
  // Tune here. pixel: normalized RGB difference per pixel; regionFraction: share of a region's
  // pixels that must exceed `pixel`; minRegions: changed regions needed to keep a capture.
  const THRESHOLDS = { pixel: 0.08, regionFraction: 0.01, minRegions: 1, grid: 4, sampleWidth: 64, maxSampleHeight: 256, blankStdDev: 2 }

  /** Comparison size: fixed width, aspect-preserving height, bounded memory (≤ 64×256 RGBA). */
  function sampleSize(width, height, t = THRESHOLDS) {
    const w = t.sampleWidth
    const h = Math.max(t.grid, Math.min(t.maxSampleHeight, Math.round((w * height) / Math.max(1, width))))
    return { w, h }
  }

  /** DOM rect (CSS px, viewport-relative) → screenshot pixels, clipped to the image. Null if unusable. */
  function cropToPixels(rect, viewport, image) {
    if (!rect || !viewport?.width || !viewport?.height || !image?.width || !image?.height) return null
    // The ratio covers devicePixelRatio and page zoom; captureVisibleTab returns the viewport only.
    const sx = image.width / viewport.width
    const sy = image.height / viewport.height
    const x0 = Math.max(0, Math.floor(rect.x * sx))
    const y0 = Math.max(0, Math.floor(rect.y * sy))
    const x1 = Math.min(image.width, Math.ceil((rect.x + rect.width) * sx))
    const y1 = Math.min(image.height, Math.ceil((rect.y + rect.height) * sy))
    if (x1 - x0 < 32 || y1 - y0 < 32) return null
    return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 }
  }

  /** Fractional crop (0–1 of the viewport, from the user's selection) → screenshot pixels. */
  function fractionToPixels(f, image) {
    if (!f) return null
    return cropToPixels({ x: f.x, y: f.y, width: f.width, height: f.height }, { width: 1, height: 1 }, image)
  }

  /** Compare two equally sized RGBA buffers on a grid×grid layout. */
  function compareGrid(a, b, w, h, t = THRESHOLDS) {
    const g = t.grid
    const regions = []
    for (let ry = 0; ry < g; ry++) {
      const y0 = Math.floor((ry * h) / g)
      const y1 = Math.floor(((ry + 1) * h) / g)
      for (let rx = 0; rx < g; rx++) {
        const x0 = Math.floor((rx * w) / g)
        const x1 = Math.floor(((rx + 1) * w) / g)
        let over = 0
        let sum = 0
        let n = 0
        for (let y = y0; y < y1; y++) {
          for (let x = x0; x < x1; x++) {
            const i = (y * w + x) * 4
            const d = (Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2])) / 765
            sum += d
            if (d > t.pixel) over++
            n++
          }
        }
        const fraction = n ? over / n : 0
        regions.push({ index: ry * g + rx, fraction, avg: n ? sum / n : 0, changed: fraction >= t.regionFraction })
      }
    }
    const changedRegions = regions.filter((r) => r.changed).map((r) => r.index)
    return { regions, changedRegions, changed: changedRegions.length >= t.minRegions }
  }

  /** A nearly uniform frame is a loading/blank viewer: never upload it automatically. */
  function isBlank(pixels, t = THRESHOLDS) {
    let sum = 0
    let sq = 0
    let n = 0
    for (let i = 0; i < pixels.length; i += 4) {
      const v = (pixels[i] + pixels[i + 1] + pixels[i + 2]) / 3
      sum += v
      sq += v * v
      n++
    }
    if (!n) return true
    const mean = sum / n
    return Math.sqrt(Math.max(0, sq / n - mean * mean)) < t.blankStdDev
  }

  /** Baselines reset whenever the document, crop, or viewport size changes. */
  const baselineKey = ({ documentId, crop, imageWidth, imageHeight }) =>
    [documentId || '', crop ? `${crop.x},${crop.y},${crop.width},${crop.height}` : 'full', `${imageWidth}x${imageHeight}`].join('|')

  /**
   * Decide what to do with one frame. frame = { key, w, h, pixels }.
   * Returns { action: 'save' | 'unchanged' | 'blank', diff, reason }.
   */
  function decide(baseline, frame, { manual = false } = {}, t = THRESHOLDS) {
    if (manual) return { action: 'save', reason: 'manual', diff: null }
    if (isBlank(frame.pixels, t)) return { action: 'blank', reason: 'blank', diff: null }
    if (!baseline || baseline.key !== frame.key || baseline.w !== frame.w || baseline.h !== frame.h) {
      return { action: 'save', reason: 'first', diff: null }
    }
    const diff = compareGrid(baseline.pixels, frame.pixels, frame.w, frame.h, t)
    return { action: diff.changed ? 'save' : 'unchanged', reason: diff.changed ? 'changed' : 'unchanged', diff }
  }

  /**
   * Full save rule. `save` persists the screenshot and may throw; the baseline (the last KEPT frame)
   * moves only after it succeeds. baselines: Map(tabId → baseline).
   */
  async function observe(baselines, tabId, frame, opts, save) {
    const verdict = decide(baselines.get(tabId), frame, opts)
    if (verdict.action !== 'save') return verdict
    await save(verdict)
    baselines.set(tabId, { key: frame.key, w: frame.w, h: frame.h, pixels: frame.pixels })
    return verdict
  }

  /** Why the observer may or may not capture this tab now. 'ok' means capture. */
  function captureGate({ consent, siteState, safeUrl, incognito, autoConsent, hasCapturePermission, manual, tab, target, focused }) {
    if (!consent) return 'no-consent'
    if (incognito || !safeUrl) return 'restricted'
    if (siteState !== 'approved') return 'not-approved'
    if (manual) return 'ok'
    if (!autoConsent) return 'no-auto-consent'
    if (!hasCapturePermission) return 'no-permission'
    if (!(tab && target && focused && tab.active && tab.id === target.tabId && tab.windowId === target.windowId)) return 'paused'
    return 'ok'
  }

  const validInterval = (s) => Number.isInteger(s) && s >= 5 && s <= 300

  const api = { THRESHOLDS, sampleSize, cropToPixels, fractionToPixels, compareGrid, isBlank, baselineKey, decide, observe, captureGate, validInterval }
  if (typeof module !== 'undefined' && module.exports) module.exports = api
  else root.PdfDiff = api
})(globalThis)
