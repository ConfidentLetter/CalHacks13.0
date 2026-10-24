import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRecorder } from './useRecorder'
import { createDemoClient, createLiveClient } from '../services/voiceTutorClient'

/**
 * One voice/typed turn with Pip at a time:
 *   ready → listening → sending → thinking → speaking → ready
 * Stale responses (from a cancelled or superseded turn) are ignored.
 * The last request is kept in memory only, so Retry can resend it without re-recording.
 */
export function useVoiceTutor({ apiBaseUrl, demo, camera }) {
  const client = useMemo(() => (demo ? createDemoClient() : createLiveClient({ baseUrl: apiBaseUrl })), [demo, apiBaseUrl])

  const [status, setStatus] = useState('ready') // 'ready' | 'listening' | 'sending' | 'thinking' | 'speaking'
  const [turn, setTurn] = useState(null) // { frame, transcript, replyText, petExpression, simulated, audioUrl, demoAudio }
  const [error, setError] = useState(null) // { message, canRetry }
  const [needsPlay, setNeedsPlay] = useState(false) // autoplay was blocked
  const [audioError, setAudioError] = useState('')
  const [attached, setAttached] = useState(null) // frame attached to the in-flight / last question
  const [frameNote, setFrameNote] = useState('')

  const turnId = useRef(0)
  const controller = useRef(null)
  const lastRequest = useRef(null)
  const pendingFrame = useRef(null)
  const audio = useRef(null)

  // ---- playback ---------------------------------------------------------------

  const stopSpeaking = useCallback(() => {
    if (audio.current) {
      audio.current.pause()
      audio.current.currentTime = 0
    }
    window.speechSynthesis?.cancel()
    setStatus((s) => (s === 'speaking' ? 'ready' : s))
  }, [])

  const releaseAudio = useCallback(() => {
    const a = audio.current
    if (!a) return
    a.pause()
    a.onplaying = a.onpause = a.onended = a.onerror = null
    a.removeAttribute('src')
    a.load() // drops the network/media resources
    audio.current = null
  }, [])

  const speakDemo = useCallback((text) => {
    const synth = window.speechSynthesis
    if (!synth) {
      setAudioError('This browser has no speech synthesis, so the demo reply is text only.')
      return
    }
    synth.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.rate = 1.02
    u.onstart = () => setStatus('speaking')
    u.onend = u.onerror = () => setStatus((s) => (s === 'speaking' ? 'ready' : s))
    synth.speak(u)
  }, [])

  const play = useCallback(() => {
    setNeedsPlay(false)
    const a = audio.current
    if (!a) return
    a.currentTime = 0
    a.play().catch((err) => {
      if (err?.name === 'NotAllowedError') setNeedsPlay(true)
      else setAudioError('Pip’s audio couldn’t play — the reply is shown as text.')
    })
  }, [])

  const loadAudio = useCallback(
    (url) => {
      releaseAudio()
      setAudioError('')
      const a = new Audio(url)
      a.preload = 'auto'
      // "Speaking" only once sound is actually playing.
      a.onplaying = () => setStatus('speaking')
      a.onpause = a.onended = () => setStatus((s) => (s === 'speaking' ? 'ready' : s))
      a.onerror = () => {
        setStatus((s) => (s === 'speaking' ? 'ready' : s))
        setAudioError('Pip’s audio couldn’t load — the reply is shown as text.')
      }
      audio.current = a
      play()
    },
    [releaseAudio, play],
  )

  const replay = useCallback(() => {
    if (turn?.demoAudio) speakDemo(turn.replyText)
    else play()
  }, [turn, speakDemo, play])

  // ---- requests -----------------------------------------------------------------

  const submit = useCallback(
    async (request) => {
      const id = ++turnId.current
      controller.current?.abort()
      const ac = new AbortController()
      controller.current = ac
      lastRequest.current = request
      setError(null)
      setStatus('sending')
      setAttached(request.frame || null)
      try {
        const opts = { frame: request.frame, signal: ac.signal, onUploaded: () => id === turnId.current && setStatus('thinking') }
        const res =
          request.kind === 'voice'
            ? await client.sendVoice({ ...opts, audio: request.audio, mimeType: request.mimeType, extension: request.extension })
            : await client.sendMessage({ ...opts, message: request.message })
        if (id !== turnId.current) return // stale — a newer turn started
        setTurn({
          frame: request.frame || null,
          transcript: res.transcript,
          replyText: res.replyText,
          petExpression: res.petExpression,
          simulated: res.simulated,
          audioUrl: res.replyAudioUrl,
          demoAudio: res.simulated,
        })
        setStatus('ready')
        if (res.replyAudioUrl) loadAudio(res.replyAudioUrl)
        else if (res.simulated) speakDemo(res.replyText)
        else releaseAudio()
      } catch (err) {
        if (id !== turnId.current || err.kind === 'aborted') return
        setStatus('ready')
        setError({ message: err.message, canRetry: true })
      }
    },
    [client, loadAudio, speakDemo, releaseAudio],
  )

  const retry = useCallback(() => {
    if (lastRequest.current) submit(lastRequest.current) // resends the same recording; never re-records
  }, [submit])

  const cancelRequest = useCallback(() => {
    turnId.current++
    controller.current?.abort()
    setStatus('ready')
  }, [])

  // ---- recording ----------------------------------------------------------------

  const recorder = useRecorder({
    onComplete: async (rec) => {
      const frame = await pendingFrame.current
      pendingFrame.current = null
      submit({ kind: 'voice', ...rec, frame })
    },
  })

  /** Grab one fresh still for this question, if the camera is live. Voice-only otherwise. */
  const grabFrame = useCallback(async () => {
    if (!camera?.isLive) {
      setFrameNote('Camera off — asking without your page.')
      return null
    }
    try {
      const f = await camera.captureFrame()
      setFrameNote('')
      return f
    } catch {
      setFrameNote('Couldn’t grab a still — asking without your page.')
      return null
    }
  }, [camera])

  const busy = status === 'sending' || status === 'thinking'

  const startTalking = useCallback(() => {
    if (busy || recorder.phase !== 'idle') return // one active turn at a time
    stopSpeaking() // never record Pip's own voice
    setError(null)
    recorder.clearError()
    pendingFrame.current = grabFrame() // taken the moment the student starts their question
    recorder.start()
  }, [busy, recorder, stopSpeaking, grabFrame])

  const sendTyped = useCallback(
    async (message) => {
      if (busy || recorder.phase !== 'idle' || !message.trim()) return false
      stopSpeaking()
      const frame = await grabFrame()
      submit({ kind: 'text', message: message.trim(), frame })
      return true
    },
    [busy, recorder.phase, stopSpeaking, grabFrame, submit],
  )

  const listening = recorder.phase === 'recording'
  useEffect(() => {
    if (listening) setStatus('listening')
    else setStatus((s) => (s === 'listening' ? 'ready' : s))
  }, [listening])

  // Release everything when leaving the page.
  useEffect(
    () => () => {
      turnId.current++
      controller.current?.abort()
      window.speechSynthesis?.cancel()
      releaseAudio()
    },
    [releaseAudio],
  )

  return {
    mode: client.mode,
    status: recorder.phase === 'requesting' ? 'ready' : status,
    requestingMic: recorder.phase === 'requesting',
    elapsed: recorder.elapsed,
    micError: recorder.error,
    micSupported: recorder.supported,
    turn,
    error,
    needsPlay,
    audioError,
    attached,
    frameNote,
    hasAudio: Boolean(turn?.audioUrl || turn?.demoAudio),
    startTalking,
    stopTalking: recorder.stop,
    cancelRecording: recorder.cancel,
    cancelRequest,
    sendTyped,
    retry,
    stopSpeaking,
    replay,
    play,
  }
}
