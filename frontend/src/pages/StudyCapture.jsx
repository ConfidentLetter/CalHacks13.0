import { useCallback, useEffect, useRef, useState } from 'react'
import { useCamera } from '../context/contexts'
import { HARDWARE_SOURCE } from '../context/CameraProvider'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Segmented, Toggle } from '../components/ui/Controls'
import { LiveVideo } from '../components/shared/LiveVideo'
import * as api from '../services/api'
import { FrameGate, grayscale } from '../features/study-capture/frameGate'
import { StudyView, resetSessionId } from '../features/study-capture/studyView'

const newSession = () => `study-${crypto.randomUUID()}`
function initialSession() {
  const params = new URLSearchParams(location.hash.split('?')[1] || '')
  const supplied = params.get('session')
  if (supplied && /^[a-zA-Z0-9_-]{1,100}$/.test(supplied)) return supplied
  const saved = sessionStorage.getItem('studbud.study.session')
  return saved && /^[a-zA-Z0-9_-]{1,100}$/.test(saved) ? saved : newSession()
}

export function StudyCapture() {
  const camera = useCamera()
  const { isLive, captureFrame, videoRef, source, stop } = camera
  const [session, setSession] = useState(initialSession)
  const [mode, setMode] = useState(() =>
    new URLSearchParams(location.hash.split('?')[1] || '').get('mode') === 'screen' ? 'screen' : 'camera')
  const [automatic, setAutomatic] = useState(false)
  const [busy, setBusy] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [phase, setPhase] = useState(() =>
    new URLSearchParams(location.hash.split('?')[1] || '').get('mode') === 'screen'
      ? 'Use the extension on the study tab to capture manually or start the timer.'
      : 'Start your camera, then enable automatic guidance or capture a frame.')
  const [error, setError] = useState('')
  const [pollError, setPollError] = useState('')
  const [events, setEvents] = useState([])
  const [latest, setLatest] = useState(null)
  const [message, setMessage] = useState('')
  const pending = useRef(null)
  const generation = useRef(0)
  const gate = useRef(new FrameGate())
  const sourceSeen = useRef(source)
  const view = useRef(new StudyView())

  useEffect(() => {
    sessionStorage.setItem('studbud.study.session', session)
    const params = new URLSearchParams({ session, mode })
    history.replaceState(null, '', `${location.pathname}${location.search}#/capture?${params}`)
  }, [session, mode])

  const refresh = useCallback(async () => {
    const { data } = await api.getStudySession(session)
    return data
  }, [session])

  // Includes observations originating in the extension, rather than only local camera calls.
  useEffect(() => {
    let active = true
    let timer
    const poll = async () => {
      const token = view.current.readToken()
      try {
        if (token !== null) {
          const data = await refresh()
          if (!active) return
          if (view.current.isCurrent(token)) {
            setPollError('')
            setEvents(data.events || [])
            setLatest(data.latest || null)
          }
        }
      } catch (err) {
        if (active && view.current.isCurrent(token)) setPollError(err.message)
      }
      if (active) timer = setTimeout(poll, 2000)
    }
    poll()
    return () => { active = false; clearTimeout(timer) }
  }, [refresh])

  useEffect(() => {
    const generationRef = generation
    const pendingRef = pending
    return () => { generationRef.current++; pendingRef.current = null; stop() }
  }, [stop])

  const invalidate = useCallback(() => {
    view.current.freeze()
    generation.current++
    pending.current = null
    setBusy(false)
    setAutomatic(false)
    setPollError('')
    gate.current = new FrameGate()
  }, [])

  useEffect(() => {
    if (sourceSeen.current === source) return
    sourceSeen.current = source
    invalidate()
    setPhase('Camera changed. Enable automatic guidance when this feed is ready.')
  }, [source, invalidate])

  const submit = useCallback(async (frame, signature = null, typed = null) => {
    if (pending.current) return
    view.current.resume()
    const token = { generation: generation.current }
    pending.current = token
    setBusy(true)
    setError('')
    setPhase('Tudor is reading your work…')
    gate.current.attempt(performance.now())
    try {
      if (typed !== null) await api.sendStudyMessage(session, typed)
      else await api.observeStudy(session, frame, signature === null)
      if (pending.current !== token || token.generation !== generation.current) return
      if (signature) gate.current.accept(signature)
      const data = await refresh()
      if (pending.current !== token || token.generation !== generation.current) return
      setEvents(data.events || [])
      setLatest(data.latest || null)
      setPhase('Your turn — answer on the page or send a reply below.')
    } catch (err) {
      if (pending.current === token) { setError(err.message); setPhase('Could not read this step. You can retry.') }
    } finally {
      if (pending.current === token) { pending.current = null; setBusy(false) }
    }
  }, [session, refresh])

  // Sample a tiny local image; the full-resolution still is grabbed only when due.
  useEffect(() => {
    if (!automatic || !isLive || mode !== 'camera') return
    const canvas = document.createElement('canvas')
    let active = true
    let grabbing = false
    const timer = setInterval(async () => {
      const video = videoRef.current
      if (!active || document.hidden || !video || video.readyState < 2 || !video.videoWidth) return
      try {
        const signature = grayscale(video, canvas)
        const result = gate.current.sample(signature, performance.now())
        if (!pending.current) setPhase(result.phase)
        if (!result.ready || pending.current || grabbing) return
        grabbing = true
        const frame = await captureFrame()
        if (active) await submit(frame, signature)
      } catch (err) {
        if (active) { setError(err.message); setAutomatic(false) }
      } finally { grabbing = false }
    }, 400)
    return () => { active = false; clearInterval(timer) }
  }, [automatic, isLive, mode, captureFrame, videoRef, submit])

  const captureNow = async () => {
    try { await submit(await captureFrame()) } catch (err) { setError(err.message) }
  }
  const reset = async () => {
    const previous = session
    invalidate()
    setResetting(true)
    setError('')
    try {
      await api.clearStudySession(previous)
      setSession(resetSessionId(previous, mode, newSession))
      setEvents([])
      setLatest(null)
      setPhase('New problem. Capture your page to begin.')
      view.current.resume()
    } catch (err) {
      setError(err.message)
    } finally { setResetting(false) }
  }
  const setCaptureMode = (next) => {
    invalidate()
    if (next === 'screen') stop()
    setMode(next)
    if (next === 'screen') view.current.resume()
    setPhase(next === 'screen' ? 'Use the extension on the study tab to capture manually or start the timer.'
      : 'Start your camera, then enable automatic guidance or capture a frame.')
  }
  const send = async (event) => {
    event.preventDefault()
    const text = message.trim()
    if (!text || pending.current) return
    setMessage('')
    await submit(null, null, text)
  }
  const latestImage = latest?.image?.source === 'screen' && latest?.image?.base64
    ? `data:${latest.image.mimeType || 'image/jpeg'};base64,${latest.image.base64}` : null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div><h1 className="font-display text-3xl">Work it out with Tudor</h1>
          <p className="mt-1 text-sm text-olive/65">A little guidance as you write. One question at a time.</p></div>
        <Button variant="ghost" onClick={reset} loading={resetting}>New problem</Button>
      </div>
      <Segmented value={mode} onChange={setCaptureMode} label="Capture mode"
        options={[{ value: 'camera', label: 'Live camera' }, { value: 'screen', label: 'Screen captures' }]} />
      <div className="grid items-start gap-6 xl:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader title={mode === 'camera' ? 'Your page, live' : 'Your study tab'}
            subtitle="The entire frame fits inside the preview — no cropping" />
          <CardBody className="space-y-4">
            <div className="grid h-[min(55vh,560px)] min-h-56 w-full place-items-center overflow-hidden rounded-sm bg-olive text-cream">
              {mode === 'camera' && isLive && camera.stream ? <LiveVideo stream={camera.stream} />
                : mode === 'screen' && latestImage ? <img src={latestImage} alt="Latest captured study tab" className="size-full object-contain" />
                  : <p className="max-w-sm p-6 text-center text-sm">{mode === 'camera'
                    ? 'Start the camera, then choose your iPhone or webcam from the list.'
                    : 'Open the extension on your study tab. Choose Capture now or Start timed captures, then Open study captures.'}</p>}
            </div>
            {mode === 'camera' ? <>
              <label className="block text-sm">Camera
                <select className="input mt-1 w-full" value={source === HARDWARE_SOURCE ? '' : source}
                  onChange={(e) => camera.setSource(e.target.value)}>
                  <option value="">Choose a local camera</option>
                  {camera.devices.filter((d) => d.deviceId).map((d, i) =>
                    <option key={d.deviceId} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
                </select>
              </label>
              <div className="flex flex-wrap gap-3">
                {isLive ? <Button variant="danger" onClick={() => { invalidate(); stop(); setPhase('Camera stopped.') }}>Stop camera</Button>
                  : <Button onClick={() => camera.start(source === HARDWARE_SOURCE ? '' : source)} loading={camera.status === 'starting'}>Start camera</Button>}
                <Button variant="primary" onClick={captureNow} disabled={!isLive || busy || resetting} loading={busy}>Capture now</Button>
                <Button variant="ghost" onClick={camera.refreshDevices}>Refresh cameras</Button>
              </div>
              <Toggle checked={automatic} disabled={!isLive || resetting} label="Automatic guidance"
                description="Send a changed still after you stop writing. No video or audio is uploaded."
                onChange={(on) => { if (on) view.current.resume(); gate.current = new FrameGate(); setAutomatic(on) }} />
              {camera.error && <p role="alert" className="text-sm text-clay">{camera.error}</p>}
              <p className="text-xs text-olive/65">For iPhone: enable Continuity Camera, connect and trust this Mac, then lock your phone. Allow Chrome camera access and refresh the list.</p>
            </> : <p className="text-sm text-olive/70">Manual and timed captures are controlled from the extension on the original study tab. They pause when that tab isn’t visible. This page shows the captured still and the same conversation.</p>}
            <p role="status" className="border-l-2 border-sage-deep pl-3 text-sm">{busy ? 'Tudor is reading your work…' : phase}</p>
            {latest?.capturedAt && <p className="text-xs text-olive/55">Last observed: {new Date(latest.image?.capturedAt || latest.capturedAt).toLocaleTimeString()}</p>}
            {(error || pollError) && <p role="alert" className="text-sm text-clay">{error || pollError}</p>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Let’s think it through" subtitle="Write your response on the page, or type below" />
          <CardBody className="space-y-4">
            <div className="max-h-[55vh] min-h-48 space-y-4 overflow-y-auto" aria-live="polite" aria-label="Study conversation">
              {!events.length && <p className="text-sm text-olive/60">Capture your work to begin. Tudor will first establish what you’re trying to do.</p>}
              {events.map((event) => <div key={event.id} className={event.role === 'assistant' ? 'border-l-2 border-sage-deep bg-sage/20 p-3' : 'bg-paper p-3'}>
                <p className="mb-1 text-xs font-bold text-olive/55">{event.role === 'assistant' ? 'Tudor' : event.role === 'observation' ? 'Visible work' : 'You'}</p>
                <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{event.content}</p>
              </div>)}
            </div>
            <form onSubmit={send} className="space-y-3">
              <label className="block text-sm" htmlFor="study-reply">Your reply or question</label>
              <textarea id="study-reply" className="input min-h-24 w-full" maxLength={4000}
                value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Here’s why I tried that step…" />
              <Button type="submit" variant="primary" disabled={busy || resetting || !message.trim()}>Send reply</Button>
            </form>
            <p className="text-xs text-olive/55">Tudor gives hints and questions. If you want a solution, explicitly ask for the answer to that problem.</p>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
