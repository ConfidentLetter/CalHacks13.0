import { useCallback, useEffect, useRef, useState } from 'react'

const Recognition = typeof window !== 'undefined' ? window.SpeechRecognition || window.webkitSpeechRecognition : null

const ERRORS = {
  'not-allowed': 'Microphone permission was denied. Allow it in your browser’s site settings to use voice input.',
  'service-not-allowed': 'Speech recognition is blocked in this browser.',
  'audio-capture': 'No microphone was found.',
  network: 'Speech recognition needs an internet connection in this browser.',
  'no-speech': 'Didn’t catch anything — try again.',
}

/**
 * Browser speech-to-text (Web Speech API). Audio is handled by the browser;
 * this hook never records, uploads, or stores it — it only returns text.
 * `onFinal(text)` is called with each finished phrase.
 */
export function useSpeechRecognition({ onFinal, lang = 'en-US' } = {}) {
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const [error, setError] = useState(null)
  const rec = useRef(null)
  const finalRef = useRef(onFinal)

  useEffect(() => {
    finalRef.current = onFinal
  }, [onFinal])

  useEffect(() => () => rec.current?.abort(), [])

  const start = useCallback(() => {
    if (!Recognition) return
    setError(null)
    const r = new Recognition()
    r.lang = lang
    r.continuous = true
    r.interimResults = true
    r.onresult = (e) => {
      let partial = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript
        if (e.results[i].isFinal) finalRef.current?.(t.trim())
        else partial += t
      }
      setInterim(partial)
    }
    r.onerror = (e) => {
      if (e.error !== 'aborted') setError(ERRORS[e.error] || `Voice input failed (${e.error}).`)
    }
    r.onend = () => {
      setListening(false)
      setInterim('')
      rec.current = null
    }
    rec.current = r
    try {
      r.start()
      setListening(true)
    } catch (err) {
      setError(err.message)
    }
  }, [lang])

  const stop = useCallback(() => rec.current?.stop(), [])

  return { supported: Boolean(Recognition), listening, interim, error, start, stop, clearError: () => setError(null) }
}
