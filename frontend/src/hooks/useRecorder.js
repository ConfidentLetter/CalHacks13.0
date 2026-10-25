import { useCallback, useEffect, useRef, useState } from 'react'

export const MAX_RECORDING_SEC = 30
const MIN_BYTES = 1200 // anything smaller is almost certainly silence / a mis-click
const MIN_MS = 400

// Ordered by preference; Safari only supports mp4/aac, Firefox prefers ogg.
const CANDIDATES = [
  ['audio/webm;codecs=opus', 'webm'],
  ['audio/webm', 'webm'],
  ['audio/mp4;codecs=mp4a.40.2', 'm4a'],
  ['audio/mp4', 'm4a'],
  ['audio/ogg;codecs=opus', 'ogg'],
  ['audio/aac', 'aac'],
]

export function pickRecordingFormat() {
  if (typeof MediaRecorder === 'undefined') return null
  for (const [mime, ext] of CANDIDATES) {
    if (MediaRecorder.isTypeSupported?.(mime)) return { mimeType: mime, extension: ext }
  }
  return null
}

const ERRORS = {
  NotAllowedError: ['denied', 'Microphone permission was denied. Allow it from the address bar, or type your question instead.'],
  SecurityError: ['denied', 'This page isn’t allowed to use the microphone. Type your question instead.'],
  NotFoundError: ['no-mic', 'No microphone found. Plug one in, or type your question instead.'],
  NotReadableError: ['busy', 'The microphone is being used by another app. Close it and try again.'],
}

/**
 * Conversational recorder with click-to-talk and automatic silence detection.
 * Permission is requested only inside `start()` (a user gesture).
 * The mic track is stopped after every recording or cancel — nothing listens in the background.
 * Recordings live only in memory; they are never written to storage or logged.
 */
export function useRecorder({ onComplete, onAutoStop, silenceTimeoutMs = 1800 } = {}) {
  // 'idle' | 'requesting' | 'recording'
  const [phase, setPhase] = useState('idle')
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState(null) // { code, message }
  const r = useRef({
    stream: null,
    recorder: null,
    chunks: [],
    startedAt: 0,
    timer: null,
    discard: false,
    cancelled: false,
    format: null,
    audioCtx: null,
    analyser: null,
    dataArray: null,
    hasSpoken: false,
    lastSpokenAt: 0,
  })
  const cb = useRef({ onComplete, onAutoStop })
  useEffect(() => {
    cb.current = { onComplete, onAutoStop }
  }, [onComplete, onAutoStop])

  const format = pickRecordingFormat()

  const cleanup = useCallback(() => {
    const s = r.current
    clearInterval(s.timer)
    s.timer = null
    try {
      s.analyser?.disconnect()
      s.audioCtx?.close()
    } catch {
      /* ignore audio context close errors */
    }
    s.audioCtx = null
    s.analyser = null
    s.dataArray = null
    s.hasSpoken = false
    s.lastSpokenAt = 0
    s.stream?.getTracks().forEach((t) => t.stop())
    s.stream = null
    s.recorder = null
    setElapsed(0)
  }, [])

  const finish = useCallback(
    (discard) => {
      const s = r.current
      if (s.recorder && s.recorder.state !== 'inactive') {
        s.discard = discard
        s.recorder.stop() // onstop does the rest
      } else {
        cleanup()
        setPhase('idle')
      }
    },
    [cleanup],
  )

  const start = useCallback(async () => {
    const s = r.current
    if (s.recorder || phase !== 'idle') return
    setError(null)
    if (!format || !navigator.mediaDevices?.getUserMedia) {
      setError({ code: 'unsupported', message: 'This browser can’t record audio here. Type your question instead.' })
      return
    }
    s.cancelled = false
    setPhase('requesting')
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
    } catch (err) {
      const [code, message] = ERRORS[err?.name] || ['error', `Couldn’t start the microphone: ${err?.message || err}`]
      setError({ code, message })
      setPhase('idle')
      return
    }
    if (s.cancelled) {
      stream.getTracks().forEach((t) => t.stop())
      setPhase('idle')
      return
    }

    let audioCtx = null
    let analyser = null
    let dataArray = null
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext
      if (AudioCtx) {
        audioCtx = new AudioCtx()
        const sourceNode = audioCtx.createMediaStreamSource(stream)
        analyser = audioCtx.createAnalyser()
        analyser.fftSize = 256
        analyser.smoothingTimeConstant = 0.3
        sourceNode.connect(analyser)
        dataArray = new Uint8Array(analyser.frequencyBinCount)
      }
    } catch {
      /* fallback gracefully if Web Audio is unavailable */
    }

    let recorder
    try {
      recorder = new MediaRecorder(stream, { mimeType: format.mimeType })
    } catch {
      try {
        audioCtx?.close()
      } catch {
        /* ignore */
      }
      stream.getTracks().forEach((t) => t.stop())
      setError({ code: 'unsupported', message: 'Recording isn’t supported in this browser. Type your question instead.' })
      setPhase('idle')
      return
    }

    Object.assign(s, {
      stream,
      recorder,
      chunks: [],
      startedAt: performance.now(),
      discard: false,
      format,
      audioCtx,
      analyser,
      dataArray,
      hasSpoken: false,
      lastSpokenAt: 0,
    })

    recorder.ondataavailable = (e) => e.data?.size && s.chunks.push(e.data)
    recorder.onstop = () => {
      const durationMs = performance.now() - s.startedAt
      const blob = new Blob(s.chunks, { type: recorder.mimeType || format.mimeType })
      const discard = s.discard
      s.chunks = []
      cleanup()
      setPhase('idle')
      if (discard) return
      if (blob.size < MIN_BYTES || durationMs < MIN_MS) {
        setError({ code: 'empty', message: 'That was too short to hear anything — speak your question and click to send.' })
        return
      }
      cb.current.onComplete?.({
        audio: blob,
        mimeType: blob.type || format.mimeType,
        extension: format.extension,
        durationMs,
      })
    }
    recorder.start(250)
    setPhase('recording')
    s.timer = setInterval(() => {
      const now = performance.now()
      const sec = (now - s.startedAt) / 1000
      setElapsed(sec)

      // Automatic silence detection: detects speech, then auto-sends after a natural pause
      if (s.analyser && s.dataArray) {
        s.analyser.getByteFrequencyData(s.dataArray)
        let sum = 0
        for (let i = 0; i < s.dataArray.length; i++) {
          sum += s.dataArray[i]
        }
        const avg = sum / s.dataArray.length
        if (sec > 0.4) {
          if (avg > 16) {
            s.hasSpoken = true
            s.lastSpokenAt = now
          } else if (s.hasSpoken && s.lastSpokenAt && now - s.lastSpokenAt > silenceTimeoutMs) {
            cb.current.onAutoStop?.()
            finish(false)
            return
          }
        }
      }

      if (sec >= MAX_RECORDING_SEC) {
        cb.current.onAutoStop?.()
        finish(false)
      }
    }, 100)
  }, [format, phase, cleanup, finish, silenceTimeoutMs])

  /** Stop talking: submit recording. */
  const stop = useCallback(() => {
    if (r.current.recorder) finish(false)
    else r.current.cancelled = true
  }, [finish])

  const cancel = useCallback(() => {
    r.current.cancelled = true
    finish(true)
  }, [finish])

  // Never keep the mic after leaving the page or losing focus mid-recording.
  useEffect(() => {
    const s = r.current
    const onBlur = () => {
      if (s.recorder) {
        finish(true)
        setError({ code: 'blur', message: 'Recording cancelled because the window lost focus.' })
      }
    }
    window.addEventListener('blur', onBlur)
    return () => {
      window.removeEventListener('blur', onBlur)
      if (s.recorder && s.recorder.state !== 'inactive') {
        s.discard = true
        s.recorder.stop()
      }
      s.stream?.getTracks().forEach((t) => t.stop())
      try {
        s.analyser?.disconnect()
        s.audioCtx?.close()
      } catch {
        /* ignore */
      }
      clearInterval(s.timer)
    }
  }, [finish])

  return { phase, elapsed, error, clearError: () => setError(null), start, stop, cancel, supported: Boolean(format) }
}
