// Pure helpers that turn the bridge's analyze result and/or T4's page twin into one line model
// for the recognition view. Nothing here rewrites a label: `latex`/`text` are passed through verbatim.

import { resolveUrl } from '../../services/api'

export const LOW_CONFIDENCE = 0.6

/** Twin paths are repo-relative (`runtime/crops/...`); T4 serves them at `/files/<path>`. Bridge URLs are already `/files/...`. */
export function fileUrl(path) {
  if (!path) return null
  if (/^(https?:|data:|blob:|\/)/.test(path)) return resolveUrl(path)
  return resolveUrl(`/files/${path}`)
}

/** Visual tone of a line: 'error' | 'correct' | 'crossed' | 'unclear' | 'read' (transcribed, not judged). */
export function toneOf(line) {
  if (line.lineStatus === 'crossed_out') return 'crossed'
  if (line.judge === 'error') return 'error'
  if (line.judge === 'correct' && !line.lowConfidence) return 'correct'
  if (line.judge === 'unclear' || line.lineStatus === 'illegible' || line.lowConfidence) return 'unclear'
  return 'read'
}

export const TONE_LABEL = {
  error: 'error',
  correct: 'correct',
  crossed: 'crossed out',
  unclear: 'unclear',
  read: 'read',
}

function readingText(r) {
  if (r == null) return null
  if (typeof r === 'string') return r
  if (r.illegible && !(r.latex || r.text)) return ''
  return r.latex || r.text || ''
}

function normalizeReadings(raw, fallbackLine) {
  const r = raw && typeof raw === 'object' ? raw : {}
  const page = readingText(r.page)
  const line = r.line !== undefined ? readingText(r.line) : fallbackLine ?? null
  const notes = Array.isArray(r.notes) ? r.notes.map(String) : []
  const agree =
    typeof r.agree === 'boolean'
      ? r.agree
      : page != null && line != null && page === line && !notes.some((n) => n === 'disagree' || n === 'near_disagree')
  return { page, line, reread: readingText(r.reread), agree, notes }
}

function normalizeReread(raw) {
  if (!raw || typeof raw !== 'object') return null
  const cand = raw.candidates
  const candidates = Array.isArray(cand)
    ? cand.map((c, i) => ({ key: String.fromCharCode(65 + i), value: readingText(c) ?? '' }))
    : cand && typeof cand === 'object'
      ? Object.entries(cand).map(([key, value]) => ({ key, value: readingText(value) ?? '' }))
      : []
  const result = raw.result && typeof raw.result === 'object' ? raw.result : raw
  return {
    zoomUrl: fileUrl(raw.zoom_path || raw.zoomUrl),
    candidates,
    choice: result.choice ?? result.pick ?? null,
    reading: readingText(result.latex || result.text ? result : null),
  }
}

function bboxOf(v) {
  if (!Array.isArray(v) || v.length !== 4) return null
  const b = v.map(Number)
  return b.every(Number.isFinite) ? b : null
}

/** One twin line (T4/T3 shape) → model line, unjudged. */
export function lineFromTwin(l) {
  const latex = l.latex || ''
  const text = l.text || ''
  const confidence = Number(l.confidence ?? 0)
  return {
    id: String(l.id),
    order: Number(l.order ?? 0),
    latex,
    text,
    label: latex || text,
    kind: l.kind || (latex ? 'math' : 'text'),
    lineStatus: l.status || 'active',
    judge: null,
    note: '',
    confidence,
    lowConfidence: confidence < LOW_CONFIDENCE,
    bbox: bboxOf(l.bbox),
    cropUrl: fileUrl(l.crop_path),
    contextCropUrl: fileUrl(l.context_crop_path),
    readings: normalizeReadings(l.readings, latex || text || null),
    reread: normalizeReread(l.reread),
    uncertainSpans: Array.isArray(l.uncertain_spans) ? l.uncertain_spans : [],
  }
}

/** One analyze step (bridge shape) → model line, judged. */
export function lineFromStep(s, order) {
  const label = s.label ?? ''
  const confidence = Number(s.confidence ?? 0)
  return {
    id: String(s.id ?? `S${order}`),
    order,
    latex: label,
    text: label,
    label,
    kind: 'math',
    lineStatus: s.lineStatus || 'active',
    judge: s.status || 'unclear',
    note: s.note || '',
    confidence,
    lowConfidence: confidence < LOW_CONFIDENCE,
    bbox: bboxOf(s.bbox),
    cropUrl: resolveUrl(s.cropUrl),
    contextCropUrl: resolveUrl(s.contextCropUrl),
    readings: normalizeReadings(s.readings, label || null),
    reread: null,
    uncertainSpans: Array.isArray(s.uncertainSpans) ? s.uncertainSpans : [],
  }
}

/** Merge judged steps with the twin's recognition detail (bbox, crops, readings, kind). Twin fields win for geometry. */
export function mergeStepsWithTwin(steps = [], twin = null) {
  const byId = new Map((twin?.lines || []).map((l) => [String(l.id), lineFromTwin(l)]))
  const merged = steps.map((s, i) => {
    const step = lineFromStep(s, i)
    const t = byId.get(step.id)
    if (!t) return step
    byId.delete(step.id)
    return {
      ...t,
      ...step,
      // the twin has the richer recognition detail; the step has the judgement
      latex: t.latex,
      text: t.text,
      kind: t.kind,
      label: step.label || t.label,
      bbox: t.bbox || step.bbox,
      cropUrl: t.cropUrl || step.cropUrl,
      contextCropUrl: t.contextCropUrl || step.contextCropUrl,
      readings: t.readings.page != null || t.readings.line != null ? t.readings : step.readings,
      reread: t.reread,
      uncertainSpans: t.uncertainSpans.length ? t.uncertainSpans : step.uncertainSpans,
    }
  })
  // lines the judge never saw (should not happen) are still shown, unjudged
  const rest = [...byId.values()]
  return [...merged, ...rest].sort((a, b) => a.order - b.order || a.id.localeCompare(b.id))
}

/** Image descriptor for the PageTwin canvas: the dewarped page is the coordinate space of every bbox. */
export function imageOf(result, twin) {
  const img = twin?.image
  const url = fileUrl(result?.dewarpedUrl) || fileUrl(img?.dewarped_path) || fileUrl(result?.imageUrl) || null
  return { url, width: Number(img?.width) || null, height: Number(img?.height) || null, stillUrl: fileUrl(result?.imageUrl) || fileUrl(img?.original_path) }
}

/** Build the whole recognition model from (result, twin); either may be null. */
export function buildRecognition({ result = null, twin = null }) {
  if (!result && !twin) return null
  const lines = result ? mergeStepsWithTwin(result.steps || [], twin) : (twin.lines || []).map(lineFromTwin).sort((a, b) => a.order - b.order)
  const counts = countLines(lines)
  return {
    snapshotId: result?.snapshotId || twin?.snapshot_id || null,
    judged: Boolean(result),
    analysisFailed: Boolean(result?.analysisFailed),
    capturedAt: result?.analyzedAt || twin?.captured_at || null,
    image: imageOf(result, twin),
    lines,
    counts,
    summary: result?.summary || '',
    topics: result?.topics || [],
    hints: result?.hints || [],
    quality: result?.quality || twin?.quality || null,
    latencyMs: result?.latencyMs || twin?.latency_ms || null,
  }
}

export function countLines(lines) {
  const c = { total: lines.length, errors: 0, correct: 0, crossed: 0, unclear: 0, illegible: 0 }
  for (const l of lines) {
    const t = toneOf(l)
    if (t === 'error') c.errors++
    else if (t === 'correct') c.correct++
    else if (t === 'crossed') c.crossed++
    else if (t === 'unclear') c.unclear++
    if (l.lineStatus === 'illegible') c.illegible++
  }
  return c
}

/** "read in 10.7 s" from latencyMs (bridge_total first, then total / snapshot_to_twin). */
export function readInSeconds(latencyMs) {
  const ms = latencyMs?.bridge_total ?? latencyMs?.total ?? latencyMs?.snapshot_to_twin
  if (!Number.isFinite(Number(ms))) return null
  return (Number(ms) / 1000).toFixed(1)
}

/**
 * Region of the page that actually carries ink: the union of all line boxes plus a margin, clamped to the
 * image. Returns null when there are no boxes or the ink already covers most of the page (then zooming
 * would not help). Used by the "writing" view so a tall sheet with four lines at the top reads from 3 m.
 */
export function inkRegion(lines, image, { margin = 0.05, minGain = 1.35 } = {}) {
  const W = image?.width
  const H = image?.height
  const boxes = (lines || []).map((l) => l.bbox).filter(Boolean)
  if (!W || !H || !boxes.length) return null
  let x0 = Infinity
  let y0 = Infinity
  let x1 = -Infinity
  let y1 = -Infinity
  for (const [x, y, w, h] of boxes) {
    x0 = Math.min(x0, x)
    y0 = Math.min(y0, y)
    x1 = Math.max(x1, x + w)
    y1 = Math.max(y1, y + h)
  }
  const pad = Math.max(W, H) * margin
  const rx0 = Math.max(0, x0 - pad)
  const ry0 = Math.max(0, y0 - pad)
  const rx1 = Math.min(W, x1 + pad)
  const ry1 = Math.min(H, y1 + pad)
  const region = { x: rx0, y: ry0, width: rx1 - rx0, height: ry1 - ry0 }
  if (region.width <= 0 || region.height <= 0) return null
  // only worth it when the region is clearly smaller than the page (by the larger of the two axes)
  const gain = Math.max(W / region.width, H / region.height)
  return gain >= minGain ? region : null
}
