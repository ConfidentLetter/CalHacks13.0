import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AppContext, ROUTES } from './contexts'
import { loadSettings, saveSettings } from '../services/config'
import { configureApi } from '../services/api'

function readRoute() {
  const r = window.location.hash.replace(/^#\/?/, '').split('?')[0]
  return ROUTES.includes(r) ? r : 'dashboard'
}

export function AppProvider({ children }) {
  const [settings, setSettings] = useState(() => {
    const s = loadSettings()
    configureApi(s)
    return s
  })
  const [route, setRoute] = useState(readRoute)
  const [tutorDraft, setTutorDraft] = useState(null)
  const [toasts, setToasts] = useState([])
  const toastId = useRef(0)

  useEffect(() => {
    const onHash = () => setRoute(readRoute())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const updateSettings = useCallback((patch) => {
    setSettings((prev) => {
      const changes = typeof patch === 'function' ? patch(prev) : patch
      if (!Object.keys(changes).length) return prev
      const next = { ...prev, ...changes }
      saveSettings(next)
      configureApi(next)
      return next
    })
  }, [])

  const navigate = useCallback((to) => {
    window.location.hash = `/${to}`
    window.scrollTo({ top: 0 })
  }, [])

  const dismissToast = useCallback((id) => setToasts((t) => t.filter((x) => x.id !== id)), [])

  const notify = useCallback(
    (message, tone = 'info') => {
      const id = ++toastId.current
      setToasts((t) => [...t.slice(-3), { id, message, tone }])
      setTimeout(() => dismissToast(id), 4200)
    },
    [dismissToast],
  )

  /** Send a question to the AI Tutor page (used by Quick Ask and "Ask about this"). */
  const askTutor = useCallback(
    (question) => {
      setTutorDraft({ question, at: Date.now() })
      navigate('tutor')
    },
    [navigate],
  )

  const value = useMemo(
    () => ({
      settings,
      updateSettings,
      route,
      navigate,
      toasts,
      notify,
      dismissToast,
      tutorDraft,
      consumeTutorDraft: () => setTutorDraft(null),
      askTutor,
    }),
    [settings, updateSettings, route, navigate, toasts, notify, dismissToast, tutorDraft, askTutor],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}
