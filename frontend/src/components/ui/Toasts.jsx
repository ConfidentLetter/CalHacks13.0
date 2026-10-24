import { CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { useApp } from '../../context/contexts'
import { cx } from '../../utils/format'

const ICONS = { success: CheckCircle2, error: XCircle, info: Info }
const TONES = {
  success: 'text-sage-ink',
  error: 'text-clay',
  info: 'text-sage-ink',
}

export function Toasts() {
  const { toasts, dismissToast } = useApp()
  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4 sm:right-6 sm:left-auto sm:items-end"
      aria-live="polite"
      role="status"
    >
      {toasts.map((t) => {
        const Icon = ICONS[t.tone] || Info
        return (
          <div
            key={t.id}
            className="glass animate-fade-up pointer-events-auto flex w-full max-w-sm items-start gap-3 bg-paper px-4 py-3 text-sm text-olive"
          >
            <Icon className={cx('mt-0.5 size-4 shrink-0', TONES[t.tone])} aria-hidden="true" />
            <p className="flex-1">{t.message}</p>
            <button
              type="button"
              onClick={() => dismissToast(t.id)}
              className="rounded text-olive/55 hover:text-olive"
              aria-label="Dismiss notification"
            >
              <X className="size-4" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
