import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { useCamera, useStudyData } from '../context/contexts'
import { HARDWARE_SOURCE } from '../context/CameraProvider'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { StatusDot } from '../components/ui/Badge'
import { Toggle } from '../components/ui/Controls'
import { Modal } from '../components/ui/Modal'
import { LiveFeed } from '../components/shared/LiveFeed'
import { LiveVideo } from '../components/shared/LiveVideo'
import { AnalysisPanel } from '../components/shared/AnalysisPanel'
import { VoicePanel } from '../components/shared/VoicePanel'
import { useConnection } from '../hooks/useConnection'
import { formatClock, timeAgo } from '../utils/format'

const STATE_COPY = {
  off: ['camera off', 'Press Start to see your notebook. Nothing turns on until you do.'],
  starting: ['starting…', 'Waiting for your browser’s camera permission.'],
  denied: ['permission denied', null],
  unavailable: ['no camera found', null],
  busy: ['camera in use', null],
  disconnected: ['feed disconnected', null],
  unsupported: ['not supported here', null],
  error: ['camera error', null],
}

function LiveBadge({ live, label }) {
  return (
    <span
      role="status"
      className="absolute top-3 left-3 inline-flex items-center gap-1.5 border border-olive/40 bg-cream px-2 py-0.5 text-[11px] font-bold tracking-wider text-olive uppercase"
    >
      <StatusDot state={live ? 'offline' : 'idle'} pulse={live} />
      {label}
    </span>
  )
}

export function NotebookObserver() {
  const { analysis, analyze, status } = useStudyData()
  const camera = useCamera()
  const backendOnline = useConnection().backend === 'online'
  const [grabError, setGrabError] = useState('')
  const [zoom, setZoom] = useState(false)

  const isHardware = camera.source === HARDWARE_SOURCE
  const canGrab = camera.isLive
  const frame = analysis.frame

  const analyzeNow = async () => {
    setGrabError('')
    try {
      analyze(await camera.captureFrame())
    } catch (err) {
      setGrabError(err.message)
    }
  }


  const [stateLabel, stateHint] = STATE_COPY[camera.status] || STATE_COPY.error

  return (
    <div className="grid gap-10 xl:grid-cols-[1.7fr_1fr]">
      {/* ---- live preview ---- */}
      <Card className="sheet rounded-none">
        <CardHeader
          title="Live camera"
          subtitle={isHardware ? 'Overhead Pi / ESP32 stream' : 'Laptop or USB webcam'}
          action={
            <Toggle
              checked={camera.isLive || camera.status === 'starting'}
              onChange={(on) => (on ? camera.start() : camera.stop())}
              label="Live camera"
              disabled={camera.status === 'starting'}
            />
          }
        />
        <CardBody className="space-y-4">
          {isHardware && camera.isLive ? (
            <LiveFeed camera={status.data?.camera} enabled backendOnline={backendOnline} />
          ) : (
            <div className="relative aspect-video w-full overflow-hidden border border-olive/70 bg-olive">
              {camera.isLive && camera.stream && <LiveVideo stream={camera.stream} />}
              {!camera.isLive && (
                <div className="absolute inset-0 grid place-items-center p-6 text-center text-cream">
                  <div className="max-w-sm space-y-3">
                    <p className="font-display text-xl">{stateLabel}</p>
                    <p className="text-xs text-cream/75">{camera.error || stateHint}</p>
                    {camera.status !== 'starting' && camera.status !== 'unsupported' && (
                      <Button variant="primary" onClick={() => camera.start()}>
                        {camera.status === 'off' ? 'Start camera' : 'Try again'}
                      </Button>
                    )}
                  </div>
                </div>
              )}
              <LiveBadge live={camera.isLive} label={camera.isLive ? 'live' : stateLabel} />
            </div>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-0 flex-1">
              <span className="mb-1 block text-[11px] font-bold tracking-[0.16em] text-olive/60 uppercase">camera</span>
              <select className="input h-10 py-0" value={camera.source} onChange={(e) => camera.setSource(e.target.value)}>
                <option value="">Default webcam</option>
                {camera.devices.map((d, i) => (
                  <option key={d.deviceId || i} value={d.deviceId}>
                    {d.label || `Camera ${i + 1}`}
                  </option>
                ))}
                <option value={HARDWARE_SOURCE}>Overhead camera (Pi / ESP32 stream)</option>
              </select>
            </label>
            {camera.isLive || camera.status === 'starting' ? (
              <Button variant="danger" onClick={camera.stop}>
                Stop
              </Button>
            ) : (
              <Button variant="primary" onClick={() => camera.start()} disabled={camera.status === 'unsupported'}>
                Start
              </Button>
            )}
          </div>

          <p className="border-l-2 border-sage-deep pl-3 text-xs leading-relaxed text-olive/70">
            This is a preview only — nothing is recorded or saved. Pip doesn’t watch the video; when you ask a question
            or press Analyze, it gets <strong className="text-olive">one still frame</strong> from that moment.
          </p>

          <VoicePanel />
        </CardBody>
      </Card>

      {/* ---- what the AI actually looked at ---- */}
      <Card className="self-start border-0 bg-transparent">
        <CardHeader
          className="border-olive/70 px-0"
          title="What Pip analyzed"
          subtitle="A single still, not the live video"
          action={
            <Button variant="primary" icon={Sparkles} loading={analysis.loading} disabled={!canGrab} onClick={analyzeNow}>
              Analyze my page
            </Button>
          }
        />
        <CardBody className="space-y-4 px-0">
          {grabError && (
            <p className="text-xs text-clay" role="alert">
              Couldn’t grab a frame: {grabError}
            </p>
          )}
          {frame ? (
            <figure>
              <button
                type="button"
                onClick={() => setZoom(true)}
                className="relative block w-full cursor-zoom-in border border-olive/70 bg-paper"
                aria-label="Open analyzed still full size"
              >
                <img src={frame.previewUrl} alt="Still frame sent to Pip" className="w-full object-contain" />
                <span className="absolute top-2 left-2 border border-olive/40 bg-butter px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-olive uppercase">
                  still
                </span>
              </button>
              <figcaption className="mt-1.5 text-xs text-olive/65">
                captured {formatClock(frame.capturedAt)} · {timeAgo(frame.capturedAt)}
                {frame.source === 'hardware' ? ' · overhead camera' : ' · webcam'}
              </figcaption>
            </figure>
          ) : (
            <p className="border-l-2 border-butter-deep pl-3 text-sm text-olive/65">
              Nothing analyzed yet. Start the camera and press “Analyze my page” — the still Pip looks at will appear here.
            </p>
          )}
          <AnalysisPanel analysis={analysis} hasSnapshot={Boolean(frame)} onRetry={canGrab ? analyzeNow : undefined} />
        </CardBody>
      </Card>

      <Modal open={zoom && Boolean(frame)} onClose={() => setZoom(false)} title="Still frame sent to Pip" size="lg">
        {frame && <img src={frame.previewUrl} alt="Still frame sent to Pip" className="w-full bg-olive object-contain" />}
      </Modal>
    </div>
  )
}
