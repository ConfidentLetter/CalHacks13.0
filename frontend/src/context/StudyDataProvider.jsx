import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { StudyDataContext, useApp } from './contexts'
import * as api from '../services/api'
import { bridge, startBridge } from '../services/extensionBridge'
import { useExtensionBridge } from '../hooks/useConnection'
import { useInterval } from '../hooks/useInterval'

const STATUS_POLL_MS = 10_000
const READING_POLL_MS = 15_000
const ACTIVITY_KEY = 'synapse.activity.v2'
const NEW_HIGHLIGHT_MS = 8_000

function loadActivity() {
  try {
    return JSON.parse(localStorage.getItem(ACTIVITY_KEY)) || []
  } catch {
    return []
  }
}

export function StudyDataProvider({ children }) {
  const { settings, updateSettings, notify } = useApp()
  const ext = useExtensionBridge()

  // ---- status ---------------------------------------------------------------
  const [status, setStatus] = useState({ data: null, loading: true, error: null })

  const refreshStatus = useCallback(async () => {
    try {
      const { data } = await api.getStatus()
      setStatus({ data, loading: false, error: null })
      return data
    } catch (err) {
      setStatus({ data: null, loading: false, error: err.message })
      return null
    }
  }, [])

  // ---- activity log (session events: captures, analyses, questions) --------
  const [events, setEvents] = useState(loadActivity)
  const logEvent = useCallback((type, title, detail = '') => {
    setEvents((prev) => {
      const next = [{ id: `${Date.now()}-${Math.random()}`, type, title, detail, at: new Date().toISOString() }, ...prev].slice(0, 40)
      try {
        localStorage.setItem(ACTIVITY_KEY, JSON.stringify(next))
      } catch {
        /* ignore */
      }
      return next
    })
  }, [])

  // ---- notebook analysis -----------------------------------------------------
  // Stills are grabbed from the live camera (CameraProvider) only when the student asks.
  const [analysis, setAnalysis] = useState({ data: null, frame: null, loading: false, error: null })
  // The most recent still the AI actually looked at (from Analyze or a tutor question).
  const [lastFrame, setLastFrame] = useState(null)

  const analyze = useCallback(
    async (frame) => {
      setLastFrame(frame)
      setAnalysis({ data: null, frame, loading: true, error: null })
      try {
        const { data } = await api.analyzeFrame(frame)
        setAnalysis({ data, frame, loading: false, error: null })
        const issues = (data.steps || []).filter((s) => s.status === 'error').length
        logEvent('analysis', 'Notebook page analyzed', issues ? `${issues} issue${issues > 1 ? 's' : ''} found` : 'No issues found')
      } catch (err) {
        setAnalysis({ data: null, frame, loading: false, error: err.message })
      }
    },
    [logEvent],
  )

  // ---- reading history ------------------------------------------------------
  const [remote, setRemote] = useState({ items: [], loading: true, error: null })
  const [newIds, setNewIds] = useState(() => new Set())
  const seenIds = useRef(null)

  const refreshReadings = useCallback(async () => {
    try {
      const { data } = await api.getReadingHistory()
      setRemote({ items: data, loading: false, error: null })
    } catch (err) {
      setRemote({ items: [], loading: false, error: err.message })
    }
  }, [])

  // Merge backend history with records relayed live by the extension.
  const readings = useMemo(() => {
    const byId = new Map()
    for (const r of remote.items) byId.set(r.id, r)
    for (const r of ext.readings) if (!byId.has(r.id)) byId.set(r.id, api.normalizeReading(r))
    return [...byId.values()].sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''))
  }, [remote.items, ext.readings])

  // Highlight records that arrive after the first load.
  useEffect(() => {
    if (remote.loading) return
    const ids = readings.map((r) => r.id)
    if (seenIds.current === null) {
      seenIds.current = new Set(ids)
      return
    }
    const fresh = ids.filter((id) => !seenIds.current.has(id))
    if (!fresh.length) return
    fresh.forEach((id) => seenIds.current.add(id))
    setNewIds((prev) => new Set([...prev, ...fresh]))
    setTimeout(() => setNewIds((prev) => new Set([...prev].filter((id) => !fresh.includes(id)))), NEW_HIGHLIGHT_MS)
  }, [readings, remote.loading])

  const deleteReading = useCallback(
    async (record) => {
      if (record.source === 'extension') {
        bridge.deleteReading(record.id)
        notify('Removed from extension storage', 'success')
        return true
      }
      try {
        await api.deleteReading(record.id)
        setRemote((r) => ({ ...r, items: r.items.filter((x) => x.id !== record.id) }))
        notify('Reading deleted', 'success')
        return true
      } catch (err) {
        notify(`Delete failed: ${err.message}`, 'error')
        return false
      }
    },
    [notify],
  )

  const clearReadings = useCallback(async () => {
    try {
      await api.clearReadingHistory()
      bridge.clearReadings()
      setRemote((r) => ({ ...r, items: [] }))
      notify('Reading history cleared', 'success')
      return true
    } catch (err) {
      notify(`Could not clear history: ${err.message}`, 'error')
      return false
    }
  }, [notify])

  // ---- lifecycle ------------------------------------------------------------
  useEffect(() => {
    startBridge()
  }, [])

  // Initial loads, and reload whenever the backend URL or data mode changes.
  useEffect(() => {
    seenIds.current = null
    setRemote((r) => ({ ...r, loading: true }))
    refreshStatus()
    refreshReadings()
  }, [settings.apiBaseUrl, refreshStatus, refreshReadings])

  // Extension ↔ dashboard preference sync. When the extension reports its state, adopt
  // its tracking switch and any sites approved from the popup; then push dashboard edits.
  const adoptedExt = useRef(false)
  useEffect(() => {
    const info = ext.info
    if (!info) return
    updateSettings((prev) => {
      const extraSites = (info.allowedSites || []).filter((s) => !prev.allowedSites.includes(s))
      const patch = {}
      if (extraSites.length) patch.allowedSites = [...prev.allowedSites, ...extraSites]
      if (Number.isInteger(info.minReadingSeconds) && info.minReadingSeconds !== prev.minReadingSeconds) {
        patch.minReadingSeconds = info.minReadingSeconds
      }
      if (typeof info.trackingEnabled === 'boolean' && info.trackingEnabled !== prev.readingTrackingEnabled) {
        patch.readingTrackingEnabled = info.trackingEnabled
      }
      return patch
    })
    adoptedExt.current = true
  }, [ext.info, updateSettings])

  useEffect(() => {
    if (!ext.connected || !adoptedExt.current) return
    bridge.updateSettings({
      trackingEnabled: settings.readingTrackingEnabled,
      allowedSites: settings.allowedSites,
      blockedSites: settings.blockedSites,
      minReadingSeconds: settings.minReadingSeconds,
      backendUrl: settings.apiBaseUrl,
    })
  }, [
    ext.connected,
    settings.readingTrackingEnabled,
    settings.allowedSites,
    settings.blockedSites,
    settings.minReadingSeconds,
    settings.apiBaseUrl,
  ])

  useInterval(refreshStatus, STATUS_POLL_MS)
  useInterval(refreshReadings, READING_POLL_MS)

  // Combined timeline: session events + reading records.
  const activity = useMemo(() => {
    const fromReadings = readings.slice(0, 15).map((r) => ({
      id: `r-${r.id}`,
      type: 'reading',
      title: r.title,
      detail: r.url,
      at: r.timestamp,
      durationSec: r.durationSec,
    }))
    return [...events, ...fromReadings].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 20)
  }, [events, readings])

  const value = {
    status,
    refreshStatus,
    analysis,
    analyze,
    lastFrame,
    setLastFrame,
    readings,
    readingsState: remote,
    refreshReadings,
    newIds,
    deleteReading,
    clearReadings,
    activity,
    logEvent,
    extension: ext,
  }

  return <StudyDataContext.Provider value={value}>{children}</StudyDataContext.Provider>
}
