import { useState } from 'react'
import { AppProvider } from './context/AppProvider'
import { StudyDataProvider } from './context/StudyDataProvider'
import { CameraProvider } from './context/CameraProvider'
import { useApp } from './context/contexts'
import { Sidebar } from './components/layout/Sidebar'
import { Topbar } from './components/layout/Topbar'
import { BackendBanner } from './components/layout/BackendBanner'
import { Toasts } from './components/ui/Toasts'
import { Dashboard } from './pages/Dashboard'
import { NotebookObserver } from './pages/NotebookObserver'
import { ReadingMemory } from './pages/ReadingMemory'
import { AITutor } from './pages/AITutor'
import { Settings } from './pages/Settings'
import { StudyCapture } from './pages/StudyCapture'

const PAGES = {
  dashboard: Dashboard,
  capture: StudyCapture,
  notebook: NotebookObserver,
  reading: ReadingMemory,
  tutor: AITutor,
  settings: Settings,
}

function Shell() {
  const { route } = useApp()
  const [menuOpen, setMenuOpen] = useState(false)
  const Page = PAGES[route] || Dashboard

  return (
    <div className="relative flex min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-butter px-3 py-2 text-sm text-olive focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <Sidebar mobileOpen={menuOpen} onClose={() => setMenuOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenu={() => setMenuOpen(true)} />
        <BackendBanner />
        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
          <Page key={route} />
        </main>
      </div>
      <Toasts />
    </div>
  )
}

export default function App() {
  return (
    <AppProvider>
      <StudyDataProvider>
        <CameraProvider>
          <Shell />
        </CameraProvider>
      </StudyDataProvider>
    </AppProvider>
  )
}
