import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, ChevronUp, Copy, X } from 'lucide-react'
import { Button } from '../ui/Button'
import { cx } from '../../utils/format'
import { Latex } from './Latex'
import { ConfidenceMeter } from './ConfidenceMeter'
import { StatusChip } from './StatusChip'
import { toneOf } from './twinModel'

function Label({ children }) {
  return <p className="text-[11px] font-bold tracking-[0.18em] text-olive/55 uppercase">{children}</p>
}

function Reading({ name, value, kind }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] items-baseline gap-2 border-b border-dotted border-olive/25 py-2 last:border-b-0">
      <span className="text-[12px] font-bold tracking-wider text-olive/55 uppercase">{name}</span>
      {value == null ? (
        <span className="text-sm text-olive/40 italic">not run</span>
      ) : value === '' ? (
        <span className="text-sm text-olive/40 italic">illegible</span>
      ) : (
        <Latex value={value} kind={kind} size="sm" />
      )}
    </div>
  )
}

function Crop({ src, alt, title }) {
  const [broken, setBroken] = useState(false)
  if (!src || broken) return null
  return (
    <figure className="min-w-0">
      <div className="border border-olive/40 bg-white p-1">
        <img src={src} alt={alt} onError={() => setBroken(true)} className="max-h-40 w-full object-contain" />
      </div>
      <figcaption className="mt-1 text-[12px] text-olive/55">{title}</figcaption>
    </figure>
  )
}

function CopyLatex({ value }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setDone(true)
      setTimeout(() => setDone(false), 1400)
    } catch {
      /* clipboard unavailable on plain-http LAN URLs; the text is still selectable */
    }
  }
  return (
    <Button size="sm" variant="ghost" icon={done ? Check : Copy} onClick={copy} aria-label="Copy raw LaTeX">
      {done ? 'copied' : 'copy'}
    </Button>
  )
}

/**
 * Side sheet for one line: crop, context crop, both readings with an agree/disagree mark, the re-read zoom and
 * candidates when present, and the raw LaTeX in a copyable code line. ↑/↓ move between lines, Esc closes.
 */
export function LineInspector({ line, total, onClose, onStep }) {
  useEffect(() => {
    if (!line) return
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowDown') {
        e.preventDefault()
        onStep(1)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        onStep(-1)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [line, onClose, onStep])

  if (!line) return null
  const tone = toneOf(line)
  const r = line.readings || {}
  const bothRead = r.page != null && r.line != null

  return createPortal(
    <div className="fixed inset-0 z-40 flex justify-end" role="presentation">
      <div className="absolute inset-0 bg-olive/20 lg:bg-transparent" onClick={onClose} aria-hidden="true" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`Line ${line.order} details`}
        className="slide-in-right sheet relative m-3 flex max-h-[calc(100dvh-1.5rem)] w-full max-w-[460px] flex-col overflow-hidden bg-cream sm:m-5"
      >
        <header className="flex items-start justify-between gap-3 border-b border-olive/70 px-5 py-4">
          <div className="min-w-0">
            <Label>line {String(line.order).padStart(2, '0')} of {total}</Label>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <StatusChip tone={tone} />
              <ConfidenceMeter value={line.confidence} tone={tone} />
              {line.lineStatus !== 'active' && <span className="text-[12px] text-olive/55">{line.lineStatus.replace('_', ' ')}</span>}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button size="icon" variant="ghost" icon={ChevronUp} onClick={() => onStep(-1)} aria-label="Previous line" />
            <Button size="icon" variant="ghost" icon={ChevronDown} onClick={() => onStep(1)} aria-label="Next line" />
            <Button size="icon" variant="ghost" icon={X} onClick={onClose} aria-label="Close line details" />
          </div>
        </header>

        <div className="space-y-6 overflow-y-auto px-5 py-5">
          <section>
            <Label>as written</Label>
            <div className={cx('ruled mt-2 min-h-14 border border-olive/30 bg-white px-3 py-3 text-xl leading-9', tone === 'crossed' && 'opacity-80')}>
              {line.label ? (
                <span className={cx(tone === 'crossed' && 'struck inline-block pr-1')}>
                  <Latex value={line.label} kind={line.kind} />
                </span>
              ) : (
                <span className="text-sm text-olive/40 italic">illegible — nothing transcribed</span>
              )}
            </div>
            {line.note && <p className={cx('mt-2 text-[15px] leading-relaxed', tone === 'error' ? 'text-ink-red' : 'text-olive/75')}>{line.note}</p>}
          </section>

          {(line.cropUrl || line.contextCropUrl) && (
            <section className="grid gap-3 sm:grid-cols-2">
              <Crop src={line.cropUrl} alt={`Crop of line ${line.order}`} title="the line, cropped" />
              <Crop src={line.contextCropUrl} alt={`Line ${line.order} with its neighbours`} title="with its neighbours (target outlined)" />
            </section>
          )}

          <section>
            <div className="flex items-center justify-between gap-3">
              <Label>two readings</Label>
              {bothRead && (
                <span
                  className={cx(
                    'inline-flex items-center gap-1 text-[12px] font-bold tracking-wider uppercase',
                    r.agree ? 'text-sage-ink' : 'text-ink-red',
                  )}
                >
                  {r.agree ? <Check className="size-3.5" aria-hidden="true" /> : <X className="size-3.5" aria-hidden="true" />}
                  {r.agree ? 'agree' : 'disagree'}
                </span>
              )}
            </div>
            <div className="mt-1">
              <Reading name="page pass" value={r.page} kind={line.kind} />
              <Reading name="line pass" value={r.line} kind={line.kind} />
              {(r.reread != null || line.reread) && <Reading name="re-read" value={r.reread ?? line.reread?.reading ?? null} kind={line.kind} />}
            </div>
            {r.notes?.length > 0 && <p className="mt-1 text-[12px] text-olive/50">{r.notes.join(' · ')}</p>}
          </section>

          {line.reread && (line.reread.zoomUrl || line.reread.candidates.length > 0) && (
            <section>
              <Label>re-read at 3× zoom</Label>
              <div className="mt-2 grid gap-3 sm:grid-cols-[1fr_1fr]">
                <Crop src={line.reread.zoomUrl} alt={`Zoomed crop of line ${line.order}`} title="zoomed crop" />
                {line.reread.candidates.length > 0 && (
                  <ul className="space-y-1.5 text-sm">
                    {line.reread.candidates.map((c) => (
                      <li
                        key={c.key}
                        className={cx(
                          'flex items-baseline gap-2 border-l-2 pl-2',
                          line.reread.choice === c.key ? 'border-butter-deep bg-butter/40' : 'border-olive/20',
                        )}
                      >
                        <span className="font-display text-olive/60">{c.key}</span>
                        <Latex value={c.value} size="sm" />
                        {line.reread.choice === c.key && <span className="ml-auto text-[11px] font-bold text-olive/60 uppercase">chosen</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          )}

          {line.uncertainSpans?.length > 0 && (
            <section>
              <Label>uncertain spans</Label>
              <ul className="mt-1 space-y-1 text-sm text-olive/75">
                {line.uncertainSpans.map((s, i) => (
                  <li key={i} className="font-mono text-[13px]">
                    chars {s.start}–{s.end}
                    {Array.isArray(s.alternatives) && s.alternatives.length > 0 && <> · alternatives: {s.alternatives.join(', ')}</>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <div className="flex items-center justify-between gap-3">
              <Label>raw latex</Label>
              {line.label && <CopyLatex value={line.label} />}
            </div>
            <pre className="mt-1 overflow-x-auto border border-olive/30 bg-white px-3 py-2 font-mono text-[13px] whitespace-pre-wrap break-all text-olive select-all">
              {line.label || '(empty)'}
            </pre>
          </section>
        </div>
      </aside>
    </div>,
    document.body,
  )
}
