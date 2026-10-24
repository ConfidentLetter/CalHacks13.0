import { cx } from '../../utils/format'

const BAR = {
  correct: 'bg-sage-deep',
  error: 'bg-ink-red',
  crossed: 'bg-olive/40',
  unclear: 'bg-butter-deep',
  read: 'bg-olive/60',
}

/** Thin bar + the number in tabular figures. Colour follows the line's tone, not the value. */
export function ConfidenceMeter({ value, tone = 'read', className }) {
  const v = Math.max(0, Math.min(1, Number(value) || 0))
  return (
    <span
      className={cx('inline-flex items-center gap-2', className)}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={v}
      aria-label={`confidence ${v.toFixed(2)}`}
    >
      <span className="relative h-1.5 w-16 overflow-hidden rounded-full bg-olive/12">
        <span className={cx('absolute inset-y-0 left-0 rounded-full', BAR[tone] || BAR.read)} style={{ width: `${v * 100}%` }} />
      </span>
      <span className="font-display text-[15px] text-olive tabular-nums">{v.toFixed(2).replace(/^0/, '')}</span>
    </span>
  )
}
