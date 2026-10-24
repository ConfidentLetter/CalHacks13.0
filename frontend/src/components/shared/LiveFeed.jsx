import { useEffect, useState } from 'react'
import { RotateCw } from 'lucide-react'
import { Button } from '../ui/Button'
import { StatusDot } from '../ui/Badge'
import { getStreamInfo } from '../../services/api'
import { cx } from '../../utils/format'

const CONNECT_TIMEOUT_MS = 10_000

const LABEL = {
  off: 'preview off',
  offline: 'offline',
  connecting: 'connecting…',
  live: 'live',
  error: 'stream error',
}
const DOT = { off: 'idle', offline: 'offline', connecting: 'warning', live: 'active', error: 'offline' }

/**
 * Continuous feed from the overhead camera (MJPEG in an <img>, or browser video).
 * Only says "live" after a real frame arrives; never shows placeholder footage.
 */
export function LiveFeed({ camera, enabled, backendOnline }) {
  const { url, type } = getStreamInfo(camera)
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState({ key: null, state: 'connecting', message: '' })

  const available = enabled && backendOnline && camera?.connected
  const key = `${url}#${attempt}`
  const src = `${url}${url.includes('?') ? '&' : '?'}t=${attempt}` // cache-bust on retry

  // Give up waiting for a first frame after a while.
  useEffect(() => {
    if (!available) return
    const t = setTimeout(
      () =>
        setResult((r) =>
          r.key === key && r.state !== 'connecting'
            ? r
            : { key, state: 'error', message: 'No frames received from the camera stream.' },
        ),
      CONNECT_TIMEOUT_MS,
    )
    return () => clearTimeout(t)
  }, [available, key])

  const state = !enabled
    ? 'off'
    : !backendOnline || !camera?.connected
      ? 'offline'
      : result.key === key
        ? result.state
        : 'connecting'

  const onLive = () => setResult({ key, state: 'live', message: '' })
  const onFail = () => setResult({ key, state: 'error', message: `Couldn’t load the stream at ${url}.` })

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-sm border border-olive/70 bg-olive">
      {available && state !== 'error' && (
        type === 'video' ? (
          <video
            key={key}
            src={src}
            autoPlay
            muted
            playsInline
            onPlaying={onLive}
            onError={onFail}
            className={cx('size-full object-contain', state !== 'live' && 'opacity-0')}
          />
        ) : (
          <img
            key={key}
            src={src}
            alt="Live view of the notebook from the overhead camera"
            onLoad={onLive}
            onError={onFail}
            className={cx('size-full object-contain', state !== 'live' && 'opacity-0')}
          />
        )
      )}

      {state !== 'live' && (
        <div className="absolute inset-0 grid place-items-center p-6 text-center text-cream">
          <div className="max-w-xs space-y-2">
            <p className="font-display text-lg">
              {state === 'off' && 'live preview is off'}
              {state === 'offline' && (backendOnline ? 'camera not connected' : 'backend offline')}
              {state === 'connecting' && 'connecting to the camera…'}
              {state === 'error' && 'can’t reach the live feed'}
            </p>
            <p className="text-xs text-cream/70">
              {state === 'off' && 'Turn on Live Preview to watch the notebook in real time. Screenshots keep working.'}
              {state === 'offline' && 'The live feed appears when the overhead camera reports in through the backend.'}
              {state === 'connecting' && 'Waiting for the first frame.'}
              {state === 'error' && result.message}
            </p>
            {state === 'error' && (
              <Button size="sm" variant="primary" icon={RotateCw} onClick={() => setAttempt((a) => a + 1)}>
                Try again
              </Button>
            )}
          </div>
        </div>
      )}

      <span
        className="absolute top-3 left-3 inline-flex items-center gap-1.5 rounded-sm border border-olive/40 bg-cream px-2 py-0.5 text-[11px] font-bold tracking-wider text-olive uppercase"
        role="status"
      >
        <StatusDot state={DOT[state]} pulse={state === 'live'} />
        {LABEL[state]}
      </span>
    </div>
  )
}
