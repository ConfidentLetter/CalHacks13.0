import { useApp } from '../../context/contexts'
import { useConnection } from '../../hooks/useConnection'

/** Shown when the backend is unreachable or some endpoints aren't built yet. */
export function BackendBanner() {
  const conn = useConnection()
  const { navigate } = useApp()

  let message = null
  if (conn.backend === 'offline') {
    message = `Backend not connected at ${conn.baseUrl}. Camera, AI tutor, and synced history will appear once the StudBud server is running.`
  } else if (conn.missingEndpoints.length) {
    message = `Not built on the backend yet: ${conn.missingEndpoints.join(', ')}.`
  }
  if (!message) return null

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-clay/40 bg-clay/10 px-4 py-2 text-xs text-clay sm:px-6 lg:px-8"
    >
      <span className="inline-flex items-center gap-1.5 rounded-md bg-clay/10 px-2 py-0.5 font-semibold tracking-wider text-clay uppercase">
        {conn.backend === 'offline' ? 'Offline' : 'Partial'}
      </span>
      <span className="min-w-0 flex-1">{message}</span>
      <button
        type="button"
        onClick={() => navigate('settings')}
        className="font-medium text-clay underline-offset-2 hover:underline"
      >
        Backend settings
      </button>
    </div>
  )
}
