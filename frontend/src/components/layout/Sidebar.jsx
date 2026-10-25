import { useApp, useStudyData } from '../../context/contexts'
import { useConnection } from '../../hooks/useConnection'
import { NAV_ITEMS } from './navItems'
import { StatusDot } from '../ui/Badge'
import { cx } from '../../utils/format'

export function Logo() {
  return (
    <div className="leading-tight">
        <p className="text-[15px] font-semibold tracking-tight text-olive">StudBud</p>
        <p className="text-[11px] text-olive/55">your cozy study space</p>
    </div>
  )
}

function NavList({ onNavigate }) {
  const { route, navigate } = useApp()
  const { readings } = useStudyData()
  return (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {NAV_ITEMS.map((item) => {
        const active = route === item.id
        return (
          <a
            key={item.id}
            href={`#/${item.id}`}
            aria-current={active ? 'page' : undefined}
            onClick={(e) => {
              e.preventDefault()
              navigate(item.id)
              onNavigate?.()
            }}
            className={cx(
              'group relative flex items-center gap-3 rounded-sm px-3 py-2.5 text-sm font-medium transition',
              active
                ? 'border border-paper-deep bg-white text-olive shadow-sm'
                : 'border border-transparent text-olive/65 hover:bg-white/60 hover:text-olive',
            )}
          >
            <span className={cx('absolute inset-y-2.5 -right-1 w-1.5 rounded-l-sm', item.tab)} aria-hidden="true" />
            {item.label}
            {item.id === 'reading' && readings.length > 0 && (
              <span className="ml-auto rounded-md bg-olive/12 px-1.5 py-0.5 text-[10px] text-olive/65 tabular-nums">
                {readings.length}
              </span>
            )}
          </a>
        )
      })}
    </nav>
  )
}

function SystemPanel() {
  const conn = useConnection()
  const { extension } = useStudyData()
  const backendState = conn.backend === 'online' ? 'online' : conn.backend === 'offline' ? 'offline' : 'idle'
  const backendLabel =
    conn.backend === 'online' ? 'Connected' : conn.backend === 'offline' ? 'Not connected' : 'Checking…'
  return (
    <div className="rounded-sm border border-olive/12 bg-olive/4 p-3 text-xs">
      <p className="mb-2 font-medium tracking-wide text-olive/55 uppercase">System</p>
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-olive/65">Backend</span>
          <span className="flex items-center gap-1.5 text-olive">
            <StatusDot state={backendState} />
            {backendLabel}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-olive/65">Extension</span>
          <span className="flex items-center gap-1.5 text-olive">
            <StatusDot state={extension.connected ? 'online' : 'idle'} />
            {extension.connected ? 'Linked' : 'Not detected'}
          </span>
        </div>
      </div>
    </div>
  )
}

export function Sidebar({ mobileOpen, onClose }) {
  return (
    <>
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-6 border-r border-paper-deep bg-paper px-4 py-5 lg:flex">
        <Logo />
        <NavList />
        <div className="mt-auto">
          <SystemPanel />
        </div>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-olive/35" onClick={onClose} aria-hidden="true" />
          <aside className="animate-fade-up absolute inset-y-0 left-0 flex w-72 flex-col gap-6 border-r border-olive/12 bg-paper px-4 py-5">
            <div className="flex items-center justify-between">
              <Logo />
              <button
                type="button"
                onClick={onClose}
                className="rounded-sm px-2 py-1 text-xs text-olive/65 hover:bg-olive/12 hover:text-olive"
                aria-label="Close navigation"
              >
                Close
              </button>
            </div>
            <NavList onNavigate={onClose} />
            <div className="mt-auto">
              <SystemPanel />
            </div>
          </aside>
        </div>
      )}
    </>
  )
}
