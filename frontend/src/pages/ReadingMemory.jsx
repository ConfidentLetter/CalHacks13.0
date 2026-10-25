import { useMemo, useState } from 'react'
import { useApp, useStudyData } from '../context/contexts'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge, StatusDot } from '../components/ui/Badge'
import { Segmented } from '../components/ui/Controls'
import { EmptyState, ErrorState, Skeleton } from '../components/ui/Feedback'
import { ConfirmDialog, Modal } from '../components/ui/Modal'
import { useNow } from '../hooks/useInterval'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { useConnection } from '../hooks/useConnection'
import * as api from '../services/api'
import { cx, domainOf, formatDateTime, formatDuration, isToday, timeAgo } from '../utils/format'

const RANGES = [
  { value: 'all', label: 'All' },
  { value: 'today', label: 'Today' },
  { value: 'week', label: '7 days' },
]
const SORTS = [
  { value: 'recent', label: 'Recent' },
  { value: 'longest', label: 'Longest' },
]

const SOURCE_BADGE = {
  extension: { tone: 'blue', label: 'Extension · local' },
  backend: { tone: 'green', label: 'Synced' },
  manual: { tone: 'violet', label: 'Manual' },
}

function SourceBadge({ source }) {
  const b = SOURCE_BADGE[source] || SOURCE_BADGE.backend
  return <Badge tone={b.tone}>{b.label}</Badge>
}

function ReadingDetail({ record, onDelete, onClose }) {
  const { askTutor } = useApp()
  if (!record) {
    return (
      <EmptyState
        title="Select a page"
        description="Choose a reading session to see its details, captured text, and actions."
        className="h-full"
      />
    )
  }
  return (
    <div className="animate-fade-up space-y-5 p-5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-base leading-snug font-semibold text-olive">{record.title}</h3>
          <a
            href={record.url}
            target="_blank"
            rel="noreferrer noopener"
            className="mt-0.5 block truncate text-xs text-sage-ink hover:underline"
          >
            {record.url}
          </a>
        </div>
        {onClose && <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close details" />}
      </div>

      <dl className="grid grid-cols-3 gap-2">
        {[
          ['Read for', formatDuration(record.durationSec)],
          ['When', formatDateTime(record.timestamp)],
          ['Domain', domainOf(record.url)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-sm border border-olive/8 bg-olive/4 p-3">
            <dt className="text-[11px] text-olive/55">{k}</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-olive">{v}</dd>
          </div>
        ))}
      </dl>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="text-xs font-medium text-olive/65">Captured text</p>
          <SourceBadge source={record.source} />
        </div>
        {record.excerpt ? (
          <p className="max-h-64 overflow-y-auto rounded-sm border border-olive/8 bg-paper p-4 text-sm leading-relaxed whitespace-pre-line text-olive/80">
            {record.excerpt}
          </p>
        ) : (
          <p className="rounded-sm border border-dashed border-olive/20 p-4 text-xs leading-relaxed text-olive/55">
            No page text stored for this session. Only the title, URL and reading time were saved — either text sharing is
            off, or the page (e.g. a PDF) didn’t expose readable text.
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          onClick={() => askTutor(`Summarize the key ideas from "${record.title}" and quiz me on them.`)}
        >
          Ask tutor about this
        </Button>
        <a
          href={record.url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex h-10 items-center gap-2 rounded-sm border border-olive/14 bg-olive/12 px-4 text-sm font-medium text-olive transition hover:bg-olive/16"
        >
          Open page
        </a>
        <Button variant="danger" onClick={() => onDelete(record)}>
          Delete
        </Button>
      </div>
    </div>
  )
}

function AddPageModal({ open, onClose, onSaved }) {
  const { notify } = useApp()
  const [form, setForm] = useState({ title: '', url: '', minutes: 5 })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const valid = /^https?:\/\/\S+\.\S+/.test(form.url)

  const save = async (e) => {
    e.preventDefault()
    if (!valid) return
    setSaving(true)
    setError(null)
    try {
      await api.saveReading({
        title: form.title.trim() || domainOf(form.url),
        url: form.url.trim(),
        durationSec: Math.max(0, Number(form.minutes) || 0) * 60,
        timestamp: new Date().toISOString(),
        excerpt: '',
        source: 'manual',
      })
      notify('Page saved', 'success')
      setForm({ title: '', url: '', minutes: 5 })
      onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Add a page manually">
      <form onSubmit={save} className="space-y-4 p-5">
        <div>
          <label htmlFor="add-url" className="mb-1.5 block text-xs font-medium text-olive/80">
            URL
          </label>
          <input
            id="add-url"
            className="input"
            placeholder="https://…"
            value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
            required
          />
        </div>
        <div>
          <label htmlFor="add-title" className="mb-1.5 block text-xs font-medium text-olive/80">
            Title <span className="text-olive/55">(optional)</span>
          </label>
          <input
            id="add-title"
            className="input"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
        </div>
        <div>
          <label htmlFor="add-min" className="mb-1.5 block text-xs font-medium text-olive/80">
            Minutes read
          </label>
          <input
            id="add-min"
            type="number"
            min="0"
            max="600"
            className="input w-32"
            value={form.minutes}
            onChange={(e) => setForm({ ...form, minutes: e.target.value })}
          />
        </div>
        {error && <ErrorState message={error} />}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={saving} disabled={!valid}>
            Save page
          </Button>
        </div>
      </form>
    </Modal>
  )
}

export function ReadingMemory() {
  const { readings, readingsState, refreshReadings, newIds, deleteReading, extension } = useStudyData()
  const conn = useConnection()
  const now = useNow()
  const isWide = useMediaQuery('(min-width: 1024px)')

  const [query, setQuery] = useState('')
  const [range, setRange] = useState('all')
  const [sort, setSort] = useState('recent')
  const [selectedId, setSelectedId] = useState(null)
  const [pendingDelete, setPendingDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [adding, setAdding] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const weekAgo = now - 7 * 86_400_000
    let list = readings.filter((r) => {
      if (range === 'today' && !isToday(r.timestamp)) return false
      if (range === 'week' && new Date(r.timestamp).getTime() < weekAgo) return false
      if (!q) return true
      return `${r.title} ${r.url} ${r.excerpt}`.toLowerCase().includes(q)
    })
    if (sort === 'longest') list = [...list].sort((a, b) => b.durationSec - a.durationSec)
    return list
  }, [readings, query, range, sort, now])

  const selected = readings.find((r) => r.id === selectedId) || null
  const totalSec = filtered.reduce((a, r) => a + r.durationSec, 0)
  const live = extension.connected || conn.backend === 'online'

  const refresh = async () => {
    setRefreshing(true)
    await refreshReadings()
    setRefreshing(false)
  }

  const confirmDelete = async () => {
    setDeleting(true)
    const ok = await deleteReading(pendingDelete)
    setDeleting(false)
    if (ok && selectedId === pendingDelete.id) setSelectedId(null)
    setPendingDelete(null)
  }

  return (
    <div className="space-y-5">
      <div className="border-b border-olive/70 pb-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search titles, URLs, and captured text…"
              aria-label="Search reading history"
              className="input"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Segmented label="Time range" size="sm" value={range} onChange={setRange} options={RANGES} />
            <Segmented label="Sort" size="sm" value={sort} onChange={setSort} options={SORTS} />
            <Button size="icon" variant="ghost" loading={refreshing} onClick={refresh} aria-label="Refresh history" />
            <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
              Add page
            </Button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-olive/65">
          <span className="flex items-center gap-1.5">
            <StatusDot state={live ? 'online' : 'idle'} pulse={live} />
            {extension.connected ? 'Live from extension' : conn.backend === 'online' ? 'Live from backend' : 'Not live — backend and extension not connected'}
          </span>
          <span className="tabular-nums">
            {filtered.length} page{filtered.length === 1 ? '' : 's'} · {formatDuration(totalSec)} total
          </span>
        </div>
      </div>

      <div className="grid gap-10 lg:grid-cols-[1.2fr_1fr]">
        <div>
          {readingsState.loading && !readings.length ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          ) : readingsState.error && !readings.length ? (
            <div className="p-4">
              <ErrorState message={readingsState.error} onRetry={refresh} />
            </div>
          ) : !readings.length ? (
            <EmptyState
              title="Your reading memory is empty"
              description="Install the StudBud extension, allow a website, and read for a few seconds. Pages appear here automatically."
              className="py-16"
            />
          ) : !filtered.length ? (
            <EmptyState
              title="No matching pages"
              description="Try a different search or time range."
              action={
                <Button
                  size="sm"
                  onClick={() => {
                    setQuery('')
                    setRange('all')
                  }}
                >
                  Clear filters
                </Button>
              }
              className="py-16"
            />
          ) : (
            <ul className="space-y-3" aria-label="Reading history">
              {filtered.map((r, i) => {
                const active = r.id === selectedId
                return (
                  <li
                    key={r.id}
                    className={cx(
                      'group relative flex items-stretch border bg-white transition',
                      active ? 'border-olive shadow-[4px_4px_0_0_var(--color-olive)]' : 'border-olive/25 hover:border-olive/60',
                      newIds.has(r.id) && 'animate-highlight',
                    )}
                  >
                    {/* bookmark ribbon */}
                    <span
                      aria-hidden="true"
                      className={cx(
                        'relative w-3 shrink-0 [clip-path:polygon(0_0,100%_0,100%_100%,50%_82%,0_100%)]',
                        i % 3 === 0 ? 'bg-butter-deep' : i % 3 === 1 ? 'bg-sage-deep' : 'bg-paper-deep',
                      )}
                    />
                    <button
                      type="button"
                      onClick={() => setSelectedId(r.id)}
                      aria-pressed={active}
                      className="flex min-w-0 flex-1 items-start gap-4 px-4 py-3 text-left"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-[10px] font-bold tracking-[0.18em] text-olive/55 uppercase">
                          {domainOf(r.url)}
                          {newIds.has(r.id) && <span className="ml-2 bg-butter px-1 text-olive">new</span>}
                        </p>
                        <p className="mt-0.5 line-clamp-2 font-display text-base leading-snug text-olive">{r.title}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="font-display text-lg leading-none text-olive tabular-nums">{formatDuration(r.durationSec)}</p>
                        <p className="mt-1 text-[11px] text-olive/55">{timeAgo(r.timestamp, now)}</p>
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => setPendingDelete(r)}
                      aria-label={`Delete ${r.title}`}
                      className="shrink-0 border-l border-dotted border-olive/30 px-3 text-xs font-semibold text-olive/50 transition hover:bg-clay/10 hover:text-clay lg:opacity-0 lg:group-hover:opacity-100 lg:focus-visible:opacity-100"
                    >
                      remove
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        {isWide && (
          <Card className="sheet sticky top-24 hidden self-start lg:block">
            <ReadingDetail record={selected} onDelete={setPendingDelete} />
          </Card>
        )}
      </div>

      {!isWide && (
        <Modal open={Boolean(selected)} onClose={() => setSelectedId(null)} title="Reading details">
          <ReadingDetail record={selected} onDelete={setPendingDelete} />
        </Modal>
      )}

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
        loading={deleting}
        title="Delete reading record?"
        message={`“${pendingDelete?.title}” and any captured text will be removed${pendingDelete?.source === 'extension' ? ' from the extension’s local storage' : ''}. This can’t be undone.`}
        confirmLabel="Delete"
      />

      <AddPageModal open={adding} onClose={() => setAdding(false)} onSaved={refreshReadings} />
    </div>
  )
}
