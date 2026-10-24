import { useState } from 'react'
import { Camera, CameraOff, Maximize2, Play, RefreshCw, Sparkles, Square } from 'lucide-react'
import { useApp, useStudyData } from '../context/contexts'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge, StatusDot } from '../components/ui/Badge'
import { Segmented } from '../components/ui/Controls'
import { ErrorState } from '../components/ui/Feedback'
import { Modal } from '../components/ui/Modal'
import { SnapshotFrame } from '../components/shared/SnapshotFrame'
import { AnalysisPanel } from '../components/shared/AnalysisPanel'
import { useNow } from '../hooks/useInterval'
import { CAPTURE_INTERVALS } from '../services/config'
import { formatDateTime } from '../utils/format'

function NextCapture({ capturedAt, intervalSec }) {
  const now = useNow(1000)
  if (!capturedAt) return <span>Waiting for first frame…</span>
  const remaining = Math.round((new Date(capturedAt).getTime() + intervalSec * 1000 - now) / 1000)
  return <span className="tabular-nums">{remaining > 0 ? `Next capture in ~${remaining}s` : 'Next capture any moment…'}</span>
}

export function NotebookObserver() {
  const { settings, updateSettings, navigate, askTutor } = useApp()
  const { snapshot, refreshSnapshot, capture, startCapture, stopCapture, analysis, analyze, status } = useStudyData()
  const [zoom, setZoom] = useState(false)
  const interval = settings.captureIntervalSec
  const cam = status.data?.camera

  const changeInterval = (value) => {
    updateSettings({ captureIntervalSec: value })
    // Starting again with a new interval updates the running capture loop.
    if (capture.capturing) startCapture(value)
  }

  const issueCount = (analysis.data?.steps || []).filter((s) => s.status === 'error').length

  return (
    <div className="grid gap-5 xl:grid-cols-[1.2fr_1fr]">
      <Card>
        <CardHeader
          icon={Camera}
          title="Camera preview"
          subtitle={!cam ? 'Backend offline' : cam.connected ? 'Overhead camera connected' : 'Camera not connected'}
          action={
            <>
              <Badge tone={capture.capturing ? 'violet' : 'neutral'}>
                <StatusDot state={capture.capturing ? 'active' : 'idle'} pulse={capture.capturing} />
                {capture.capturing ? 'Capturing' : 'Idle'}
              </Badge>
            </>
          }
        />
        <CardBody className="space-y-4">
          <div className="relative">
            <SnapshotFrame
              snapshot={snapshot.data}
              loading={snapshot.loading}
              capturing={capture.capturing}
              onOpen={snapshot.data ? () => setZoom(true) : undefined}
            />
            {snapshot.data && (
              <span className="pointer-events-none absolute top-3 right-3 grid size-8 place-items-center rounded-lg bg-olive/35 text-olive">
                <Maximize2 className="size-4" aria-hidden="true" />
              </span>
            )}
          </div>

          {snapshot.error && <ErrorState message={snapshot.error} onRetry={() => refreshSnapshot()} />}

          {!settings.cameraEnabled && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-butter-deep bg-butter/60 p-3 text-xs text-honey">
              <span className="flex items-center gap-2">
                <CameraOff className="size-4" aria-hidden="true" /> Camera capture is turned off in Settings.
              </span>
              <Button size="sm" variant="ghost" onClick={() => navigate('settings')}>
                Open Settings
              </Button>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            {capture.capturing ? (
              <Button variant="danger" icon={Square} loading={capture.busy} onClick={stopCapture}>
                Stop Capture
              </Button>
            ) : (
              <Button
                variant="primary"
                icon={Play}
                loading={capture.busy}
                disabled={!settings.cameraEnabled}
                onClick={() => startCapture(interval)}
              >
                Start Capture
              </Button>
            )}
            <Button icon={RefreshCw} loading={snapshot.loading} onClick={() => refreshSnapshot({ fresh: true })}>
              Refresh Snapshot
            </Button>
            <div className="flex items-center gap-2 sm:ml-auto">
              <span className="text-xs text-olive/65" id="interval-label">
                Interval
              </span>
              <Segmented
                label="Capture interval"
                size="sm"
                value={interval}
                onChange={changeInterval}
                options={CAPTURE_INTERVALS.map((s) => ({ value: s, label: `${s}s` }))}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-olive/8 pt-3 text-xs text-olive/65">
            <span>
              {snapshot.data ? `Last frame: ${formatDateTime(snapshot.data.capturedAt)}` : 'No frames received'}
            </span>
            {capture.capturing && <NextCapture capturedAt={snapshot.data?.capturedAt} intervalSec={interval} />}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          icon={Sparkles}
          title="AI analysis"
          subtitle="Step-by-step check of your handwritten work"
          action={
            <Button
              variant="primary"
              icon={Sparkles}
              loading={analysis.loading}
              disabled={!snapshot.data}
              onClick={analyze}
            >
              Analyze My Work
            </Button>
          }
        />
        <CardBody>
          <AnalysisPanel analysis={analysis} hasSnapshot={Boolean(snapshot.data)} onRetry={analyze} />
          {analysis.data && (
            <div className="mt-5 border-t border-olive/8 pt-4">
              <Button
                variant="secondary"
                className="w-full justify-center"
                onClick={() =>
                  askTutor(
                    issueCount
                      ? 'Walk me through the mistake in my latest notebook snapshot.'
                      : 'What should I practice next based on my latest notebook snapshot?',
                  )
                }
              >
                {issueCount ? 'Ask the tutor about this mistake' : 'Ask the tutor what to practice next'}
              </Button>
            </div>
          )}
        </CardBody>
      </Card>

      <Modal open={zoom} onClose={() => setZoom(false)} title="Notebook snapshot" size="lg">
        {snapshot.data && (
          <img
            src={snapshot.data.imageUrl}
            alt={`Notebook snapshot captured ${formatDateTime(snapshot.data.capturedAt)}`}
            className="w-full bg-paper object-contain"
          />
        )}
      </Modal>
    </div>
  )
}
