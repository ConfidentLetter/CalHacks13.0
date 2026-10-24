import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, BookOpenText, Bot, Camera, Eraser, RotateCw, Send, Sparkles, User } from 'lucide-react'
import { useApp, useStudyData } from '../context/contexts'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Toggle } from '../components/ui/Controls'
import { EmptyState, LoadingDots } from '../components/ui/Feedback'
import { ConfirmDialog, Modal } from '../components/ui/Modal'
import * as api from '../services/api'
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
        <BookOpenText className="size-3.5 shrink-0" aria-hidden="true" />
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
      <Camera className="size-3.5" aria-hidden="true" />
      {source.title || 'Notebook snapshot'}
      {source.capturedAt && <span className="text-honey/60">· {formatClock(source.capturedAt)}</span>}
    </button>
  )
}

function Message({ m, onRetry, onOpenSnapshot }) {
  const isUser = m.role === 'user'
  const isError = m.role === 'error'
  return (
    <div className={cx('animate-fade-up flex gap-3', isUser && 'flex-row-reverse')}>
      <span
        className={cx(
          'grid size-8 shrink-0 place-items-center rounded-xl border',
          isUser
            ? 'border-olive/20 bg-olive/12 text-olive/80'
            : isError
              ? 'border-clay/40 bg-clay/10 text-clay'
              : 'border-butter-deep bg-butter text-honey',
        )}
        aria-hidden="true"
      >
        {isUser ? <User className="size-4" /> : isError ? <AlertTriangle className="size-4" /> : <Bot className="size-4" />}
      </span>
      <div className={cx('flex max-w-[85%] min-w-0 flex-col gap-2 sm:max-w-[75%]', isUser && 'items-end')}>
        <div
          className={cx(
            'rounded-2xl px-4 py-3 text-sm leading-relaxed',
            isUser
              ? 'rounded-tr-md bg-butter text-olive'
              : isError
                ? 'rounded-tl-md border border-clay/40 bg-clay/10 text-clay'
                : 'rounded-tl-md border border-paper-deep bg-paper text-olive',
          )}
        >
          {m.content.split(/\n{2,}/).map((p, i) => (
            <p key={i} className={cx('whitespace-pre-line', i > 0 && 'mt-3')}>
              {p}
            </p>
          ))}
          {isError && onRetry && (
            <Button size="sm" variant="ghost" icon={RotateCw} className="mt-2 -ml-2 text-clay" onClick={() => onRetry(m)}>
              Try again
            </Button>
          )}
        </div>
        {m.sources?.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            <span className="self-center text-[11px] text-olive/55">Sources:</span>
            {m.sources.map((s, i) => (
              <SourceChip key={`${s.type}-${s.id}-${i}`} source={s} onOpenSnapshot={onOpenSnapshot} />
            ))}
          </div>
        )}
        <div className="flex items-center gap-2 text-[11px] text-olive/55">
          <time dateTime={m.at}>{formatClock(m.at)}</time>
        </div>
      </div>
    </div>
  )
}

export function AITutor() {
  const { tutorDraft, consumeTutorDraft, navigate, settings } = useApp()
  const { snapshot, readings, logEvent } = useStudyData()
  const [messages, setMessages] = useState(loadHistory)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [includeNotebook, setIncludeNotebook] = useState(true)
  const [includeReading, setIncludeReading] = useState(true)
  const [confirmClear, setConfirmClear] = useState(false)
  const [viewSnapshot, setViewSnapshot] = useState(null)
  const scroller = useRef(null)
  const textarea = useRef(null)
  const handledDraft = useRef(null)

  useEffect(() => saveHistory(messages), [messages])

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [messages, sending])

  const send = useCallback(
    async (text, priorMessages) => {
      const question = text.trim()
      if (!question) return
      const base = priorMessages ?? messages
      const userMsg = { id: uid(), role: 'user', content: question, at: new Date().toISOString() }
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
        textarea.current?.focus()
      }
    },
    [messages, includeNotebook, includeReading, settings.shareReadingTextWithTutor, logEvent],
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
      <Card className="flex h-[calc(100dvh-13rem)] min-h-[480px] flex-col overflow-hidden lg:h-[calc(100dvh-9.5rem)]">
        <div ref={scroller} className="flex-1 space-y-6 overflow-y-auto p-4 sm:p-6" aria-live="polite">
          {messages.length === 0 ? (
            <EmptyState
              icon={Sparkles}
              title="ask a little question"
              description="let’s work through it together — answers can use your latest notebook snapshot and the pages you’ve read."
              className="h-full"
              action={
                <div className="flex max-w-lg flex-wrap justify-center gap-2">
                  {SUGGESTIONS.slice(0, 4).map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => send(s)}
                      className="rounded-full border border-olive/14 bg-olive/5 px-3 py-1.5 text-xs text-olive/80 transition hover:border-butter-deep hover:bg-butter/50 hover:text-olive"
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
            <div className="flex items-center gap-3">
              <span className="grid size-8 place-items-center rounded-xl border border-butter-deep bg-butter text-honey">
                <Bot className="size-4" aria-hidden="true" />
              </span>
              <div className="rounded-2xl rounded-tl-md border border-olive/12 bg-olive/5 px-4 py-3">
                <LoadingDots label="Tutor is thinking" />
              </div>
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
          <div className="flex items-end gap-2 rounded-2xl border border-olive/14 bg-cream p-2 focus-within:border-butter-deep focus-within:ring-4 focus-within:ring-butter-deep">
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
            <Button type="submit" variant="primary" icon={Send} loading={sending} disabled={!input.trim()}>
              Send
            </Button>
          </div>
          <p className="mt-2 px-1 text-[11px] text-olive/55">enter to send · shift + enter for a new line</p>
        </form>
      </Card>

      <div className="space-y-5">
        <Card>
          <CardHeader title="Context" subtitle="What the tutor can see" />
          <CardBody className="space-y-4">
            <Toggle
              checked={includeNotebook}
              onChange={setIncludeNotebook}
              label="Notebook snapshots"
              description={snapshot.data ? `Latest frame at ${formatClock(snapshot.data.capturedAt)}` : 'No snapshot yet'}
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
                className="w-full rounded-xl px-3 py-2 text-left text-xs leading-relaxed text-olive transition hover:bg-white/60 disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </CardBody>
        </Card>

        <Button
          variant="ghost"
          icon={Eraser}
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
