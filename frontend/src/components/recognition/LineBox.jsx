import { cx } from '../../utils/format'
import { toneOf } from './twinModel'

const STROKE = {
  correct: 'border-2 border-sage-deep bg-sage/15',
  error: 'border-[3px] border-ink-red bg-ink-red/10',
  crossed: 'border-2 border-olive/50 hatch',
  unclear: 'border-2 border-dashed border-olive/40',
  read: 'border-2 border-olive/35',
}
const BADGE = {
  correct: 'bg-sage text-sage-ink border-sage-deep',
  error: 'bg-ink-red text-cream border-ink-red',
  crossed: 'bg-paper text-olive border-olive/40 line-through decoration-ink-red',
  unclear: 'bg-paper text-olive border-olive/40',
  read: 'bg-white text-olive border-olive/30',
}

/** One line box on the page twin, positioned in percentages of the dewarped image so it survives any resize. */
export function LineBox({ line, image, selected, hovered, compact, onSelect, onHover }) {
  const [x, y, w, h] = line.bbox
  const tone = toneOf(line)
  const style = {
    left: `${(x / image.width) * 100}%`,
    top: `${(y / image.height) * 100}%`,
    width: `${(w / image.width) * 100}%`,
    height: `${(h / image.height) * 100}%`,
  }
  const label = `line ${line.order}: ${line.label || '(illegible)'} — ${tone}`
  if (compact) {
    return <span aria-hidden="true" className={cx('absolute rounded-[2px]', STROKE[tone])} style={style} />
  }
  return (
    <button
      type="button"
      style={style}
      aria-label={label}
      aria-pressed={selected}
      onClick={() => onSelect?.(line.id)}
      onMouseEnter={() => onHover?.(line.id)}
      onMouseLeave={() => onHover?.(null)}
      onFocus={() => onHover?.(line.id)}
      onBlur={() => onHover?.(null)}
      className={cx(
        'absolute rounded-[2px] transition-[box-shadow,background-color] duration-150 outline-none',
        STROKE[tone],
        (hovered || selected) && 'bg-butter/25',
        selected && 'shadow-[0_0_0_2px_var(--color-cream),0_0_0_5px_var(--color-butter-deep)]',
      )}
    >
      <span
        className={cx(
          'absolute top-0 right-[calc(100%+4px)] grid h-5 min-w-5 place-items-center border px-1 font-display text-[12px] leading-none tabular-nums shadow-[1px_1px_0_0_var(--color-olive)]',
          BADGE[tone],
        )}
      >
        {line.order}
      </span>
    </button>
  )
}
