import { useState } from 'react'
import { useApp, useStudyData } from '../context/contexts'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { Toggle } from '../components/ui/Controls'
import { ConfirmDialog } from '../components/ui/Modal'
import { DEFAULT_SETTINGS, READING_SECONDS, normalizeBaseUrl } from '../services/config'
import * as api from '../services/api'
import { normalizeSite } from '../utils/format'

function Section({ n, title, note, aside, children }) {
  return (
    <section className="grid gap-6 border-t border-olive/70 py-10 first:border-t-0 first:pt-2 lg:grid-cols-[15rem_1fr] lg:gap-14">
      <header>
        <p className="font-display text-sm text-olive/50 tabular-nums">{n}</p>
        <h2 className="mt-0.5 text-2xl text-olive">{title}</h2>
        {note && <p className="mt-2 text-sm leading-relaxed text-olive/65">{note}</p>}
        {aside && <div className="mt-3">{aside}</div>}
      </header>
      <div className="min-w-0 space-y-6">{children}</div>
    </section>
  )
}

function SiteList({ title, tone, sites, onChange, placeholder, emptyText, scopeNote }) {
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
      <p className="mb-2 text-xs font-bold tracking-[0.16em] text-olive/60 uppercase">{title}</p>
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
        <Button type="submit" variant={tone === 'green' ? 'secondary' : 'ghost'} disabled={!value.trim()}>
          Add
        </Button>
      </form>
      {error && (
        <p id={`${inputId}-err`} className="mt-1.5 text-xs text-clay">
          {error}
        </p>
      )}
      <ul className="mt-3 border-t border-dotted border-olive/40">
        {sites.length === 0 && <li className="py-3 text-xs text-olive/55">{emptyText}</li>}
        {sites.map((s) => (
          <li key={s} className="flex items-center gap-3 border-b border-dotted border-olive/40 py-2">
            <span
              aria-hidden="true"
              className={tone === 'green' ? 'h-4 w-1.5 shrink-0 bg-sage-deep' : 'h-4 w-1.5 shrink-0 bg-clay/60'}
            />
            <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-olive">
              {s}
              {scopeNote && <span className="font-sans text-xs text-olive/50"> + subdomains</span>}
            </span>
            <button
              type="button"
              onClick={() => onChange(sites.filter((x) => x !== s))}
              className="text-xs font-semibold text-olive/60 underline decoration-olive/30 underline-offset-4 hover:text-clay hover:decoration-clay"
              aria-label={`Remove ${s}`}
            >
              remove
            </button>
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
    <Section n="05" title="Backend" note="Where the dashboard sends API requests. Your teammates’ server lives here.">
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
              <Button onClick={runTest} loading={test.state === 'loading'} disabled={!validUrl}>
                Test
              </Button>
              <Button type="submit" variant="primary" disabled={!dirty || !validUrl}>
                Save
              </Button>
            </div>
          </div>
          {test.state === 'ok' && (
            <p className="flex items-center gap-1.5 text-xs text-sage-ink" role="status">
              {test.message}
            </p>
          )}
          {test.state === 'error' && (
            <p className="flex items-center gap-1.5 text-xs text-clay" role="alert">
              {test.message}
            </p>
          )}
          <p className="text-xs text-olive/55">
            No API keys are stored in the dashboard — Claude and SpacetimeDB credentials live on the backend.
          </p>
        </form>
    </Section>
  )
}

export function Settings() {
  const { settings, updateSettings, notify, navigate } = useApp()
  const { clearReadings, extension } = useStudyData()
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
    <div className="mx-auto max-w-5xl">
      <Section n="01" title="Notebook camera" note="A live preview of your page. Pip only sees single stills you send.">
            <ul className="space-y-2 text-sm leading-relaxed text-olive/80">
              <li>Starts only when you press Start on “peek at my notebook”, and stops when you press Stop or close the tab.</li>
              <li>Nothing is recorded or saved. A still is grabbed only when you ask Pip a question or press Analyze.</li>
              <li>Choose your webcam from the camera menu.</li>
            </ul>
            <Button variant="secondary" className="self-start" onClick={() => navigate('notebook')}>
              Open the live camera
            </Button>
      </Section>

      <Section
        n="02"
        title="Reading"
        note={extension.connected ? 'Synced with the Chrome extension.' : 'Extension not detected — saved here until it connects.'}
        aside={<Badge tone={extension.connected ? 'green' : 'neutral'}>{extension.connected ? 'linked' : 'offline'}</Badge>}
      >
            <Toggle
              checked={settings.readingTrackingEnabled}
              onChange={(readingTrackingEnabled) => updateSettings({ readingTrackingEnabled })}
              label="Track active reading"
              description="Pause to stop the extension from recording any new pages."
            />
            <div className={settings.readingTrackingEnabled ? '' : 'opacity-50'}>
              <div className="flex items-baseline justify-between gap-3">
                <label htmlFor="min-reading" className="text-sm font-medium text-olive">
                  Save a page after
                </label>
                <output htmlFor="min-reading" className="font-display text-2xl text-olive tabular-nums">
                  {settings.minReadingSeconds}s
                </output>
              </div>
              <p className="text-xs text-olive/65">
                Seconds of active reading (tab visible, window focused, you interacting) on an allowed site.
              </p>
              <input
                id="min-reading"
                type="range"
                min={READING_SECONDS.min}
                max={READING_SECONDS.max}
                step="1"
                value={settings.minReadingSeconds}
                onChange={(e) => updateSettings({ minReadingSeconds: Number(e.target.value) })}
                disabled={!settings.readingTrackingEnabled}
                aria-valuetext={`${settings.minReadingSeconds} seconds`}
                className="mt-3 w-full accent-sage-deep"
              />
              <div className="flex justify-between text-[11px] text-olive/55 tabular-nums" aria-hidden="true">
                <span>{READING_SECONDS.min}s</span>
                <span>{READING_SECONDS.max}s</span>
              </div>
            </div>
            <Toggle
              checked={settings.shareReadingTextWithTutor}
              onChange={(shareReadingTextWithTutor) => updateSettings({ shareReadingTextWithTutor })}
              label="Let the tutor use captured page text"
              description="Off: the tutor only sees page titles and URLs. Page text is uploaded only if you also enable it in the extension."
            />
      </Section>

      <Section
        n="03"
        title="Allowed websites"
        note="Any site you choose — Canvas, Notion, Figma, YouTube, docs. Nothing else is ever tracked. Each entry covers the domain and its subdomains."
      >
            <SiteList
              scopeNote
              title="Allowed websites"
              tone="green"
              sites={settings.allowedSites}
              onChange={(allowedSites) => updateSettings({ allowedSites })}
              placeholder="docs.python.org"
              emptyText="No sites allowed — nothing will be tracked."
            />
            <p className="-mt-3 text-xs leading-relaxed text-olive/55">
              The extension’s list is the source of truth. While the extension is linked, edits here sync to it automatically; otherwise they apply the next time it connects. Chrome still asks you to grant access per site from the extension popup — the dashboard can’t grant permissions.
            </p>
            <SiteList
              title="Blocked sites"
              tone="red"
              sites={settings.blockedSites}
              onChange={(blockedSites) => updateSettings({ blockedSites })}
              placeholder="mail.google.com"
              emptyText="No blocked sites."
            />
      </Section>

      <Section n="04" title="Privacy" note="What StudBud collects — and what it never does.">
            <ul className="space-y-3">
              {[
                ['Opt-in only', 'Reading is tracked only on sites you approve, and only while the tab is visible, focused, and you’re interacting with it.'],
                ['Never collected', 'Passwords, form fields, text inputs, private messages, and pages with login/checkout forms are skipped entirely.'],
                ['Text stays local by default', 'Extracted article text is kept in the extension until you explicitly allow uploading it.'],
                ['Camera', 'The live preview stays on your device. Only the single still sent with a question or Analyze goes to the backend.'],
                ['Your control', 'Pause tracking anytime, delete individual records, or clear everything below.'],
              ].map(([k, v]) => (
                <li key={k} className="flex gap-3">
                  <span aria-hidden="true" className="mt-2 h-px w-4 shrink-0 bg-olive/60" />
                  <span>
                    <strong className="font-medium text-olive">{k}.</strong> {v}
                  </span>
                </li>
              ))}
            </ul>
            <p className="rounded-sm border border-olive/12 bg-olive/4 p-3 text-xs text-olive/65">
              PDFs opened in Chrome’s built-in viewer don’t expose their text to extensions, so for PDFs StudBud records only the
              title, URL and reading time.
            </p>
      </Section>

      <BackendCard key={settings.apiBaseUrl} />

      <Section n="06" title="Your data" note="Delete things, or start the settings over.">
        <div className="flex flex-col gap-3 sm:flex-row">
            <Button variant="danger" onClick={() => setConfirmClear(true)}>
              Clear reading history
            </Button>
            <Button variant="ghost" onClick={() => setConfirmReset(true)}>
              Reset settings to defaults
            </Button>
        </div>
      </Section>

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
