import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CameraContext } from './contexts'
import * as api from '../services/api'

// Live notebook camera.
//
// Two adapters behind one interface:
//   - 'webcam'   — a laptop / USB webcam via getUserMedia. Preview is a <video>; stills are
//                  grabbed from the stream into a canvas. Nothing is recorded or uploaded
//                  until the student asks a question.
//   - 'hardware' — the Pi / ESP32 overhead camera. Preview is its MJPEG stream (LiveFeed);
//                  stills come from POST /api/camera/capture. It never goes through getUserMedia.
//
// The camera only starts after a deliberate Start click, and is released on Stop, on page
// unload, and if the device disconnects.

export const HARDWARE_SOURCE = 'hardware'
const DEVICE_KEY = 'synapse.camera.device'
const MAX_FRAME_WIDTH = 1600

const ERROR_STATES = {
  NotAllowedError: 'denied',
  SecurityError: 'denied',
  NotFoundError: 'unavailable',
  OverconstrainedError: 'unavailable',
  NotReadableError: 'busy',
  AbortError: 'busy',
}

function readDevice() {
  try {
    return localStorage.getItem(DEVICE_KEY) || ''
  } catch {
    return ''
  }
}

export function CameraProvider({ children }) {
  // 'off' | 'starting' | 'live' | 'denied' | 'unavailable' | 'busy' | 'disconnected' | 'unsupported' | 'error'
  const [status, setStatus] = useState('off')
  const [error, setError] = useState('')
  const [devices, setDevices] = useState([])
  const [source, setSourceState] = useState(readDevice)
  const [stream, setStream] = useState(null)
  const streamRef = useRef(null)
  const videoRef = useRef(null) // off-screen <video> that frames are grabbed from, on any page

  const supported = typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia)

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return
    const all = await navigator.mediaDevices.enumerateDevices()
    setDevices(all.filter((d) => d.kind === 'videoinput'))
  }, [])

  const release = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => {
      t.onended = null
      t.stop()
    })
    streamRef.current = null
    setStream(null)
  }, [])

  const stop = useCallback(() => {
    release()
    setStatus('off')
    setError('')
  }, [release])

  const start = useCallback(
    async (sourceId = source) => {
      release()
      setError('')
      if (sourceId === HARDWARE_SOURCE) {
        setStatus('live') // LiveFeed reports its own connecting/offline/error state
        return
      }
      if (!supported) {
        setStatus('unsupported')
        setError('This browser can’t access cameras here. Use Chrome on http://localhost or an https:// address.')
        return
      }
      setStatus('starting')
      try {
        const media = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            ...(sourceId ? { deviceId: { exact: sourceId } } : {}),
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
        })
        const [track] = media.getVideoTracks()
        track.onended = () => {
          // Unplugged, or the OS took the camera away.
          streamRef.current = null
          setStream(null)
          setStatus('disconnected')
          setError('The camera stopped sending video. Check the cable, then start it again.')
        }
        streamRef.current = media
        setStream(media)
        setStatus('live')
        const actualId = track.getSettings().deviceId
        if (actualId && !sourceId) setSourceState(actualId)
        refreshDevices() // labels only appear after permission is granted
      } catch (err) {
        const state = ERROR_STATES[err?.name] || 'error'
        setStatus(state)
        setError(
          state === 'denied'
            ? 'Camera permission was denied. Click the camera icon in the address bar to allow it, then press Start.'
            : state === 'unavailable'
              ? 'No camera found. Plug in a USB webcam or pick a different camera.'
              : state === 'busy'
                ? 'The camera is in use by another app (Zoom, FaceTime, OBS…). Close it and try again.'
                : `Couldn’t start the camera: ${err?.message || err}`,
        )
      }
    },
    [source, supported, release, refreshDevices],
  )

  const setSource = useCallback(
    (id) => {
      setSourceState(id)
      try {
        localStorage.setItem(DEVICE_KEY, id)
      } catch {
        /* ignore */
      }
      // Switching while live restarts on the new camera; otherwise just remember the choice.
      if (streamRef.current || (status === 'live' && source === HARDWARE_SOURCE)) start(id)
    },
    [start, status, source],
  )

  /**
   * Grab one still from the live feed right now. Returns a frame descriptor that the API
   * can send, or throws if there's nothing live to capture.
   */
  const captureFrame = useCallback(async () => {
    if (source === HARDWARE_SOURCE && status === 'live') {
      const { data } = await api.captureNow()
      if (!data) throw new Error('The overhead camera returned no image.')
      return { source: 'hardware', snapshotId: data.id, previewUrl: data.imageUrl, capturedAt: data.capturedAt }
    }
    const video = videoRef.current
    if (!streamRef.current || !video || video.readyState < 2 || !video.videoWidth) {
      throw new Error('The live camera isn’t running.')
    }
    const scale = Math.min(1, MAX_FRAME_WIDTH / video.videoWidth)
    const width = Math.round(video.videoWidth * scale)
    const height = Math.round(video.videoHeight * scale)
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    canvas.getContext('2d').drawImage(video, 0, 0, width, height)
    const dataUrl = canvas.toDataURL('image/jpeg', 0.85)
    return {
      source: 'webcam',
      mimeType: 'image/jpeg',
      base64: dataUrl.slice(dataUrl.indexOf(',') + 1),
      previewUrl: dataUrl,
      width,
      height,
      capturedAt: new Date().toISOString(),
    }
  }, [source, status])

  // Feed the off-screen grabber so a still can be taken even when no preview is on screen.
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    v.srcObject = stream
    if (stream) v.play().catch(() => {})
  }, [stream])

  // Keep the device list fresh (plug/unplug), and always release the camera on unload.
  useEffect(() => {
    refreshDevices()
    const md = navigator.mediaDevices
    md?.addEventListener?.('devicechange', refreshDevices)
    const onHide = () => release()
    window.addEventListener('pagehide', onHide)
    return () => {
      md?.removeEventListener?.('devicechange', refreshDevices)
      window.removeEventListener('pagehide', onHide)
      release()
    }
  }, [refreshDevices, release])

  const value = useMemo(
    () => ({
      status,
      isLive: status === 'live',
      error,
      devices,
      source,
      setSource,
      supported,
      stream,
      videoRef,
      start,
      stop,
      captureFrame,
    }),
    [status, error, devices, source, setSource, supported, stream, start, stop, captureFrame],
  )

  return (
    <CameraContext.Provider value={value}>
      {children}
      <video
        ref={videoRef}
        muted
        playsInline
        aria-hidden="true"
        tabIndex={-1}
        className="pointer-events-none fixed top-0 left-0 size-px opacity-0"
      />
    </CameraContext.Provider>
  )
}
