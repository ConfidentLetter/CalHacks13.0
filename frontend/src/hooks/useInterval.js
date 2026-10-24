import { useEffect, useRef, useState } from 'react'

/** Calls `fn` every `ms` milliseconds; pass null to pause. */
export function useInterval(fn, ms) {
  const saved = useRef(fn)
  useEffect(() => {
    saved.current = fn
  }, [fn])
  useEffect(() => {
    if (ms == null) return
    const id = setInterval(() => saved.current(), ms)
    return () => clearInterval(id)
  }, [ms])
}

/** Re-renders periodically so relative timestamps ("2m ago") stay fresh. */
export function useNow(ms = 15_000) {
  const [now, setNow] = useState(() => Date.now())
  useInterval(() => setNow(Date.now()), ms)
  return now
}
