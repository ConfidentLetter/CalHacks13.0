import { Menu } from 'lucide-react'
import { useApp, useCamera, useStudyData } from '../../context/contexts'
import { NAV_ITEMS } from './navItems'
import { StatusDot } from '../ui/Badge'
import { Logo } from './Sidebar'

const SUBTITLES = {
  dashboard: 'everything from today, in one place',
  notebook: 'one still, every line boxed and read exactly as written',
  reading: 'pages you actually sat with, on sites you approved',
  tutor: 'let’s work through it together',
  settings: 'camera, tracking, privacy, and where the backend lives',
}

export function Topbar({ onMenu }) {
  const { route } = useApp()
  const { extension } = useStudyData()
  const camera = useCamera()
  const item = NAV_ITEMS.find((n) => n.id === route)

  return (
    <header className="sticky top-0 z-30 border-b border-olive/8 bg-cream">
      <div className="flex items-center gap-3 px-4 py-3 sm:px-6 lg:px-8 lg:py-4">
        <button
          type="button"
          onClick={onMenu}
          className="grid size-10 place-items-center rounded-xl text-olive/80 hover:bg-olive/12 lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="size-5" />
        </button>
        <div className="lg:hidden">
          <Logo />
        </div>
        <div className="hidden min-w-0 lg:block">
          <h1 className="text-[1.75rem] leading-tight text-olive">{item?.label}</h1>
          <p className="truncate text-[13px] text-olive/65">{SUBTITLES[route]}</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden items-center gap-2 rounded-sm border border-olive/20 bg-white px-2.5 py-1 text-xs text-olive/80 sm:inline-flex">
            <StatusDot state={camera.isLive ? 'offline' : 'idle'} pulse={camera.isLive} />
            {camera.isLive ? 'Live camera on' : 'Camera off'}
          </span>
          <span className="hidden items-center gap-2 rounded-sm border border-olive/20 bg-white px-2.5 py-1 text-xs text-olive/80 sm:inline-flex">
            <StatusDot state={extension.connected && extension.info?.trackingEnabled ? 'online' : 'idle'} />
            {extension.connected ? (extension.info?.trackingEnabled ? 'Tracking reading' : 'Tracking paused') : 'Extension off'}
          </span>
        </div>
      </div>
      <div className="px-4 pb-3 sm:px-6 lg:hidden">
        <h1 className="text-xl text-olive">{item?.label}</h1>
        <p className="text-xs text-olive/65">{SUBTITLES[route]}</p>
      </div>
    </header>
  )
}
