import { useEffect, useState } from 'react'
import * as api from '../../services/api'

/**
 * `GET /twin/:id` for a snapshot id (bbox, crops, both readings, image size). Returns `{ twin, loading }`.
 * When `initial` already is that twin (the latest twin on page load) no request is made.
 */
export function useTwin(snapshotId, initial = null) {
  const [fetched, setFetched] = useState({ id: null, twin: null, loading: false })
  const haveInitial = Boolean(snapshotId && initial && initial.snapshot_id === snapshotId)

  useEffect(() => {
    if (!snapshotId || haveInitial) return
    let cancelled = false
    const timer = setTimeout(() => !cancelled && setFetched((s) => (s.id === snapshotId ? s : { id: snapshotId, twin: null, loading: true })), 0)
    api
      .getTwin(snapshotId)
      .then(({ data }) => !cancelled && setFetched({ id: snapshotId, twin: data, loading: false }))
      // the view works from the steps alone (the bridge adds bbox/cropUrl per step); the twin is a bonus
      .catch(() => !cancelled && setFetched({ id: snapshotId, twin: null, loading: false }))
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [snapshotId, haveInitial])

  if (haveInitial) return { twin: initial, loading: false }
  return { twin: fetched.id === snapshotId ? fetched.twin : null, loading: fetched.id === snapshotId && fetched.loading }
}
