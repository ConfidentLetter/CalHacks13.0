// A single browser-transcribed turn. No audio upload or paid transcription service.
const MESSAGES = {
  'not-allowed': 'Microphone permission was denied. Allow the microphone from the address bar, then try again, or type your question.',
  'service-not-allowed': 'Speech recognition is blocked in this browser. Try Chrome or Safari, or type your question.',
  'audio-capture': 'No microphone is available. Check your microphone, or type your question.',
  'no-speech': 'I didn’t hear any words. Try again and speak after the Listening indicator appears.',
  network: 'The browser’s speech service couldn’t connect. Check your connection and retry, or type your question.',
  'permission-timeout': 'Still waiting for microphone access. Choose Allow in your browser’s microphone prompt, then click Talk to Pip again. You can also type below.',
}

export function createSpeechInput({ Recognition, onPhase, onComplete, onError, setTimer = setTimeout, clearTimer = clearTimeout }) {
  const recognition = new Recognition()
  recognition.lang = 'en-US'
  recognition.continuous = false
  recognition.interimResults = true
  let ended = false, transcript = '', permissionTimer, durationTimer, stopTimer
  const finish = (error, discard = false) => {
    if (ended) return
    ended = true
    clearTimer(permissionTimer); clearTimer(durationTimer); clearTimer(stopTimer)
    if (error) onError({ code: error, message: MESSAGES[error] || 'Speech recognition stopped. Try again, or type your question.' })
    onPhase('idle')
    if (!error && !discard) {
      if (transcript.trim()) onComplete(transcript.trim())
      else onError({ code: 'no-speech', message: MESSAGES['no-speech'] })
    }
  }
  const abort = () => { try { recognition.abort() } catch { /* already ended */ } }
  const stop = () => {
    if (ended) return
    try { recognition.stop() } catch { finish(null); return }
    // Some engines never emit end after stop. Release the UI and ignore late events.
    stopTimer = setTimer(() => { finish(null); abort() }, 3000)
  }
  recognition.onstart = () => {
    if (ended) { abort(); return }
    clearTimer(permissionTimer)
    onPhase('recording')
    durationTimer = setTimer(stop, 30000)
  }
  recognition.onresult = event => {
    if (ended) return
    transcript = Array.from(event.results, result => result[0]?.transcript || '').join(' ').replace(/\s+/g, ' ')
  }
  recognition.onerror = event => { if (!ended) { finish(event.error || 'error'); abort() } }
  recognition.onend = () => finish(null)
  return {
    start() {
      onPhase('requesting')
      permissionTimer = setTimer(() => { finish('permission-timeout'); abort() }, 15000)
      try { recognition.start() } catch { finish('error'); abort() }
    },
    stop,
    cancel() { finish(null, true); abort() },
  }
}
