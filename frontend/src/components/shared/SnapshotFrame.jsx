import { useState } from 'react'
import { Skeleton } from '../ui/Feedback'
import { cx, formatClock, timeAgo } from '../../utils/format'

/** Displays a notebook snapshot, or a camera placeholder when there is none. */
export function SnapshotFrame({ snapshot, loading, capturing, onOpen, className, compact = false }) {
  const [broken, setBroken] = useState(null)
  const isBroken = snapshot && broken === snapshot.imageUrl

  if (loading && !snapshot) return <Skeleton className={cx('aspect-[4/3] w-full rounded-sm', className)} />

  if (!snapshot || isBroken) {
    return (
      <div
        className={cx(
          'relative grid aspect-[4/3] w-full place-items-center overflow-hidden rounded-sm ruled border border-dashed border-sage-deep bg-paper',
          className,
        )}
      >
        <div className="flex flex-col items-center gap-2 px-6 text-center">
          <p className="text-sm text-olive/80">{isBroken ? 'Snapshot image failed to load' : 'No snapshot yet'}</p>
          {!compact && (
            <p className="max-w-xs text-xs text-olive/55">
              {capturing
                ? 'Waiting for the next frame from the overhead camera…'
                : 'Start capture or refresh to pull the latest frame from the overhead camera.'}
            </p>
          )}
        </div>
        <Corners />
      </div>
    )
  }

  const Wrapper = onOpen ? 'button' : 'div'
  return (
    <Wrapper
      type={onOpen ? 'button' : undefined}
      onClick={onOpen}
      aria-label={onOpen ? 'Open snapshot full size' : undefined}
      className={cx(
        'group relative block aspect-[4/3] w-full overflow-hidden rounded-sm border border-olive/12 bg-paper text-left',
        onOpen && 'cursor-zoom-in',
        className,
      )}
    >
      <img
        src={snapshot.imageUrl}
        alt={`Notebook snapshot captured ${formatClock(snapshot.capturedAt)}`}
        onError={() => setBroken(snapshot.imageUrl)}
        className={cx('size-full object-contain transition duration-500', onOpen && 'group-hover:scale-[1.02]', loading && 'opacity-60')}
      />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between gap-2 border-t border-paper-deep bg-paper/90 px-3 py-2 text-[11px] text-olive">
        <span className="flex items-center gap-1.5">
          {capturing && <span className="size-1.5 animate-pulse rounded-full bg-clay" aria-hidden="true" />}
          {formatClock(snapshot.capturedAt)} · {timeAgo(snapshot.capturedAt)}
        </span>
        {snapshot.deviceId && <span className="truncate text-olive/65">{snapshot.deviceId}</span>}
      </div>
    </Wrapper>
  )
}

function Corners() {
  const c = 'absolute size-5 border-sage-deep'
  return (
    <>
      <span className={cx(c, 'top-3 left-3 border-t-2 border-l-2 rounded-tl-md')} />
      <span className={cx(c, 'top-3 right-3 border-t-2 border-r-2 rounded-tr-md')} />
      <span className={cx(c, 'bottom-3 left-3 border-b-2 border-l-2 rounded-bl-md')} />
      <span className={cx(c, 'right-3 bottom-3 border-r-2 border-b-2 rounded-br-md')} />
    </>
  )
}
