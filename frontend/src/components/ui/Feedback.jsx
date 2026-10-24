import { AlertTriangle, RotateCw } from 'lucide-react'
import { Button } from './Button'
import { cx } from '../../utils/format'

export function EmptyState({ icon: Icon, title, description, action, className }) {
  return (
    <div className={cx('flex flex-col items-center justify-center px-6 py-10 text-center', className)}>
      {Icon && (
        <span className="mb-3 grid size-12 place-items-center rounded-2xl border border-olive/12 bg-olive/5 text-olive/65">
          <Icon className="size-5" aria-hidden="true" />
        </span>
      )}
      <p className="text-sm font-medium text-olive">{title}</p>
      {description && <p className="mt-1 max-w-sm text-xs leading-relaxed text-olive/65">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({ message, onRetry, className }) {
  return (
    <div
      role="alert"
      className={cx(
        'flex items-start gap-3 rounded-sm border border-clay/40 bg-clay/10 p-3.5 text-sm text-clay',
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-clay" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="break-words">{message}</p>
      </div>
      {onRetry && (
        <Button size="sm" variant="ghost" icon={RotateCw} onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  )
}

export function Skeleton({ className }) {
  return <div className={cx('skeleton', className)} aria-hidden="true" />
}

export function LoadingDots({ label = 'Loading' }) {
  return (
    <span className="inline-flex items-center gap-1" role="status" aria-label={label}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="size-1.5 animate-bounce rounded-full bg-butter"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  )
}
