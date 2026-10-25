import { MathText } from '../components/shared/MathTextRenderer'
import { useState } from 'react'
import { useApp, useCamera, useStudyData } from '../context/contexts'
import { Button } from '../components/ui/Button'
import { StatusDot } from '../components/ui/Badge'
import { ErrorState, Skeleton } from '../components/ui/Feedback'
import { LiveVideo } from '../components/shared/LiveVideo'
import { PageTwin } from '../components/recognition/PageTwin'
import { inkRegion } from '../components/recognition/twinModel'
import { useNow } from '../hooks/useInterval'
import { cx, domainOf, formatClock, formatDuration, isToday, timeAgo } from '../utils/format'
import { savedConversationLink } from '../features/conversations/links'

const journalLinkClass = 'group grid grid-cols-[2rem_1fr_auto] items-baseline gap-2 rounded-sm border border-olive/20 bg-white px-3 py-3 shadow-[0_2px_0_#e6dac1] transition hover:border-sage-deep hover:bg-sage/15 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sage-ink'

const QUICK_PROMPTS = ['check the page on my desk', 'explain integration by parts', 'quiz me on what i read today']

function greeting() {
  const h = new Date().getHours()
  return h < 5 ? 'burning the midnight oil' : h < 12 ? 'good morning' : h < 18 ? 'good afternoon' : 'good evening'
}

const today = () =>
  new Date().toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' }).toLowerCase()

/** Small editorial section label: "01 — latest snapshot". */
function Eyebrow({ n, children, className }) {
  return (
    <p className={cx('flex items-center gap-2 text-[11px] font-bold tracking-[0.18em] text-olive/60 uppercase', className)}>
      {n && <span className="font-display text-sm tracking-normal text-olive"><MathText>{n}</MathText></span>}
      {n && <span aria-hidden="true">—</span>}
      {children}
    </p>
  )
}

// ---- welcome ----------------------------------------------------------------

function Welcome() {
  const { askTutor } = useApp()
  const { readings, recogStats } = useStudyData()
  const [q, setQ] = useState('')
  const pages = readings.filter((r) => isToday(r.timestamp))
  const seconds = pages.reduce((a, r) => a + (r.durationSec || 0), 0)
  const stats = [
    ['lines read today', recogStats?.linesRead ?? 0],
    ['errors caught', recogStats?.errorsCaught ?? 0],
    ['pages today', pages.length],
    ['active reading', formatDuration(seconds)],
  ]

  const submit = (e) => {
    e.preventDefault()
    if (q.trim()) askTutor(q.trim())
  }

  return (
    <section className="grid gap-8 border-b border-olive/70 pb-8 md:grid-cols-[1.4fr_1fr] md:items-end">
      <div>
        <p className="flex flex-wrap items-center gap-x-3 text-xs font-semibold tracking-wide text-olive/60 uppercase">
          <span className="text-sage-ink">{greeting()}</span>
          <span aria-hidden="true">·</span>
          <span>{today()}</span>
        </p>
        <h2 className="mt-3 max-w-[14ch] text-[2.6rem] leading-[1.02] text-olive sm:text-6xl">
          a quiet place to <span className="scribble">study</span>.
        </h2>
        <p className="mt-4 max-w-md text-base text-olive/70">
          your notebook, the pages you read, and a tutor who’s seen both — kept together on one desk.
        </p>
        <dl className="mt-6 flex flex-wrap gap-x-8 gap-y-3">
          {stats.map(([label, value]) => (
            <div key={label}>
              <dt className="text-[11px] font-semibold tracking-wide text-olive/55 uppercase">{label}</dt>
              <dd className="font-display text-3xl text-olive tabular-nums"><MathText>{value}</MathText></dd>
            </div>
          ))}
        </dl>
      </div>

      {/* sticky note — quick question */}
      <form onSubmit={submit} className="sticky-note rotate-[1.2deg] p-4 motion-reduce:rotate-0 sm:p-5">
        <label htmlFor="quick-ask" className="font-display text-lg text-olive">
          ask a little question
        </label>
        <div className="mt-2 flex gap-2 border-b-2 border-olive/70 pb-1 focus-within:border-olive">
          <input
            id="quick-ask"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="about your notes or reading…"
            className="min-w-0 flex-1 bg-transparent py-1 text-sm text-olive outline-none placeholder:text-olive/50"
            autoComplete="off"
          />
          <button
            type="submit"
            disabled={!q.trim()}
            aria-label="Ask the AI tutor"
            className="grid h-8 px-2 place-items-center text-olive transition hover:bg-olive/10 disabled:opacity-40"
          >
            Ask
          </button>
        </div>
        <ul className="mt-3 space-y-1">
          {QUICK_PROMPTS.map((p) => (
            <li key={p}>
              <button
                type="button"
                onClick={() => askTutor(p)}
                className="text-left text-xs text-olive/80 underline decoration-olive/30 underline-offset-4 transition hover:text-olive hover:decoration-olive"
              >
                → {p}
              </button>
            </li>
          ))}
        </ul>
      </form>
    </section>
  )
}

// ---- status ledger ----------------------------------------------------------

function StatusLedger() {
  const { navigate } = useApp()
  const { status, extension, lastFrame } = useStudyData()
  const camera = useCamera()
  const cam = status.data?.camera
  const ai = status.data?.ai
  const ext = extension.info

  if (status.loading && !status.data) return <Skeleton className="h-14 rounded-sm" />

  const rows = [
    {
      label: 'camera',
      state: camera.isLive ? 'active' : 'idle',
      value: camera.isLive ? 'live' : 'off',
      note: lastFrame ? `last still ${timeAgo(lastFrame.capturedAt)}` : cam?.connected ? 'overhead camera online' : null,
      to: 'notebook',
    },
    {
      label: 'reading tracker',
      state: !extension.connected ? 'idle' : ext?.trackingEnabled ? 'online' : 'warning',
      value: !extension.connected ? 'extension not detected' : ext?.trackingEnabled ? 'tracking' : 'paused',
      note: extension.connected ? `${ext?.allowedSites?.length ?? 0} approved sites` : 'load it from /extension',
      to: 'reading',
    },
    {
      label: 'tutor',
      state: ai?.available ? 'online' : 'offline',
      value: ai?.available ? 'ready' : ai ? 'unavailable' : 'backend offline',
      note: ai?.model || null,
      to: 'tutor',
    },
  ]

  return (
    <dl className="grid border-y border-dotted border-olive/40 sm:grid-cols-3 sm:divide-x sm:divide-dotted sm:divide-olive/40">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-3 py-3 sm:px-4 sm:first:pl-0 sm:last:pr-0">
          <StatusDot state={r.state} pulse={r.state === 'active'} />
          <div className="min-w-0 flex-1 leading-tight">
            <dt className="text-[11px] font-semibold tracking-wide text-olive/55 uppercase">{r.label}</dt>
            <dd className="truncate text-sm text-olive">
              {r.value}
              {r.note && <span className="text-olive/55"> · <MathText>{r.note}</MathText></span>}
            </dd>
          </div>
          <button
            type="button"
            onClick={() => navigate(r.to)}
            aria-label={`Open ${r.label}`}
            className="grid h-7 px-2 shrink-0 place-items-center border border-olive/30 text-olive transition hover:bg-butter"
          >
            Open
          </button>
        </div>
      ))}
    </dl>
  )
}

// ---- notebook centrepiece -------------------------------------------------

function Notebook() {
  const { navigate } = useApp()
  const { analysis, lastFrame, recognition } = useStudyData()
  const camera = useCamera()
  const twinCounts = recognition?.counts
  return (
    <section className="relative">
      {/* second sheet underneath */}
      <div aria-hidden="true" className="absolute inset-0 translate-x-2 translate-y-2 border border-olive/40 bg-paper" />
      <div className="relative border border-olive/70 bg-white">
        {/* notebook index tab */}
        <span aria-hidden="true" className="absolute -top-3 left-6 h-3 w-16 border border-b-0 border-olive/70 bg-sage" />
        <header className="flex flex-wrap items-end justify-between gap-3 border-b border-olive/70 px-5 py-4">
          <div>
            <Eyebrow n="01">the notebook</Eyebrow>
            <h3 className="mt-1 text-2xl text-olive">{recognition ? 'your page, read' : camera.isLive ? 'live on your desk' : 'your page'}</h3>
          </div>
          <span className="flex items-center gap-1.5 text-xs text-olive/60">
            {recognition && twinCounts ? (
              <>
                <span className="tabular-nums">{twinCounts.total} lines</span>
                {twinCounts.errors > 0 && (
                  <span className="border border-ink-red bg-ink-red/10 px-1.5 font-bold text-ink-red tabular-nums">{twinCounts.errors} error{twinCounts.errors > 1 ? 's' : ''}</span>
                )}
                {twinCounts.crossed > 0 && <span className="tabular-nums">· {twinCounts.crossed} crossed out</span>}
              </>
            ) : (
              <>
                <StatusDot state={camera.isLive ? 'offline' : 'idle'} pulse={camera.isLive} />
                {camera.isLive ? 'live camera on' : 'camera off'}
              </>
            )}
          </span>
        </header>
        <div className="grid gap-5 p-5 lg:grid-cols-[1.5fr_1fr]">
          {recognition ? (
            <button
              type="button"
              onClick={() => navigate('notebook')}
              className="group relative block text-left"
              aria-label="Open the page twin"
            >
              <PageTwin image={recognition.image} lines={recognition.lines} region={inkRegion(recognition.lines, recognition.image)} compact maxHeight={440} />
              <span className="absolute top-2 left-2 border border-olive/40 bg-butter px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-olive uppercase">
                page twin
              </span>
            </button>
          ) : (
            <div className="relative aspect-video overflow-hidden border border-olive/70 bg-olive">
              {camera.isLive && camera.stream ? (
                <LiveVideo stream={camera.stream} />
              ) : (
                <div className="grid size-full place-items-center p-6 text-center text-cream">
                  <div className="space-y-3">
                    <p className="font-display text-lg">camera off</p>
                    <Button variant="primary" onClick={() => navigate('notebook')}>
                      Start the live camera
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="flex flex-col gap-4">
            <div className="ruled flex-1 border-l-2 border-clay/40 pl-4 text-sm leading-7 text-olive/80 [background-position:0_0]">
              {recognition?.summary ? (
                <>
                  <span className="font-semibold text-olive">
                    notes on the page from {formatClock(recognition.capturedAt)} —{' '}
                  </span>
                  <MathText>{recognition.summary}</MathText>
                </>
              ) : recognition ? (
                <MathText>{`${recognition.counts.total} lines read from the page at ${formatClock(recognition.capturedAt)} — open the notebook to have Pip check them.`}</MathText>
              ) : analysis.data ? (
                <MathText>{analysis.data.summary}</MathText>
              ) : lastFrame ? (
                <MathText>{`Pip last looked at a still from ${formatClock(lastFrame.capturedAt)}.`}</MathText>
              ) : (
                'the preview is just for you. Pip only sees a single still when you ask a question or press Analyze.'
              )}
            </div>
            <Button variant="primary" className="self-start" onClick={() => navigate('notebook')}>
              {recognition ? 'see every line' : camera.isLive ? 'ask about this page' : 'open the camera'}
            </Button>
          </div>
        </div>
      </div>
    </section>
  )
}

// ---- journal + reading list -------------------------------------------------

function Journal() {
  const { activity } = useStudyData()
  const now = useNow()
  return (
    <section>
      <Eyebrow n="02">today’s journal</Eyebrow>
      <h3 className="mt-1 text-2xl text-olive">what happened</h3>
      {!activity.length ? (
        <p className="mt-4 border-l-2 border-butter-deep pl-4 text-sm leading-relaxed text-olive/65">
          all quiet for now. captures, questions and reading sessions will be written here as you study.
        </p>
      ) : (
        <ol className="mt-4 space-y-3">
          {activity.slice(0, 8).map((e, i) => (
            <li
              key={e.id}
            >
              <a href={savedConversationLink(e)} className={journalLinkClass} aria-label={`Open conversation: ${e.title}`}>
              <span className="font-display text-sm text-olive/50 tabular-nums"><MathText>{String(i + 1).padStart(2, '0')}</MathText></span>
              <div className="min-w-0">
                <p className="truncate text-sm text-olive"><MathText>{e.title}</MathText></p>
                <p className="truncate text-xs text-olive/55">
                  {e.type === 'reading' ? `${domainOf(e.detail)} · read ${formatDuration(e.durationSec)}` : e.detail}
                </p>
              </div>
              <time className="text-[11px] text-olive/50 tabular-nums" dateTime={e.at}>
                {timeAgo(e.at, now)}
              </time>
              </a>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function ReadingList() {
  const { navigate } = useApp()
  const { readings, readingsState, refreshReadings, newIds } = useStudyData()
  const now = useNow()
  return (
    <section>
      <div className="flex items-end justify-between gap-3">
        <div>
          <Eyebrow n="03">things i’ve been reading</Eyebrow>
          <h3 className="mt-1 text-2xl text-olive">recent pages</h3>
        </div>
        <button
          type="button"
          onClick={() => navigate('reading')}
          className="text-xs font-semibold text-olive underline decoration-olive/30 underline-offset-4 hover:decoration-olive"
        >
          see all
        </button>
      </div>
      {readingsState.loading && !readings.length ? (
        <div className="mt-4 space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10 rounded-sm" />
          ))}
        </div>
      ) : readingsState.error && !readings.length ? (
        <ErrorState className="mt-4 rounded-sm" message={readingsState.error} onRetry={refreshReadings} />
      ) : !readings.length ? (
        <p className="mt-4 border-l-2 border-sage-deep pl-4 text-sm leading-relaxed text-olive/65">
          nothing saved yet. allow a website in the extension and read for a few seconds.
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {readings.slice(0, 5).map((r, i) => (
            <li key={r.id} className={cx(newIds.has(r.id) && 'animate-highlight')}>
              <a
                href={savedConversationLink({ ...r, type: 'reading' })}
                aria-label={`Open conversation: ${r.title}`}
                className={journalLinkClass}
              >
                <span className="font-display text-sm text-olive/50 tabular-nums"><MathText>{String(i + 1).padStart(2, '0')}</MathText></span>
                <span className="min-w-0">
                  <span className="block truncate text-sm text-olive group-hover:underline group-hover:underline-offset-4">
                    {r.title}
                  </span>
                  <span className="block truncate text-xs text-olive/55">
                    {domainOf(r.url)} · {timeAgo(r.timestamp, now)}
                  </span>
                </span>
                <span className="flex items-center gap-1 text-xs text-olive/70 tabular-nums">
                  {formatDuration(r.durationSec)}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function Dashboard() {
  return (
    <div className="space-y-10">
      <Welcome />
      <StatusLedger />
      <Notebook />
      <div className="grid gap-10 border-t border-olive/70 pt-8 lg:grid-cols-2 lg:gap-16">
        <Journal />
        <ReadingList />
      </div>
    </div>
  )
}
