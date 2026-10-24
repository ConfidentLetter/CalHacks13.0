import { BookOpenText, Camera, MessageSquare, Sparkles, Video } from 'lucide-react'
import { EmptyState } from '../ui/Feedback'
import { useNow } from '../../hooks/useInterval'
import { cx, domainOf, formatDuration, timeAgo } from '../../utils/format'

const TYPES = {
  reading: { icon: BookOpenText, color: 'text-sage-ink bg-sage/50 border-sage-deep' },
  snapshot: { icon: Camera, color: 'text-honey bg-butter/50 border-butter-deep' },
  camera: { icon: Video, color: 'text-olive/80 bg-olive/8 border-olive/20' },
  analysis: { icon: Sparkles, color: 'text-honey bg-butter/50 border-butter-deep' },
  chat: { icon: MessageSquare, color: 'text-sage-ink bg-sage/50 border-sage-deep' },
}

export function ActivityTimeline({ items, limit = 8 }) {
  const now = useNow()
  if (!items.length) {
    return (
      <EmptyState
        icon={Sparkles}
        title="all quiet for now"
        description="captures, questions and reading sessions will show up here as you study."
      />
    )
  }
  return (
    <ol className="relative space-y-1">
      {items.slice(0, limit).map((e, i) => {
        const t = TYPES[e.type] || TYPES.camera
        const Icon = t.icon
        const last = i === Math.min(items.length, limit) - 1
        return (
          <li key={e.id} className="relative flex gap-3 pb-3">
            {!last && <span className="absolute top-8 bottom-0 left-[15px] w-px bg-olive/12" aria-hidden="true" />}
            <span className={cx('grid size-8 shrink-0 place-items-center rounded-lg border', t.color)}>
              <Icon className="size-3.5" aria-hidden="true" />
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
