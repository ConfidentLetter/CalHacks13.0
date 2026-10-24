import { useEffect, useRef } from 'react'
import { cx } from '../../utils/format'

/** Renders a MediaStream (the live webcam). Preview only — nothing is recorded. */
export function LiveVideo({ stream, className, label = 'Live view of your notebook' }) {
  const ref = useRef(null)
  useEffect(() => {
    const v = ref.current
    if (!v) return
    v.srcObject = stream || null
    if (stream) v.play().catch(() => {})
  }, [stream])
  return <video ref={ref} muted playsInline aria-label={label} className={cx('size-full object-contain', className)} />
}
