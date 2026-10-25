import { cx } from '../../utils/format'
import { TONE_LABEL } from './twinModel'

const TONE = {
  correct: { cls: 'border-sage-deep bg-sage/60 text-sage-ink' },
  error: { cls: 'border-ink-red bg-ink-red text-cream' },
  crossed: { cls: 'border-olive/40 bg-paper text-olive/80' },
  unclear: { cls: 'border-dashed border-olive/50 bg-white text-olive/80' },
  read: { cls: 'border-olive/25 bg-white text-olive/70' },
}

/** correct / error / unclear / crossed out / read — same vocabulary on the twin, the ledger and the inspector. */
export function StatusChip({ tone, size = 'md', className }) {
  const t = TONE[tone] || TONE.read
  return (
    <span
      className={cx(
        'inline-flex shrink-0 items-center gap-1 rounded-sm border font-bold tracking-wider uppercase whitespace-nowrap',
        size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-[11px]',
        t.cls,
        className,
      )}
    >
      {TONE_LABEL[tone] || tone}
    </span>
  )
}
