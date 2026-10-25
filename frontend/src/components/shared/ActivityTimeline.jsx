import { EmptyState } from '../ui/Feedback'
import { useNow } from '../../hooks/useInterval'
import { cx, domainOf, formatDuration, timeAgo } from '../../utils/format'

const TYPES = {
  reading: { color: 'text-sage-ink bg-sage/50 border-sage-deep' },
  snapshot: { color: 'text-honey bg-butter/50 border-butter-deep' },
  camera: { color: 'text-olive/80 bg-olive/8 border-olive/20' },
  analysis: { color: 'text-honey bg-butter/50 border-butter-deep' },
  chat: { color: 'text-sage-ink bg-sage/50 border-sage-deep' },
}

export function ActivityTimeline({ items, limit = 8 }) {
  const now = useNow()
  if (!items.length) {
    return (
      <EmptyState
        title="all quiet for now"
        description="captures, questions and reading sessions will show up here as you study."
      />
    )
  }
  return (
    <ol className="relative space-y-1">
      {items.slice(0, limit).map((e) => {
        const t = TYPES[e.type] || TYPES.camera
        return (
          <li key={e.id} className="relative flex gap-3 pb-3">
            <span className={cx('mt-0.5 h-fit shrink-0 rounded-sm border px-2 py-1 text-[10px] font-semibold uppercase', t.color)}>
              {e.type}
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex items-baseline justify-between gap-3">
                <p className="truncate text-sm text-olive">{e.title}</p>
                <time className="shrink-0 text-[11px] text-olive/55 tabular-nums" dateTime={e.at}>
                  {timeAgo(e.at, now)}
                </time>
              </div>
              <p className="truncate text-xs text-olive/55">
                {e.type === 'reading'
                  ? `${domainOf(e.detail)} · read ${formatDuration(e.durationSec)}`
                  : e.detail}
              </p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
