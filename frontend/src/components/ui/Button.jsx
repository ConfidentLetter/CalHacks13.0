import { MathContent } from '../shared/MathTextRenderer'
import { Loader2 } from 'lucide-react'
import { cx } from '../../utils/format'

const VARIANTS = {
  primary:
    'bg-butter text-olive border border-butter-deep shadow-[0_2px_0_0_var(--color-butter-deep)] hover:bg-[#fbeab0] active:translate-y-px active:shadow-none',
  secondary:
    'bg-sage text-sage-ink border border-sage-deep shadow-[0_2px_0_0_var(--color-sage-deep)] hover:bg-[#d4e2c6] active:translate-y-px active:shadow-none',
  ghost: 'bg-paper text-olive border border-paper-deep hover:bg-paper-deep/60',
  danger: 'bg-white text-clay border border-clay/40 hover:bg-clay/10',
  success: 'bg-sage text-sage-ink border border-sage-deep hover:bg-[#d4e2c6]',
}

const SIZES = {
  sm: 'h-8 px-3 text-xs gap-1.5 rounded-sm',
  md: 'h-10 px-4 text-sm gap-2 rounded-sm',
  lg: 'h-12 px-5 text-sm gap-2 rounded-sm',
  icon: 'h-9 px-3 text-xs gap-2 rounded-sm justify-center',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  icon: _icon,
  loading = false,
  disabled,
  className,
  children,
  type = 'button',
  ...rest
}) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        'paper-button inline-flex shrink-0 items-center font-medium whitespace-nowrap select-none disabled:pointer-events-none disabled:opacity-45',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
      <MathContent>{children ?? rest['aria-label']}</MathContent>
    </button>
  )
}
