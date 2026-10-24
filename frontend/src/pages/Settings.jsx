import { useState } from 'react'
import {
  Ban,
  Camera,
  CheckCircle2,
  Globe,
  PlugZap,
  Plus,
  RotateCcw,
  Server,
  ShieldCheck,
  Timer,
  Trash2,
  X,
  XCircle,
} from 'lucide-react'
import { useApp, useStudyData } from '../context/contexts'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { Segmented, Toggle } from '../components/ui/Controls'
import { ConfirmDialog } from '../components/ui/Modal'
import { CAPTURE_INTERVALS, DEFAULT_SETTINGS, normalizeBaseUrl } from '../services/config'
import * as api from '../services/api'
import { normalizeSite } from '../utils/format'

function SiteList({ title, icon: Icon, tone, sites, onChange, placeholder, emptyText }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const inputId = `site-${title.replace(/\W/g, '').toLowerCase()}`

  const add = (e) => {
    e.preventDefault()
    const site = normalizeSite(value)
    if (!site) return setError('Enter a valid domain, e.g. docs.python.org')
    if (sites.includes(site)) return setError(`${site} is already in this list`)
    onChange([...sites, site])
    setValue('')
    setError('')
  }

  return (
    <div>
      <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-olive">
        <Icon className="size-4 text-olive/65" aria-hidden="true" />
        {title}
      </p>
      <form onSubmit={add} className="flex gap-2">
        <label htmlFor={inputId} className="sr-only">
          Add to {title}
        </label>
        <input
          id={inputId}
          className="input"
          placeholder={placeholder}
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            setError('')
          }}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${inputId}-err` : undefined}
        />
        <Button type="submit" icon={Plus} disabled={!value.trim()}>
          Add
        </Button>
      </form>
      {error && (
        <p id={`${inputId}-err`} className="mt-1.5 text-xs text-clay">
          {error}
        </p>
      )}
      <ul className="mt-3 flex flex-wrap gap-1.5">
        {sites.length === 0 && <li className="text-xs text-olive/55">{emptyText}</li>}
        {sites.map((s) => (
          <li key={s}>
            <Badge tone={tone} className="py-1 pr-1 pl-2.5 text-xs">
              {s}
              <button
                type="button"
                onClick={() => onChange(sites.filter((x) => x !== s))}
                className="ml-0.5 grid size-4 place-items-center rounded-full hover:bg-olive/20"
                aria-label={`Remove ${s}`}
              >
                <X className="size-3" />
              </button>
            </Badge>
          </li>
        ))}
      </ul>
    </div>
  )
}

function BackendCard() {
  const { settings, updateSettings, notify } = useApp()
  const [url, setUrl] = useState(settings.apiBaseUrl)
  const [test, setTest] = useState({ state: 'idle', message: '' })
  const dirty = normalizeBaseUrl(url) !== normalizeBaseUrl(settings.apiBaseUrl)
  const validUrl = /^https?:\/\/[^\s]+$/.test(url.trim())

  const runTest = async () => {
    setTest({ state: 'loading', message: '' })
    try {
      const { data, latencyMs } = await api.testConnection(url)
      setTest({ state: 'ok', message: `Connected in ${latencyMs} ms${data?.version ? ` · backend ${data.version}` : ''}` })
    } catch (err) {
      setTest({ state: 'error', message: err.message })
    }
  }

  const save = (e) => {
    e.preventDefault()
    updateSettings({ apiBaseUrl: normalizeBaseUrl(url) })
    notify('Backend URL saved', 'success')
  }

  return (
    <Card>
      <CardHeader icon={Server} title="Backend connection" subtitle="Where the dashboard sends API requests" />
      <CardBody className="space-y-5">
        <form onSubmit={save} className="space-y-2">
          <label htmlFor="api-url" className="text-sm font-medium text-olive">
            Backend API URL
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id="api-url"
              className="input font-mono text-[13px]"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value)
                setTest({ state: 'idle', message: '' })
              }}
              placeholder="http://localhost:8000"
              spellCheck="false"
              autoComplete="off"
            />
            <div className="flex gap-2">
              <Button icon={PlugZap} onClick={runTest} loading={test.state === 'loading'} disabled={!validUrl}>
                Test
              </Button>
              <Button type="submit" variant="primary" disabled={!dirty || !validUrl}>
                Save
              </Button>
            </div>
          </div>
          {test.state === 'ok' && (
            <p className="flex items-center gap-1.5 text-xs text-sage-ink" role="status">
              <CheckCircle2 className="size-3.5" aria-hidden="true" /> {test.message}
            </p>
          )}
          {test.state === 'error' && (
            <p className="flex items-center gap-1.5 text-xs text-clay" role="alert">
              <XCircle className="size-3.5" aria-hidden="true" /> {test.message}
            </p>
          )}
          <p className="text-xs text-olive/55">
            No API keys are stored in the dashboard — Claude and SpacetimeDB credentials live on the backend.
          </p>
        </form>
      </CardBody>
    </Card>
  )
}

export function Settings() {
  const { settings, updateSettings, notify } = useApp()
  const { clearReadings, extension, capture } = useStudyData()
  const [confirmClear, setConfirmClear] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)

  const doClear = async () => {
    setClearing(true)
    await clearReadings()
    setClearing(false)
    setConfirmClear(false)
  }

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <div className="space-y-5">
        <Card>
          <CardHeader icon={Camera} title="Notebook camera" subtitle="Overhead Raspberry Pi / ESP32 capture" />
          <CardBody className="space-y-5">
            <Toggle
              checked={settings.cameraEnabled}
              onChange={(cameraEnabled) => updateSettings({ cameraEnabled })}
              label="Camera capture"
              description={
                capture.capturing && !settings.cameraEnabled
                  ? 'Stopping capture…'
                  : 'When off, capture is stopped and the Start button is disabled.'
              }
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-olive">Capture interval</p>
                <p className="text-xs text-olive/65">How often the camera photographs your notebook.</p>
              </div>
              <Segmented
                label="Capture interval"
                value={settings.captureIntervalSec}
                onChange={(captureIntervalSec) => updateSettings({ captureIntervalSec })}
                options={CAPTURE_INTERVALS.map((s) => ({ value: s, label: `${s}s` }))}
                disabled={!settings.cameraEnabled}
              />
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            icon={Timer}
            title="Reading tracking"
            subtitle={extension.connected ? 'Synced to the Chrome extension' : 'Extension not detected — saved for when it connects'}
            action={<Badge tone={extension.connected ? 'green' : 'neutral'}>{extension.connected ? 'Linked' : 'Offline'}</Badge>}
          />
          <CardBody className="space-y-5">
            <Toggle
              checked={settings.readingTrackingEnabled}
              onChange={(readingTrackingEnabled) => updateSettings({ readingTrackingEnabled })}
              label="Track active reading"
              description="Pause to stop the extension from recording any new pages."
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-olive">Minimum active reading</p>
                <p className="text-xs text-olive/65">Visible, focused, and recently interacted-with time before a page is saved.</p>
              </div>
              <Segmented
                label="Minimum active reading time"
                value={settings.minReadingSeconds}
                onChange={(minReadingSeconds) => updateSettings({ minReadingSeconds })}
                options={[15, 30, 60].map((s) => ({ value: s, label: `${s}s` }))}
                disabled={!settings.readingTrackingEnabled}
              />
            </div>
            <Toggle
              checked={settings.shareReadingTextWithTutor}
              onChange={(shareReadingTextWithTutor) => updateSettings({ shareReadingTextWithTutor })}
              label="Let the tutor use captured page text"
              description="Off: the tutor only sees page titles and URLs. Page text is uploaded only if you also enable it in the extension."
            />
            <SiteList
              title="Allowed study sites"
              icon={Globe}
              tone="green"
              sites={settings.allowedSites}
              onChange={(allowedSites) => updateSettings({ allowedSites })}
              placeholder="docs.python.org"
              emptyText="No sites allowed — nothing will be tracked."
            />
            <p className="-mt-2 text-xs text-olive/55">
              Chrome still asks you to grant access per site from the extension popup — the dashboard can’t grant permissions for you.
            </p>
            <SiteList
              title="Blocked sites"
              icon={Ban}
              tone="red"
              sites={settings.blockedSites}
              onChange={(blockedSites) => updateSettings({ blockedSites })}
              placeholder="mail.google.com"
              emptyText="No blocked sites."
            />
          </CardBody>
        </Card>
      </div>

      <div className="space-y-5">
        <BackendCard key={settings.apiBaseUrl} />

        <Card>
          <CardHeader icon={ShieldCheck} title="Privacy" subtitle="What Synapse collects — and what it never does" />
          <CardBody className="space-y-4 text-sm leading-relaxed text-olive/80">
            <ul className="space-y-3">
              {[
                ['Opt-in only', 'Reading is tracked only on sites you approve, and only while the tab is visible, focused, and you’re interacting with it.'],
                ['Never collected', 'Passwords, form fields, text inputs, private messages, and pages with login/checkout forms are skipped entirely.'],
                ['Text stays local by default', 'Extracted article text is kept in the extension until you explicitly allow uploading it.'],
                ['Camera', 'Snapshots are taken only while capture is running and are sent to your team’s backend for analysis.'],
                ['Your control', 'Pause tracking anytime, delete individual records, or clear everything below.'],
              ].map(([k, v]) => (
                <li key={k} className="flex gap-3">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-sage-ink" aria-hidden="true" />
                  <span>
                    <strong className="font-medium text-olive">{k}.</strong> {v}
                  </span>
                </li>
              ))}
            </ul>
            <p className="rounded-xl border border-olive/12 bg-olive/4 p-3 text-xs text-olive/65">
              PDFs opened in Chrome’s built-in viewer don’t expose their text to extensions, so for PDFs Synapse records only the
              title, URL and reading time.
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader icon={Trash2} title="Data management" />
          <CardBody className="flex flex-col gap-3 sm:flex-row">
            <Button variant="danger" icon={Trash2} onClick={() => setConfirmClear(true)}>
              Clear reading history
            </Button>
            <Button variant="ghost" icon={RotateCcw} onClick={() => setConfirmReset(true)}>
              Reset settings to defaults
            </Button>
          </CardBody>
        </Card>
      </div>

      <ConfirmDialog
        open={confirmClear}
        onCancel={() => setConfirmClear(false)}
        onConfirm={doClear}
        loading={clearing}
        title="Clear all reading history?"
        message="This deletes every reading record from the backend and from the extension’s local storage, including any records still waiting to sync. This can’t be undone."
        confirmLabel="Clear history"
      />
      <ConfirmDialog
        open={confirmReset}
        onCancel={() => setConfirmReset(false)}
        onConfirm={() => {
          updateSettings({ ...DEFAULT_SETTINGS })
          setConfirmReset(false)
          notify('Settings reset to defaults', 'success')
        }}
        title="Reset settings?"
        message="Capture, tracking, site lists, and the backend URL will return to their defaults. Your data is not deleted."
        confirmLabel="Reset"
      />
    </div>
  )
}
