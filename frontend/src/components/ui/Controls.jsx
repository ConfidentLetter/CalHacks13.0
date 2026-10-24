import { useId } from 'react'
import { cx } from '../../utils/format'

export function Toggle({ checked, onChange, label, description, disabled }) {
  const id = useId()
  return (
    <div className={cx('flex items-start justify-between gap-4', disabled && 'opacity-50')}>
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-olive">
          {label}
        </label>
        {description && <p className="mt-0.5 text-xs leading-relaxed text-olive/65">{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx(
          'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition',
          checked ? 'border-butter-deep bg-butter' : 'border-olive/20 bg-olive/14',
        )}
      >
        <span
          className={cx(
            'inline-block size-4.5 rounded-full bg-white shadow transition-transform',
            checked ? 'translate-x-[22px]' : 'translate-x-[3px]',
          )}
        />
      </button>
    </div>
  )
}

/** Radio-group styled as a segmented control. Arrow keys move the selection. */
export function Segmented({ value, onChange, options, label, size = 'md', disabled }) {
  const onKeyDown = (e) => {
    const i = options.findIndex((o) => o.value === value)
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault()
      onChange(options[(i + 1) % options.length].value)
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault()
      onChange(options[(i - 1 + options.length) % options.length].value)
    }
  }
  return (
    <div
      role="radiogroup"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cx(
        'inline-flex rounded-xl border border-olive/14 bg-paper p-1',
        disabled && 'pointer-events-none opacity-50',
      )}
    >
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(o.value)}
            className={cx(
              'rounded-lg font-medium transition',
              size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3.5 py-1.5 text-sm',
              active ? 'bg-olive/16 text-olive shadow-sm' : 'text-olive/65 hover:text-olive',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
