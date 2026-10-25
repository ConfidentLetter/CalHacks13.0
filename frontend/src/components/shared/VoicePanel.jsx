import { useState } from 'react'
import { useApp, useCamera } from '../../context/contexts'
import { useVoiceTutor } from '../../hooks/useVoiceTutor'
import { MAX_RECORDING_SEC } from '../../hooks/useRecorder'
import { Button } from '../ui/Button'
import { MathText } from './MathTextRenderer'
import { Toggle } from '../ui/Controls'
import { PipPet } from './PipPet'
import { cx, formatClock } from '../../utils/format'

const STEPS = [
  ['ready', 'Ready'],
  ['listening', 'Listening'],
  ['sending', 'Sending'],
  ['thinking', 'Thinking'],
  ['speaking', 'Speaking'],
]
const ANNOUNCE = {
  ready: 'Pip is ready.',
  listening: 'Listening. Speak your question, then click Done or pause to send.',
  sending: 'Sending your question to Pip.',
  thinking: 'Pip is thinking.',
  speaking: 'Pip is speaking.',
}
const fmt = (s) => `0:${String(Math.floor(s)).padStart(2, '0')}`

export function VoicePanel() {
  const { settings, updateSettings } = useApp()
  const camera = useCamera()
  const v = useVoiceTutor({ apiBaseUrl: settings.apiBaseUrl, demo: settings.voiceDemo, camera })
  const [typed, setTyped] = useState('')

  const listening = v.status === 'listening'
  const busy = v.status === 'sending' || v.status === 'thinking'
  const talkDisabled = busy || v.requestingMic || !v.micSupported

  const toggleTalking = () => {
    if (talkDisabled) return
    if (listening) {
      v.stopTalking()
    } else {
      v.startTalking()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault()
      toggleTalking()
    } else if (e.key === 'Escape') {
      if (listening || v.requestingMic) {
        e.preventDefault()
        v.cancelRecording()
      }
    }
  }

  const submitTyped = async (e) => {
    e.preventDefault()
    if (await v.sendTyped(typed)) setTyped('')
  }

  return (
    <section className="space-y-4 border-t border-olive/70 pt-5" aria-label="Talk to Pip">
      <div className="flex flex-wrap items-center gap-4">
        <PipPet state={v.status} expression={v.turn?.petExpression} size={96} />
        <div className="min-w-0 flex-1">
          <p className="font-display text-xl text-olive">talk to Pip</p>
          <ol className="mt-1 flex flex-wrap gap-x-1 text-[11px] font-bold tracking-wider uppercase" aria-hidden="true">
            {STEPS.map(([key, label], i) => (
              <li key={key} className={cx(v.status === key ? 'bg-butter px-1 text-olive' : 'px-1 text-olive/35')}>
                {label}
                {i < STEPS.length - 1 && <span className="ml-1 text-olive/25">→</span>}
              </li>
            ))}
          </ol>
          <p className="sr-only" role="status" aria-live="polite">
            {ANNOUNCE[v.status]}
          </p>
        </div>
        <div className="w-full sm:w-auto">
          <Toggle
            checked={settings.voiceDemo}
            onChange={(voiceDemo) => updateSettings({ voiceDemo })}
            label="Demo voice"
            description="Scripted, simulated replies"
          />
        </div>
      </div>

      {settings.voiceDemo && (
        <p className="border-l-2 border-butter-deep bg-butter/40 px-3 py-1.5 text-xs text-olive">
          <strong>Demo voice is on.</strong> Replies are scripted, your recording is not transcribed, and audio is the
          browser’s voice — nothing here comes from Claude.
        </p>
      )}

      {/* talk to Pip */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={toggleTalking}
          onKeyDown={handleKeyDown}
          disabled={talkDisabled}
          aria-pressed={listening}
          aria-describedby="talk-hint"
          className={cx(
            'flex h-14 min-w-56 flex-1 items-center justify-center gap-3 border-2 border-olive px-5 font-display text-lg text-olive transition select-none sm:flex-none cursor-pointer',
            listening ? 'translate-y-px bg-clay/15 shadow-none' : 'bg-butter shadow-[4px_4px_0_0_var(--color-olive)] hover:bg-[#fbeab0]',
            talkDisabled && 'opacity-50 cursor-not-allowed',
          )}
        >
          {listening ? (
            <>
              <span className="size-3 animate-pulse rounded-full bg-clay" aria-hidden="true" />
              <span className="tabular-nums">
                Done talking · {fmt(v.elapsed)} / {fmt(MAX_RECORDING_SEC)}
              </span>
            </>
          ) : (
            <>
              {v.requestingMic ? 'Allow the mic…' : busy ? 'Pip is busy…' : 'Talk to Pip'}
            </>
          )}
        </button>
        {listening && (
          <Button variant="secondary" onClick={v.stopTalking}>
            Send question
          </Button>
        )}
        {(listening || v.requestingMic) && (
          <Button variant="ghost" onClick={v.cancelRecording}>
            Cancel
          </Button>
        )}
        {busy && (
          <Button variant="ghost" onClick={v.cancelRequest}>
            Cancel
          </Button>
        )}
      </div>
      <p id="talk-hint" className="-mt-1 text-[11px] text-olive/60">
        Click to talk, then click Done or pause when finished to send. Esc cancels. Up to {MAX_RECORDING_SEC}s.
      </p>

      {v.requestingMic && (
        <p role="status" className="border-l-2 border-butter-deep bg-butter/30 px-3 py-2 text-sm text-olive">
          Waiting for microphone permission. Choose <strong>Allow</strong> in the browser prompt near the address bar.
          Listening starts after you allow access. Cancel to type your question below.
        </p>
      )}
      {!v.micSupported && (
        <p role="status" className="text-sm text-clay">
          Voice input isn’t available in this browser. Open this site in Chrome or Safari, or type your question below.
        </p>
      )}
      {!settings.voiceDemo && v.micSupported && (
        <p className="text-[11px] text-olive/60">Your browser transcribes your speech; Pip answers using the same AI as typed questions.</p>
      )}

      {/* attached still */}
      {(v.attached || v.frameNote) && (
        <div className="flex items-center gap-3 text-xs text-olive/70">
          {v.attached ? (
            <>
              <img src={v.attached.previewUrl} alt="Still attached to this question" className="h-12 border border-olive/40" />
              <span>
                <strong className="text-olive">still attached</strong> · captured {formatClock(v.attached.capturedAt)}
              </span>
            </>
          ) : (
            <span>{v.frameNote}</span>
          )}
        </div>
      )}

      {/* errors */}
      {v.micError && (
        <p role="alert" className="border-l-2 border-clay pl-3 text-sm text-clay">
          {v.micError.message}
        </p>
      )}
      {v.error && (
        <div role="alert" className="flex flex-wrap items-center gap-3 border-l-2 border-clay pl-3 text-sm text-clay">
          <span className="flex-1">{v.error.message}</span>
          {v.error.canRetry && (
            <Button size="sm" variant="ghost" onClick={v.retry}>
              Retry (same question)
            </Button>
          )}
        </div>
      )}

      {/* the exchange */}
      {v.turn && (
        <div className="ruled space-y-3 bg-cream py-3 pr-3 pl-4">
          <div>
            <p className="text-[10px] font-bold tracking-[0.18em] text-olive/55 uppercase">
              you said{v.turn.simulated && <span className="ml-2 bg-butter px-1 text-olive">simulated</span>}
            </p>
            <p className="text-sm leading-7 text-olive/80 italic">{v.turn.transcript || '—'}</p>
          </div>
          <div className="border-l-2 border-sage-deep pl-3">
            <p className="text-[10px] font-bold tracking-[0.18em] text-olive/55 uppercase">
              pip says{v.turn.simulated && <span className="ml-2 bg-butter px-1 text-olive">simulated</span>}
            </p>
            <p className="text-sm leading-7 text-olive"><MathText>{v.turn.replyText}</MathText></p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {v.needsPlay && (
              <Button size="sm" variant="primary" onClick={v.play}>
                Play Pip’s reply
              </Button>
            )}
            {v.status === 'speaking' && (
              <Button size="sm" variant="ghost" onClick={v.stopSpeaking}>
                Stop speaking
              </Button>
            )}
            {v.hasAudio && v.status === 'ready' && !v.needsPlay && (
              <Button size="sm" variant="ghost" onClick={v.replay}>
                Replay response
              </Button>
            )}
            {v.turn.demoAudio && <span className="text-[11px] text-olive/55">demo audio · browser voice</span>}
            {v.audioError && <span className="text-[11px] text-clay">{v.audioError}</span>}
          </div>
        </div>
      )}

      {/* typed fallback */}
      <form onSubmit={submitTyped} className="flex gap-2">
        <label htmlFor="pip-typed" className="sr-only">
          Type a question for Pip
        </label>
        <input
          id="pip-typed"
          className="input"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder="or type a question…"
          autoComplete="off"
          disabled={busy || listening || v.requestingMic}
        />
        <Button type="submit" variant="secondary" disabled={!typed.trim() || busy || listening || v.requestingMic}>
          Ask
        </Button>
      </form>
    </section>
  )
}
