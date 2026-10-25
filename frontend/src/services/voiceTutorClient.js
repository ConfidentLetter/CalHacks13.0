// Replaceable adapter for talking to Pip. The UI only ever calls `sendVoice` / `sendMessage`;
// swap the implementation without touching components. See docs/BACKEND_CONTRACT.md.
//
// Both modes resolve to:
//   { requestId, transcript, replyText, replyAudioUrl, petExpression, simulated }
// and reject with an Error whose `kind` is 'timeout' | 'network' | 'http' | 'aborted'.
//
// The browser never talks to Anthropic, Cartesia, or any provider directly — only to our backend.

import { DEFAULT_SETTINGS, normalizeBaseUrl } from './config'
import { uid } from '../utils/format'

export const VOICE_PATHS = {
  voice: import.meta.env.VITE_TUTOR_VOICE_PATH || '/api/tutor/voice',
  message: import.meta.env.VITE_TUTOR_MESSAGE_PATH || '/api/tutor/message',
}
const TIMEOUT_MS = 90_000
const SESSION_KEY = 'synapse.tutor.session'

/** Anonymous per-tab session id; no account or personal data. */
export function getSessionId() {
  try {
    let id = sessionStorage.getItem(SESSION_KEY)
    if (!id) {
      id = `s-${uid()}`
      sessionStorage.setItem(SESSION_KEY, id)
    }
    return id
  } catch {
    return 's-ephemeral'
  }
}

class TutorError extends Error {
  constructor(message, kind, status = 0) {
    super(message)
    this.kind = kind
    this.status = status
  }
}

function base64ToBlob(base64, type) {
  const bin = atob(base64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Blob([bytes], { type })
}

/** The camera frame → a JPEG Blob (webcam frames carry base64; hardware frames carry a URL). */
async function frameToJpeg(frame) {
  if (!frame) return null
  if (frame.base64) return base64ToBlob(frame.base64, frame.mimeType || 'image/jpeg')
  if (frame.previewUrl) {
    const res = await fetch(frame.previewUrl)
    if (res.ok) return res.blob()
  }
  return null
}

/**
 * XHR rather than fetch so we can tell "sending" (upload in flight) from "thinking"
 * (upload done, waiting for the backend) — fetch can't report upload completion.
 */
function postForm(url, form, { signal, onUploaded }) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.responseType = 'json'
    xhr.timeout = TIMEOUT_MS
    xhr.upload.onload = () => onUploaded?.()
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300 && xhr.response) return resolve(xhr.response)
      const detail = xhr.response?.error || xhr.response?.detail || ''
      const notBuilt = [404, 405, 501].includes(xhr.status)
      reject(
        new TutorError(
          notBuilt
            ? `This speech upload service is unavailable (HTTP ${xhr.status}). Refresh the page to use browser voice input, or type your question.`
            : detail || `The backend answered HTTP ${xhr.status}.`,
          'http',
          xhr.status,
        ),
      )
    }
    xhr.onerror = () => reject(new TutorError('Couldn’t reach Pip’s backend. Check that it’s running, then retry.', 'network'))
    xhr.ontimeout = () => reject(new TutorError('Pip took too long to answer. The free server may be waking up; please retry.', 'timeout'))
    xhr.onabort = () => reject(new TutorError('Request cancelled.', 'aborted'))
    if (signal) {
      if (signal.aborted) return xhr.abort()
      signal.addEventListener('abort', () => xhr.abort(), { once: true })
    }
    xhr.send(form)
  })
}

function normalizeReply(json, requestId, baseUrl) {
  if (json.requestId && json.requestId !== requestId) {
    throw new TutorError('The backend answered a different request.', 'http')
  }
  const audio = json.replyAudioUrl
  return {
    requestId,
    transcript: json.transcript ?? null,
    replyText: json.replyText || '',
    replyAudioUrl: audio ? (/^(https?:|data:|blob:)/.test(audio) ? audio : `${baseUrl}${audio.startsWith('/') ? '' : '/'}${audio}`) : null,
    petExpression: json.petExpression || 'neutral',
    simulated: false,
  }
}

async function appendImage(form, frame) {
  const jpeg = await frameToJpeg(frame).catch(() => null)
  if (jpeg) {
    form.append('image', jpeg, 'notebook.jpg')
    form.append('imageCapturedAt', frame.capturedAt)
  }
  return Boolean(jpeg)
}

// ---- live adapter ------------------------------------------------------------

export function createLiveClient({ baseUrl = DEFAULT_SETTINGS.apiBaseUrl } = {}) {
  const root = normalizeBaseUrl(baseUrl)
  return {
    mode: 'live',
    async sendVoice({ audio, mimeType, extension, frame, signal, onUploaded }) {
      const requestId = `r-${uid()}`
      const form = new FormData()
      form.append('audio', audio, `question.${extension}`)
      form.append('audioMimeType', mimeType)
      form.append('sessionId', getSessionId())
      form.append('requestId', requestId)
      await appendImage(form, frame)
      return normalizeReply(await postForm(`${root}${VOICE_PATHS.voice}`, form, { signal, onUploaded }), requestId, root)
    },
    async sendMessage({ message, frame, signal, onUploaded }) {
      const requestId = `r-${uid()}`
      const form = new FormData()
      form.append('message', message)
      form.append('sessionId', getSessionId())
      form.append('requestId', requestId)
      await appendImage(form, frame)
      const json = await postForm(`${root}${VOICE_PATHS.message}`, form, { signal, onUploaded })
      return { ...normalizeReply(json, requestId, root), transcript: message }
    },
  }
}

// ---- demo adapter (clearly simulated; never used as a fallback for failed live calls) ----

const DEMO_REPLIES = [
  { replyText: 'Let’s look at it together. Read your second line out loud — does the sign match the line above it?', petExpression: 'curious' },
  { replyText: 'Nice setup! Before you simplify, check that both sides got the same operation.', petExpression: 'encouraging' },
  { replyText: 'You’re close. What would happen if you plugged your answer back into the first equation?', petExpression: 'thinking' },
  { replyText: 'That step looks right to me. Want to try the next one on your own first?', petExpression: 'celebrating' },
]

export function createDemoClient() {
  let i = 0
  const wait = (ms, signal) =>
    new Promise((resolve, reject) => {
      const t = setTimeout(resolve, ms)
      signal?.addEventListener('abort', () => {
        clearTimeout(t)
        reject(new TutorError('Request cancelled.', 'aborted'))
      })
    })
  const reply = async ({ signal, onUploaded, typed }) => {
    const requestId = `demo-${uid()}`
    await wait(500, signal)
    onUploaded?.()
    await wait(900, signal)
    const r = DEMO_REPLIES[i++ % DEMO_REPLIES.length]
    return {
      requestId,
      // We deliberately do NOT pretend to transcribe the recording.
      transcript: typed ?? '(demo — your recording was not transcribed)',
      replyText: r.replyText,
      replyAudioUrl: null, // demo audio uses the browser's speech synthesis, labelled as such
      petExpression: r.petExpression,
      simulated: true,
    }
  }
  return {
    mode: 'demo',
    sendVoice: (opts) => reply(opts),
    sendMessage: (opts) => reply({ ...opts, typed: opts.message }),
  }
}
