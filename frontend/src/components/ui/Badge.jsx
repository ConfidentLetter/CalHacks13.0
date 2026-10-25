import { cx } from '../../utils/format'

const TONES = {
  neutral: 'bg-olive/12 text-olive/80 border-olive/14',
  violet: 'bg-butter/50 text-honey border-butter-deep',
  blue: 'bg-sage/50 text-sage-ink border-sage-deep',
  green: 'bg-sage/50 text-sage-ink border-sage-deep',
  amber: 'bg-butter/60 text-honey border-butter-deep',
  red: 'bg-clay/10 text-clay border-clay/40',
}

export function Badge({ tone = 'neutral', icon: _icon, className, children }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

const DOT = {
  online: 'bg-sage-deep text-sage-ink',
  active: 'bg-butter-deep text-honey',
  warning: 'bg-honey text-honey',
  offline: 'bg-clay text-clay',
  idle: 'bg-olive/30 text-olive/55',
}

export function StatusDot({ state = 'idle', pulse = false, label }) {
  return (
    <span className="relative inline-flex size-2.5 shrink-0" role={label ? 'img' : undefined} aria-label={label}>
      {pulse && <span className={cx('absolute inset-0 status-pulse rounded-full', DOT[state])} />}
      <span className={cx('relative inline-flex size-2.5 rounded-full', DOT[state])} />
    </span>
  )
}
