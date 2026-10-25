import { useCallback, useEffect, useRef, useState } from 'react'
import { createSpeechInput } from '../services/speechInput'

export function useSpeechRecorder({ onComplete } = {}) {
  const [phase, setPhase] = useState('idle')
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState(null)
  const session = useRef(null)
  const callback = useRef(onComplete)
  useEffect(() => { callback.current = onComplete }, [onComplete])
  const Recognition = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)
  const start = useCallback(() => {
    if (session.current || !Recognition) return
    setError(null)
    const input = createSpeechInput({ Recognition,
      onPhase: next => { setPhase(next); if (next === 'idle') { session.current = null; setElapsed(0) } },
      onError: setError,
      onComplete: transcript => callback.current?.({ transcript }),
    })
    session.current = input
    input.start()
  }, [Recognition])
  const cancel = useCallback(() => session.current?.cancel(), [])
  useEffect(() => {
    if (phase !== 'recording') return
    const started = performance.now()
    const timer = setInterval(() => setElapsed((performance.now() - started) / 1000), 100)
    return () => clearInterval(timer)
  }, [phase])
  useEffect(() => {
    // Permission dialogs may blur the window; don't cancel pending permission.
    const onBlur = () => { if (phase === 'recording') cancel() }
    window.addEventListener('blur', onBlur)
    return () => window.removeEventListener('blur', onBlur)
  }, [phase, cancel])
  useEffect(() => () => { session.current?.cancel() }, [])
  return { phase, elapsed, error, start, stop: () => session.current?.stop(), cancel,
    clearError: () => setError(null), supported: Boolean(Recognition) }
}
