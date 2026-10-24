import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { useCamera, useStudyData } from '../context/contexts'
import { HARDWARE_SOURCE } from '../context/CameraProvider'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { StatusDot } from '../components/ui/Badge'
import { Toggle } from '../components/ui/Controls'
import { LoadingDots } from '../components/ui/Feedback'
import { Modal } from '../components/ui/Modal'
import { LiveFeed } from '../components/shared/LiveFeed'
import { LiveVideo } from '../components/shared/LiveVideo'
import { VoicePanel } from '../components/shared/VoicePanel'
import { RecognitionView } from '../components/recognition/RecognitionView'
import { SummaryStrip } from '../components/recognition/SummaryStrip'
import { useConnection } from '../hooks/useConnection'
import { formatClock, timeAgo } from '../utils/format'
import { isDeskView } from '../utils/camera'

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
  const { analysis, analyze, recognition, status } = useStudyData()
  const camera = useCamera()
  const backendOnline = useConnection().backend === 'online'
  const [grabError, setGrabError] = useState('')
  const [zoom, setZoom] = useState(false)

  const isHardware = camera.source === HARDWARE_SOURCE
  const canGrab = camera.isLive
  const frame = analysis.frame
  // after a reload the frame is gone but the result knows which still it came from
  const stillUrl = frame?.previewUrl || recognition?.image?.stillUrl || null
  const stillAt = frame?.capturedAt || recognition?.capturedAt || null

  const analyzeNow = async () => {
    setGrabError('')
    try {
      analyze(await camera.captureFrame())
    } catch (err) {
      setGrabError(err.message)
    }
  }

  const [stateLabel, stateHint] = STATE_COPY[camera.status] || STATE_COPY.error
  const emptyCopy = camera.isLive
    ? 'press “Analyze my page” — every line on the page will be boxed and transcribed exactly as written.'
    : 'start the camera and press “Analyze my page” — the flattened page, every line boxed and read, will appear here.'

  return (
    <div className="space-y-10">
      <div className="grid gap-8 xl:grid-cols-[1.25fr_1fr]">
        {/* ---- live preview (Micha's card, untouched) ---- */}
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
                      <p className="text-sm text-cream/75">{camera.error || stateHint}</p>
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
                <span className="mb-1 flex items-center gap-2 text-[11px] font-bold tracking-[0.16em] text-olive/60 uppercase">
                  camera
                  {camera.isDeskView && (
                    <span className="inline-flex items-center gap-1 border border-sage-deep bg-sage/60 px-1.5 py-px text-[10px] tracking-wider text-sage-ink normal-case">
                      <StatusDot state="online" /> desk view
                    </span>
                  )}
                </span>
                <select className="input h-10 py-0" value={camera.source} onChange={(e) => camera.setSource(e.target.value)}>
                  <option value="">Default webcam</option>
                  {camera.devices.map((d, i) => (
                    <option key={d.deviceId || i} value={d.deviceId}>
                      {d.label ? (isDeskView(d.label) ? `${d.label} · desk view` : d.label) : `Camera ${i + 1}`}
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

            {!camera.isDeskView && !isHardware && (
              <p className="text-[13px] leading-relaxed text-olive/60">
                No overhead camera? Open <strong className="font-semibold text-olive/80">Desk View</strong> from the camera menu in the
                macOS menu bar, then pick the Desk View camera here. Your choice is remembered.
              </p>
            )}

            <p className="border-l-2 border-sage-deep pl-3 text-sm leading-relaxed text-olive/70">
              This is a preview only — nothing is recorded or saved. Pip doesn’t watch the video; when you ask a question
              or press Analyze, it gets <strong className="text-olive">one still frame</strong> from that moment.
            </p>

            <VoicePanel />
          </CardBody>
        </Card>

        {/* ---- what Pip analyzed: the still + the verdict ---- */}
        <Card className="self-start border-0 bg-transparent">
          <CardHeader
            className="border-olive/70 px-0"
            title="What Pip analyzed"
            subtitle="A single still, read line by line"
            action={
              <Button variant="primary" icon={Sparkles} loading={analysis.loading} disabled={!canGrab} onClick={analyzeNow}>
                Analyze my page
              </Button>
            }
          />
          <CardBody className="space-y-5 px-0">
            {grabError && (
              <p className="text-sm text-clay" role="alert">
                Couldn’t grab a frame: {grabError}
              </p>
            )}
            {stillUrl ? (
              <figure className="flex items-start gap-4">
                <button
                  type="button"
                  onClick={() => setZoom(true)}
                  className="relative block w-40 shrink-0 cursor-zoom-in border border-olive/70 bg-paper"
                  aria-label="Open analyzed still full size"
                >
                  <img src={stillUrl} alt="Still frame sent to Pip" className="w-full object-contain" />
                  <span className="absolute top-1.5 left-1.5 border border-olive/40 bg-butter px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-olive uppercase">
                    still
                  </span>
                </button>
                <figcaption className="text-sm leading-relaxed text-olive/65">
                  {stillAt ? (
                    <>
                      captured {formatClock(stillAt)} · {timeAgo(stillAt)}
                      {frame ? (frame.source === 'hardware' ? ' · overhead camera' : ' · webcam') : ''}
                    </>
                  ) : (
                    'the still Pip looked at'
                  )}
                  <br />
                  <span className="text-olive/50">the flattened page with every line boxed is below.</span>
                </figcaption>
              </figure>
            ) : (
              <p className="border-l-2 border-butter-deep pl-3 text-[15px] text-olive/65">
                Nothing analyzed yet. Start the camera and press “Analyze my page” — the still Pip looks at will appear here.
              </p>
            )}

            {analysis.loading ? (
              <p className="flex items-center gap-2 text-[15px] text-honey" aria-live="polite">
                <LoadingDots label="Reading" /> reading your page…
              </p>
            ) : recognition ? (
              <>
                <SummaryStrip model={recognition} />
                <a
                  href="#page-twin"
                  onClick={(e) => {
                    e.preventDefault()
                    document.getElementById('page-twin')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                  }}
                  className="inline-flex items-center gap-1.5 text-sm font-semibold text-olive underline decoration-olive/30 underline-offset-4 hover:decoration-olive"
                >
                  ↓ see every line on the page twin
                </a>
              </>
            ) : null}
          </CardBody>
        </Card>
      </div>

      {/* ---- the hero: page twin + line ledger ---- */}
      <RecognitionView
        model={recognition}
        loading={analysis.loading}
        startedAt={analysis.startedAt}
        error={analysis.error}
        onRetry={canGrab ? analyzeNow : undefined}
        emptyCopy={emptyCopy}
        showSummary={false}
      />

      <Modal open={zoom && Boolean(stillUrl)} onClose={() => setZoom(false)} title="Still frame sent to Pip" size="lg">
        {stillUrl && <img src={stillUrl} alt="Still frame sent to Pip" className="w-full bg-olive object-contain" />}
      </Modal>
    </div>
  )
}
