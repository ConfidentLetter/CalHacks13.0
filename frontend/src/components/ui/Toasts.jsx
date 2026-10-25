import { useApp } from '../../context/contexts'
import { cx } from '../../utils/format'

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
        return (
          <div
            key={t.id}
            className="glass animate-fade-up pointer-events-auto rounded-sm flex w-full max-w-sm items-start gap-3 bg-paper px-4 py-3 text-sm text-olive"
          >
            <span className={cx('mt-0.5 text-xs font-semibold capitalize', TONES[t.tone])}>{t.tone || 'info'}</span>
            <p className="flex-1">{t.message}</p>
            <button
              type="button"
              onClick={() => dismissToast(t.id)}
              className="rounded text-olive/55 hover:text-olive"
              aria-label="Dismiss notification"
            >
              Dismiss
            </button>
          </div>
        )
      })}
    </div>
  )
}
