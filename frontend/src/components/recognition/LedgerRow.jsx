import { MathText } from '../shared/MathTextRenderer'
import { useEffect, useRef } from 'react'
import { cx } from '../../utils/format'
import { Latex } from './Latex'
import { ConfidenceMeter } from './ConfidenceMeter'
import { StatusChip } from './StatusChip'
import { toneOf } from './twinModel'

const ROW_TONE = {
  error: 'bg-ink-red/[0.07] border-l-[3px] border-l-ink-red',
  correct: 'border-l-[3px] border-l-sage-deep',
  crossed: 'border-l-[3px] border-l-olive/30',
  unclear: 'border-l-[3px] border-l-dashed border-l-olive/35',
  read: 'border-l-[3px] border-l-transparent',
}

/** One line in reading order: number · verbatim LaTeX · confidence · status · tutor note. */
export function LedgerRow({ line, selected, hovered, onSelect, onHover }) {
  const ref = useRef(null)
  const tone = toneOf(line)
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selected])

  const empty = !line.label
  return (
    <li ref={ref} className={cx('transition-colors', ROW_TONE[tone], (hovered || selected) && 'bg-butter/30', selected && 'bg-butter/45')}>
      <button
        type="button"
        onClick={() => onSelect?.(line.id)}
        onMouseEnter={() => onHover?.(line.id)}
        onMouseLeave={() => onHover?.(null)}
        aria-pressed={selected}
        className="grid w-full grid-cols-[2.25rem_1fr_auto] items-start gap-x-3 px-3 py-2.5 text-left outline-none focus-visible:bg-butter/40"
      >
        <span className="pt-1 font-display text-[17px] leading-none text-olive/55 tabular-nums"><MathText>{String(line.order).padStart(2, '0')}</MathText></span>
        <span className="min-w-0">
          <span className={cx('block min-h-7 leading-7 text-olive', tone === 'crossed' && 'struck inline-block pr-1 opacity-80')}>
            {empty ? (
              <span className="text-[13px] tracking-wider text-olive/40 uppercase italic">illegible — no readable ink</span>
            ) : (
              <Latex value={line.label} kind={line.kind} />
            )}
          </span>
          {line.note && line.note.trim().toLowerCase() !== 'crossed out' && (
            <span className={cx('mt-1 block text-[14px] leading-relaxed', tone === 'error' ? 'text-ink-red' : 'text-olive/70')}><MathText>{line.note}</MathText></span>
          )}
        </span>
        <span className="flex flex-col items-end gap-1.5 pt-0.5">
          <StatusChip tone={tone} size="sm" />
          <ConfidenceMeter value={line.confidence} tone={tone} />
        </span>
      </button>
    </li>
  )
}
