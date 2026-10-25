import { createContext, useContext } from 'react'

export const AppContext = createContext(null)
export const StudyDataContext = createContext(null)
export const CameraContext = createContext(null)

/** settings, navigation, toasts */
export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used inside <AppProvider>')
  return ctx
}

/** status, snapshots, readings, activity — shared across pages */
export function useStudyData() {
  const ctx = useContext(StudyDataContext)
  if (!ctx) throw new Error('useStudyData must be used inside <StudyDataProvider>')
  return ctx
}

/** live notebook camera: status, devices, start/stop, captureFrame */
export function useCamera() {
  const ctx = useContext(CameraContext)
  if (!ctx) throw new Error('useCamera must be used inside <CameraProvider>')
  return ctx
}

export const ROUTES = ['dashboard', 'capture', 'notebook', 'reading', 'tutor', 'settings']
