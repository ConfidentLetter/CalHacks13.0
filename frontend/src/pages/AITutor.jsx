import { useCallback, useEffect, useRef, useState } from 'react'
import { useApp, useCamera, useStudyData } from '../context/contexts'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Toggle } from '../components/ui/Controls'
import { EmptyState, LoadingDots } from '../components/ui/Feedback'
import { ConfirmDialog, Modal } from '../components/ui/Modal'
import { MathText } from '../components/shared/MathTextRenderer'
import * as api from '../services/api'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'
import { cx, formatClock, uid } from '../utils/format'

const HISTORY_KEY = 'synapse.chat.v2'
const CONTEXT_TURNS = 10

const SUGGESTIONS = [
  'Did I make a mistake in my latest notebook work?',
  'Explain integration by parts with an example',
  'How do I find acceleration on an incline with friction?',
  'Summarize what I read today in 3 bullet points',
  'Give me a practice problem like the one in my notebook',
]

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []
  } catch {
    return []
  }
}

function saveHistory(messages) {
  try {
    // Snapshot image data URLs can be large; keep only references in storage.
    const slim = messages.map((m) => ({
      ...m,
      frame: m.frame && { capturedAt: m.frame.capturedAt, source: m.frame.source },
      sources: m.sources?.map(({ imageUrl, ...s }) => ({ ...s, imageUrl: imageUrl?.startsWith('data:') ? undefined : imageUrl })),
    }))
    localStorage.setItem(HISTORY_KEY, JSON.stringify(slim.slice(-60)))
  } catch {
    /* ignore quota errors */
  }
}

function SourceChip({ source, onOpenSnapshot }) {
  if (source.type === 'reading') {
    return (
      <a
        href={source.url}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-sage-deep bg-sage/50 px-2.5 py-1 text-xs text-sage-ink transition hover:bg-sage/50"
      >
        <span className="truncate">{source.title}</span>
      </a>
    )
  }
  return (
    <button
      type="button"
      onClick={() => onOpenSnapshot(source)}
      className="inline-flex items-center gap-1.5 rounded-lg border border-butter-deep bg-butter/50 px-2.5 py-1 text-xs text-honey transition hover:bg-butter/50"
    >
      {source.title || 'Notebook snapshot'}
      {source.capturedAt && <span className="text-honey/60">· {formatClock(source.capturedAt)}</span>}
    </button>
  )
}

function Message({ m, onRetry, onOpenSnapshot }) {
  const isUser = m.role === 'user'
  const isError = m.role === 'error'
  return (
    <div className={cx('animate-fade-up flex', isUser ? 'justify-end' : 'justify-start')}>
      <div className={cx('flex max-w-[88%] min-w-0 flex-col gap-1.5 sm:max-w-[72%]', isUser && 'items-end')}>
        <p className="text-[10px] font-bold tracking-[0.18em] text-olive/50 uppercase">
          {isUser ? 'you' : isError ? 'couldn’t answer' : 'pip'} · <time dateTime={m.at}>{formatClock(m.at)}</time>
        </p>
        <div
          className={cx(
            'text-sm',
            isUser
              ? 'sticky-note rotate-[0.6deg] px-4 py-3 leading-relaxed motion-reduce:rotate-0'
              : isError
                ? 'border-l-2 border-clay py-1 pl-4 leading-7 text-clay'
                : 'border-l-2 border-sage-deep py-1 pl-4 leading-7 text-olive',
          )}
        >
          {m.content.split(/\n{2,}/).map((p, i) => (
            <p key={i} className={cx('whitespace-pre-line', i > 0 && 'mt-3')}>
              <MathText>{p}</MathText>
            </p>
          ))}
          {isError && onRetry && (
            <Button size="sm" variant="ghost" className="mt-2" onClick={() => onRetry(m)}>
              Try again
            </Button>
          )}
        </div>
        {m.frame && (
          <figure className="w-40 border border-olive/40 bg-white p-1">
            {m.frame.previewUrl && <img src={m.frame.previewUrl} alt="Still sent with this question" className="w-full" />}
            <figcaption className="px-0.5 pt-1 text-[10px] text-olive/60">
              still sent to Pip · {formatClock(m.frame.capturedAt)}
            </figcaption>
          </figure>
        )}
        {m.sources?.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pl-4">
            <span className="self-center text-[11px] text-olive/55">from:</span>
            {m.sources.map((s, i) => (
              <SourceChip key={`${s.type}-${s.id}-${i}`} source={s} onOpenSnapshot={onOpenSnapshot} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function AITutor() {
  const { tutorDraft, consumeTutorDraft, navigate, settings } = useApp()
  const { readings, logEvent, setLastFrame } = useStudyData()
  const camera = useCamera()
  const [sendingFrame, setSendingFrame] = useState(null)
  const [messages, setMessages] = useState(loadHistory)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [includeNotebook, setIncludeNotebook] = useState(true)
  const [includeReading, setIncludeReading] = useState(true)
  const [confirmClear, setConfirmClear] = useState(false)
  const [viewSnapshot, setViewSnapshot] = useState(null)
  const scroller = useRef(null)
  const textarea = useRef(null)
  // Voice input: finished phrases are appended to the box so they can be edited before sending.
  const voice = useSpeechRecognition({
    onFinal: (text) => setInput((prev) => (prev.trim() ? `${prev.trimEnd()} ${text}` : text)),
  })
  const stopVoice = voice.stop
  const handledDraft = useRef(null)

  useEffect(() => saveHistory(messages), [messages])

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [messages, sending])

  const send = useCallback(
    async (text, priorMessages) => {
      const question = text.trim()
      if (!question) return
      stopVoice()
      const base = priorMessages ?? messages
      // One fresh still from the live camera, taken right now — Pip never sees the video itself.
      let frame = null
      if (includeNotebook && camera.isLive) {
        try {
          frame = await camera.captureFrame()
        } catch {
          frame = null // answer without the page rather than fail the question
        }
      }
      if (frame) setLastFrame(frame)
      setSendingFrame(frame)
      const userMsg = {
        id: uid(),
        role: 'user',
        content: question,
        at: new Date().toISOString(),
        frame: frame && { previewUrl: frame.previewUrl, capturedAt: frame.capturedAt, source: frame.source },
      }
      setMessages([...base, userMsg])
      setInput('')
      setSending(true)
      logEvent('chat', 'Asked the tutor', question)
      try {
        const history = base
          .filter((m) => m.role !== 'error')
          .slice(-CONTEXT_TURNS)
          .map(({ role, content }) => ({ role, content }))
        const { data } = await api.sendChat({
          message: question,
          history,
          includeNotebook,
          includeReading,
          includeReadingText: settings.shareReadingTextWithTutor,
          frame,
        })
        setMessages((prev) => [
          ...prev,
          {
            id: uid(),
            role: 'assistant',
            content: data.reply || '(The tutor returned an empty response.)',
            sources: data.sources || [],
            at: new Date().toISOString(),
          },
        ])
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          {
            id: uid(),
            role: 'error',
            content: `I couldn’t get an answer: ${err.message}`,
            question,
            at: new Date().toISOString(),
          },
        ])
      } finally {
        setSending(false)
        setSendingFrame(null)
        textarea.current?.focus()
      }
    },
    [messages, includeNotebook, includeReading, settings.shareReadingTextWithTutor, logEvent, stopVoice, camera, setLastFrame],
  )

  // Questions handed over from Quick Ask / other pages.
  useEffect(() => {
    if (!tutorDraft || handledDraft.current === tutorDraft.at || sending) return
    handledDraft.current = tutorDraft.at
    consumeTutorDraft()
    send(tutorDraft.question)
  }, [tutorDraft, consumeTutorDraft, send, sending])

  const retry = (errMsg) => {
    // Drop the failed exchange (user question + error) and ask again.
    const idx = messages.findIndex((m) => m.id === errMsg.id)
    send(errMsg.question, messages.slice(0, Math.max(0, idx - 1)))
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      if (!sending) send(input)
    }
  }

  const openSnapshot = (source) => {
    if (source.imageUrl) setViewSnapshot(source)
    else navigate('notebook')
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_300px]">
      <Card className="sheet flex h-[calc(100dvh-13rem)] min-h-[480px] flex-col overflow-hidden lg:h-[calc(100dvh-9.5rem)]">
        <div ref={scroller} className="ruled relative flex-1 space-y-7 overflow-y-auto bg-white py-6 pr-4 pl-8 sm:pr-8 sm:pl-14" aria-live="polite">
          <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-4 w-px bg-clay/30 sm:left-9" />
          {messages.length === 0 ? (
            <EmptyState
              title="ask a little question"
              description="let’s work through it together — with the camera on, Pip gets one still of your page when you send."
              className="h-full"
              action={
                <div className="flex max-w-lg flex-wrap justify-center gap-2">
                  {SUGGESTIONS.slice(0, 4).map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => send(s)}
                      className="rounded-sm border border-olive/25 bg-white px-3 py-1.5 text-xs text-olive/80 transition hover:border-butter-deep hover:bg-butter/50 hover:text-olive"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              }
            />
          ) : (
            messages.map((m) => <Message key={m.id} m={m} onRetry={sending ? null : retry} onOpenSnapshot={openSnapshot} />)
          )}
          {sending && (
            <div className="flex items-center gap-3 border-l-2 border-sage-deep py-1 pl-4 text-xs text-olive/60">
              <LoadingDots label="Pip is thinking" />{' '}
              {sendingFrame ? `Analyzing your page… (still from ${formatClock(sendingFrame.capturedAt)})` : 'thinking it through…'}
            </div>
          )}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            send(input)
          }}
          className="border-t border-olive/12 bg-paper p-3 sm:p-4"
        >
          <div className="flex items-end gap-2 rounded-sm border border-olive/14 bg-white p-2 focus-within:border-butter-deep focus-within:ring-4 focus-within:ring-butter-deep">
            <label htmlFor="tutor-input" className="sr-only">
              Message the AI tutor
            </label>
            <textarea
              id="tutor-input"
              ref={textarea}
              rows={1}
              value={input}
              onChange={(e) => {
                setInput(e.target.value)
                e.target.style.height = 'auto'
                e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`
              }}
              onKeyDown={onKeyDown}
              placeholder="Ask about your notes, a concept, or what you read…"
              className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-olive outline-none placeholder:text-olive/55"
            />
            <Button
              variant={voice.listening ? 'danger' : 'ghost'}
              size="icon"
              onClick={voice.listening ? voice.stop : voice.start}
              disabled={!voice.supported}
              aria-pressed={voice.listening}
              aria-label={voice.listening ? 'Stop voice input' : 'Start voice input'}
              title={voice.supported ? undefined : 'Voice input isn’t supported in this browser — try Chrome or Edge'}
              className={cx('h-10', voice.listening && 'animate-pulse')}
            >
              {voice.listening ? 'Stop mic' : 'Mic'}
            </Button>
            <Button type="submit" variant="primary" loading={sending} disabled={!input.trim()}>
              Send
            </Button>
          </div>
          {voice.listening && (
            <p className="mt-2 flex items-center gap-2 px-1 text-xs text-clay" role="status">
              <span className="size-2 animate-pulse rounded-full bg-clay" aria-hidden="true" />
              listening… {voice.interim && <span className="truncate text-olive/65 italic">“{voice.interim}”</span>}
            </p>
          )}
          {voice.error && (
            <p className="mt-2 px-1 text-xs text-clay" role="alert">
              {voice.error}
            </p>
          )}
          <p className="mt-2 px-1 text-[11px] text-olive/55">
            enter to send · shift + enter for a new line
            {voice.supported ? ' · mic turns speech into text (audio is never saved)' : ' · voice input not supported in this browser'}
          </p>
        </form>
      </Card>

      <div className="space-y-5">
        <Card className="border-0 bg-transparent">
          <CardHeader title="What the tutor can see" className="border-olive/70 px-0" />
          <CardBody className="space-y-4 px-0">
            <Toggle
              checked={includeNotebook}
              onChange={setIncludeNotebook}
              label="My notebook page"
              description={
                camera.isLive
                  ? 'Camera live — one still is captured when you send'
                  : 'Camera off — start it in “peek at my notebook”'
              }
            />
            <Toggle
              checked={includeReading}
              onChange={setIncludeReading}
              label="Reading history"
              description={`${readings.length} tracked page${readings.length === 1 ? '' : 's'}${
                settings.shareReadingTextWithTutor ? ' · with text' : ' · titles & URLs only'
              }`}
            />
          </CardBody>
        </Card>

        <Card className="sticky-note rotate-1 motion-reduce:rotate-0">
          <CardHeader title="a few to get you started" />
          <CardBody className="space-y-1.5 pt-3">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                disabled={sending}
                onClick={() => send(s)}
                className="w-full rounded-sm px-3 py-2 text-left text-xs leading-relaxed text-olive transition hover:bg-white/60 disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </CardBody>
        </Card>

        <Button
          variant="ghost"
          className="w-full justify-center"
          disabled={!messages.length || sending}
          onClick={() => setConfirmClear(true)}
        >
          Clear conversation
        </Button>
      </div>

      <ConfirmDialog
        open={confirmClear}
        onCancel={() => setConfirmClear(false)}
        onConfirm={() => {
          setMessages([])
          setConfirmClear(false)
        }}
        title="Clear conversation?"
        message="This removes the chat history stored in this browser. Your notebook snapshots and reading history are not affected."
        confirmLabel="Clear"
      />

      <Modal open={Boolean(viewSnapshot)} onClose={() => setViewSnapshot(null)} title="Referenced notebook snapshot" size="lg">
        {viewSnapshot && <img src={viewSnapshot.imageUrl} alt="Referenced notebook snapshot" className="w-full bg-paper object-contain" />}
      </Modal>
    </div>
  )
}
