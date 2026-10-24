import { AlertCircle, CheckCircle2, HelpCircle, Scissors, Type } from 'lucide-react'
import { cx } from '../../utils/format'
import { TONE_LABEL } from './twinModel'

const TONE = {
  correct: { icon: CheckCircle2, cls: 'border-sage-deep bg-sage/60 text-sage-ink' },
  error: { icon: AlertCircle, cls: 'border-ink-red bg-ink-red text-cream' },
  crossed: { icon: Scissors, cls: 'border-olive/40 bg-paper text-olive/80' },
  unclear: { icon: HelpCircle, cls: 'border-dashed border-olive/50 bg-white text-olive/80' },
  read: { icon: Type, cls: 'border-olive/25 bg-white text-olive/70' },
}

/** correct / error / unclear / crossed out / read — same vocabulary on the twin, the ledger and the inspector. */
export function StatusChip({ tone, size = 'md', className }) {
  const t = TONE[tone] || TONE.read
  const Icon = t.icon
  return (
    <span
      className={cx(
        'inline-flex shrink-0 items-center gap-1 rounded-sm border font-bold tracking-wider uppercase whitespace-nowrap',
        size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-[11px]',
        t.cls,
        className,
      )}
    >
      <Icon className={size === 'sm' ? 'size-3' : 'size-3.5'} aria-hidden="true" />
      {TONE_LABEL[tone] || tone}
    </span>
  )
}
