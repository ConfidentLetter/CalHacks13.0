import { useCallback, useMemo, useState } from 'react'
import { Button } from '../ui/Button'
import { Segmented } from '../ui/Controls'
import { useNow } from '../../hooks/useInterval'
import { cx, formatClock } from '../../utils/format'
import { PageTwin } from './PageTwin'
import { LineLedger } from './LineLedger'
import { LineInspector } from './LineInspector'
import { SummaryStrip } from './SummaryStrip'
import { inkRegion } from './twinModel'

const SLOW_AFTER_MS = 20_000
const BUDGET_S = 60

function Eyebrow({ n, children, className }) {
  return (
    <p className={cx('flex items-center gap-2 text-[11px] font-bold tracking-[0.18em] text-olive/60 uppercase', className)}>
      {n && <span className="font-display text-sm tracking-normal text-olive">{n}</span>}
      {n && <span aria-hidden="true">—</span>}
      {children}
    </p>
  )
}

/** Skeleton ruled page whose "ink" fills in line by line while the backend reads the page. */
function ReadingSkeleton({ startedAt }) {
  const now = useNow(1000)
  const elapsed = startedAt ? Math.floor((now - startedAt) / 1000) : 0
  const slow = elapsed * 1000 >= SLOW_AFTER_MS
  return (
    <div className="grid gap-6 lg:grid-cols-[1.15fr_1fr]" aria-live="polite" aria-busy="true">
      <div className="ruled-lg relative min-h-[420px] border border-olive/70 bg-white p-6">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="ink-fill mt-9 first:mt-3" style={{ width: `${[72, 58, 40, 64, 30, 52][i]}%`, animationDelay: `${i * 0.25}s` }} />
        ))}
        <p className="absolute right-4 bottom-3 text-[13px] text-olive/55 tabular-nums">
          {slow ? `still reading your page… ${elapsed} s of a ${BUDGET_S} s budget` : `reading your page… ${elapsed} s`}
        </p>
      </div>
      <div className="space-y-3 pt-1">
        <div className="skeleton h-5 w-2/3" />
        <div className="skeleton h-4 w-11/12" />
        <div className="skeleton h-4 w-4/5" />
        <div className="skeleton mt-6 h-14 w-full" />
        <div className="skeleton h-14 w-full" />
      </div>
    </div>
  )
}

/** Camera-off / nothing-read state: an empty ruled page and one line of copy — never blank. */
function EmptyPage({ copy }) {
  return (
    <div className="ruled-lg relative grid min-h-[320px] place-items-center border border-dashed border-sage-deep bg-white p-8 text-center">
      <p className="max-w-md text-[15px] leading-relaxed text-olive/70">{copy}</p>
    </div>
  )
}

/**
 * The hero: page twin (dewarped image + boxes) beside the line ledger, with the summary strip and a side-sheet
 * inspector for the selected line. `model` comes from buildRecognition(); `loading`/`error` from the analyze call.
 */
export function RecognitionView({ model, loading, startedAt, error, onRetry, emptyCopy, showSummary = true, className }) {
  const snapshotId = model?.snapshotId || null
  // selection/view state is keyed by the page it belongs to, so a new page starts clean without an effect
  const [ui, setUi] = useState({ snapshotId, selectedId: null, inspecting: false, view: 'twin' })
  const current = ui.snapshotId === snapshotId ? ui : { snapshotId, selectedId: null, inspecting: false, view: 'twin' }
  const { selectedId, inspecting, view } = current
  const [hoveredId, setHoveredId] = useState(null)
  const patch = useCallback((changes) => setUi((prev) => ({ ...(prev.snapshotId === snapshotId ? prev : { snapshotId, selectedId: null, inspecting: false, view: 'twin' }), ...changes })), [snapshotId])

  const lines = useMemo(() => model?.lines || [], [model])
  const setView = useCallback((v) => patch({ view: v }), [patch])
  const select = useCallback((id) => patch({ selectedId: id, inspecting: true }), [patch])
  const closeInspector = useCallback(() => patch({ inspecting: false }), [patch])
  const step = useCallback(
    (delta) => {
      if (!lines.length) return
      const i = lines.findIndex((l) => l.id === selectedId)
      patch({ selectedId: lines[(i + delta + lines.length) % lines.length].id })
    },
    [lines, selectedId, patch],
  )

  const selected = useMemo(() => lines.find((l) => l.id === selectedId) || null, [lines, selectedId])
  const hasStill = Boolean(model?.image?.stillUrl && model.image.stillUrl !== model.image.url)
  const region = useMemo(() => inkRegion(lines, model?.image), [lines, model])
  // default view: zoom to the writing when that helps, else the whole page
  const effectiveView = view === 'twin' ? (region ? 'writing' : 'page') : view
  const viewOptions = [
    ...(region ? [{ value: 'writing', label: 'writing' }] : []),
    { value: 'page', label: 'page' },
    ...(hasStill ? [{ value: 'still', label: 'still' }] : []),
  ]

  return (
    <section id="page-twin" className={cx('scroll-mt-24 space-y-5', className)} aria-label="Recognition">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-olive/70 pb-3">
        <div>
          <Eyebrow n="01">the page twin</Eyebrow>
          <h2 className="mt-1 text-[1.65rem] leading-tight text-olive">
            {loading ? 'reading your page' : model ? 'every line, as written' : 'your page, line by line'}
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {model?.capturedAt && !loading && (
            <span className="text-[13px] text-olive/55">
              {model.judged ? 'checked' : 'read'} {formatClock(model.capturedAt)}
            </span>
          )}
          {model && !loading && viewOptions.length > 1 && (
            <Segmented size="sm" label="Page view" value={effectiveView} onChange={setView} options={viewOptions} />
          )}
        </div>
      </header>

      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-3 border-l-[3px] border-clay bg-clay/10 px-4 py-3 text-[15px] text-clay">
          <span className="flex-1">Analysis failed: {error}</span>
          {onRetry && (
            <Button size="sm" variant="ghost" onClick={onRetry}>
              Retry
            </Button>
          )}
        </div>
      )}

      {loading ? (
        <ReadingSkeleton startedAt={startedAt} />
      ) : !model ? (
        <EmptyPage copy={emptyCopy} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1.15fr_1fr] lg:items-start">
          <div className="space-y-2">
            <PageTwin
              image={effectiveView === 'still' ? { ...model.image, url: model.image.stillUrl, width: null, height: null } : model.image}
              showBoxes={effectiveView !== 'still'}
              region={effectiveView === 'writing' ? region : null}
              lines={lines}
              selectedId={selectedId}
              hoveredId={hoveredId}
              onSelect={select}
              onHover={setHoveredId}
              maxHeight={760}
            />
            <p className="text-[13px] text-olive/55">
              {effectiveView === 'still'
                ? 'the still exactly as the camera saw it'
                : effectiveView === 'writing'
                  ? 'the flattened page, zoomed to the writing · click a box for crops and both readings'
                  : lines.some((l) => l.bbox)
                    ? 'the flattened page · click a box for crops and both readings'
                    : 'the flattened page'}
            </p>
          </div>
          <div className="space-y-5">
            {lines.length ? (
              <LineLedger lines={lines} selectedId={selectedId} hoveredId={hoveredId} onSelect={select} onHover={setHoveredId} />
            ) : (
              <EmptyPage copy="no lines were read on this page — lay it flat under the camera and try again." />
            )}
            {showSummary && <SummaryStrip model={model} />}
          </div>
        </div>
      )}

      <LineInspector line={inspecting ? selected : null} total={lines.length} onClose={closeInspector} onStep={step} />
    </section>
  )
}
