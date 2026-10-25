import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { StudyDataContext, useApp } from './contexts'
import * as api from '../services/api'
import { bridge, startBridge } from '../services/extensionBridge'
import { useExtensionBridge } from '../hooks/useConnection'
import { useInterval } from '../hooks/useInterval'
import { buildRecognition } from '../components/recognition/twinModel'
import { useTwin } from '../components/recognition/useTwin'
import { deleteReadingCopies } from '../features/reading-memory/deleteReading'

const STATUS_POLL_MS = 10_000
const READING_POLL_MS = 15_000
const ACTIVITY_KEY = 'synapse.activity.v2'
const NEW_HIGHLIGHT_MS = 8_000
const ANALYSIS_KEY = 'synapse.analysis.v1' // last judged result (small JSON, no image data) so a reload keeps the twin judged
const RECOG_STATS_KEY = 'synapse.recognition.stats.v1' // { day, linesRead, errorsCaught }

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback
  } catch {
    return fallback
  }
}
function saveJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* ignore quota / private mode */
  }
}
const todayKey = () => new Date().toDateString()

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
  const [analysis, setAnalysis] = useState(() => ({
    data: loadJson(ANALYSIS_KEY, null),
    frame: null,
    loading: false,
    startedAt: null,
    error: null,
  }))
  // The most recent still the AI actually looked at (from Analyze or a tutor question).
  const [lastFrame, setLastFrame] = useState(null)
  // Recognition counters for the dashboard stat row (today only).
  const [recogStats, setRecogStats] = useState(() => {
    const saved = loadJson(RECOG_STATS_KEY, null)
    return saved?.day === todayKey() ? saved : { day: todayKey(), linesRead: 0, errorsCaught: 0 }
  })

  const analyze = useCallback(
    async (frame) => {
      setLastFrame(frame)
      setAnalysis((prev) => ({ ...prev, frame, loading: true, startedAt: Date.now(), error: null }))
      try {
        const { data } = await api.analyzeFrame(frame)
        setAnalysis({ data, frame, loading: false, startedAt: null, error: null })
        saveJson(ANALYSIS_KEY, data)
        const issues = (data.steps || []).filter((s) => s.status === 'error').length
        const read = (data.steps || []).length
        setRecogStats((prev) => {
          const base = prev.day === todayKey() ? prev : { day: todayKey(), linesRead: 0, errorsCaught: 0 }
          const next = { ...base, linesRead: base.linesRead + read, errorsCaught: base.errorsCaught + issues }
          saveJson(RECOG_STATS_KEY, next)
          return next
        })
        logEvent(
          'analysis',
          'Notebook page read',
          `${read} line${read === 1 ? '' : 's'} · ${issues ? `${issues} error${issues > 1 ? 's' : ''} caught` : 'no errors'}`,
        )
      } catch (err) {
        // keep the previous result on screen under the error
        setAnalysis((prev) => ({ ...prev, frame, loading: false, startedAt: null, error: err.message }))
      }
    },
    [logEvent],
  )

  // ---- page twin (recognition detail) ---------------------------------------
  // On load, the newest stored twin (so the notebook and dashboard are never empty when one exists);
  // after Analyze, the twin for that snapshot. Mock/fallback twins are never shown as the student's work.
  const [latestTwin, setLatestTwin] = useState(null)
  const refreshLatestTwin = useCallback(async () => {
    try {
      const { data } = await api.getLatestTwin()
      setLatestTwin(data)
      return data
    } catch {
      setLatestTwin(null)
      return null
    }
  }, [])

  const activeSnapshotId = analysis.data?.snapshotId || latestTwin?.snapshot_id || null
  const { twin: activeTwin } = useTwin(activeSnapshotId, latestTwin)

  const recognition = useMemo(() => {
    if (!activeSnapshotId) return null
    const twin = activeTwin && activeTwin.snapshot_id === activeSnapshotId ? activeTwin : null
    // a restored result only counts if it belongs to the twin on screen
    const result = analysis.data && analysis.data.snapshotId === activeSnapshotId ? analysis.data : null
    if (!result && analysis.data && analysis.frame) return buildRecognition({ result: analysis.data, twin: null })
    return buildRecognition({ result, twin })
  }, [activeSnapshotId, activeTwin, analysis.data, analysis.frame])

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
    for (const r of ext.readings) {
      const extensionRecord = api.normalizeReading(r)
      const existing = byId.get(r.id)
      byId.set(r.id, existing ? { ...extensionRecord, ...existing, synced: r.synced } : extensionRecord)
    }
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
      try {
        await deleteReadingCopies(record, {
          remoteItems: remote.items, extensionItems: ext.readings,
          deleteRemote: api.deleteReading, deleteLocal: bridge.deleteReading,
        })
        setRemote((r) => ({ ...r, items: r.items.filter((x) => x.id !== record.id) }))
        notify('Reading deleted', 'success')
        return true
      } catch (err) {
        notify(`Delete failed: ${err.message}`, 'error')
        return false
      }
    },
    [notify, remote.items, ext.readings],
  )

  const clearReadings = useCallback(async () => {
    try {
      await api.clearReadingHistory()
      if (ext.connected) await bridge.clearReadings()
      setRemote((r) => ({ ...r, items: [] }))
      notify('Reading history cleared', 'success')
      return true
    } catch (err) {
      notify(`Could not clear history: ${err.message}`, 'error')
      return false
    }
  }, [notify, ext.connected])

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
    refreshLatestTwin()
  }, [settings.apiBaseUrl, refreshStatus, refreshReadings, refreshLatestTwin])

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
    recognition,
    recogStats,
    refreshLatestTwin,
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
