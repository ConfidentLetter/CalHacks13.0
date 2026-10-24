import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { Button } from './Button'
import { cx } from '../../utils/format'

/** Accessible dialog: Escape closes, focus moves in and returns on close. */
export function Modal({ open, onClose, title, children, footer, size = 'md' }) {
  const panel = useRef(null)
  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement
    const onKey = (e) => {
      if (e.key === 'Escape') closeRef.current()
      if (e.key === 'Tab' && panel.current) {
        const focusables = panel.current.querySelectorAll(
          'button:not([disabled]), a[href], input, textarea, select, [tabindex]:not([tabindex="-1"])',
        )
        if (!focusables.length) return
        const first = focusables[0]
        const last = focusables[focusables.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    panel.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      previous?.focus?.()
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6">
      <div className="absolute inset-0 bg-olive/35" onClick={onClose} aria-hidden="true" />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={cx(
          'glass animate-fade-up relative flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-b-none bg-cream outline-none sm:rounded-sm',
          size === 'lg' ? 'sm:max-w-4xl' : 'sm:max-w-lg',
        )}
      >
        <div className="flex items-center justify-between gap-4 border-b border-olive/12 px-5 py-4">
          <h2 className="truncate text-sm font-semibold text-olive">{title}</h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close dialog" icon={X} />
        </div>
        <div className="overflow-y-auto">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-olive/12 px-5 py-4">{footer}</div>
        )}
      </div>
    </div>,
    document.body,
  )
}

export function ConfirmDialog({ open, onCancel, onConfirm, title, message, confirmLabel = 'Confirm', loading }) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="px-5 py-4 text-sm leading-relaxed text-olive/80">{message}</p>
    </Modal>
  )
}
