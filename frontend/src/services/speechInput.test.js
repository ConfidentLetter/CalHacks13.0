import assert from 'node:assert/strict'
import test from 'node:test'
import { createSpeechInput } from './speechInput.js'

function setup() {
  let recognition
  const events = [], timers = new Map()
  class Recognition {
    constructor() { recognition = this }
    start() { this.started = true }
    stop() { this.stopped = true }
    abort() { this.aborted = true }
  }
  const session = createSpeechInput({ Recognition, onPhase: p => events.push(['phase', p]),
    onComplete: t => events.push(['complete', t]), onError: e => events.push(['error', e.code]),
    setTimer: (fn, ms) => { timers.set(ms, fn); return ms }, clearTimer: id => timers.delete(id) })
  session.start()
  return { session, recognition, events, timers }
}

test('requests speech immediately and submits recognized words once', () => {
  const { recognition: r, events } = setup()
  assert.equal(r.started, true)
  assert.deepEqual(events, [['phase', 'requesting']])
  r.onstart()
  r.onresult({ results: [[{ transcript: 'What is acceleration?' }]] })
  r.onend(); r.onend()
  assert.deepEqual(events, [['phase', 'requesting'], ['phase', 'recording'], ['phase', 'idle'], ['complete', 'What is acceleration?']])
})

test('cancel while awaiting permission aborts and ignores late events', () => {
  const { session, recognition: r, events } = setup()
  session.cancel(); r.onstart(); r.onresult({ results: [[{ transcript: 'late' }]] }); r.onend()
  assert.equal(r.aborted, true)
  assert.equal(events.some(e => e[0] === 'complete'), false)
  assert.deepEqual(events.at(-1), ['phase', 'idle'])
})

test('permission wait times out and permits a fresh attempt', () => {
  const { recognition: r, events, timers } = setup()
  timers.get(15000)()
  assert.equal(r.aborted, true)
  assert.ok(events.some(e => e[0] === 'error' && e[1] === 'permission-timeout'))
  assert.deepEqual(events.at(-1), ['phase', 'idle'])
})

test('permission denial is actionable and never sends a fake transcript', () => {
  const { recognition: r, events } = setup()
  r.onerror({ error: 'not-allowed' }); r.onend()
  assert.ok(events.some(e => e[0] === 'error' && e[1] === 'not-allowed'))
  assert.equal(events.some(e => e[0] === 'complete'), false)
})

test('manual stop waits for final result; cancel discards words', () => {
  const { session, recognition: r, events } = setup()
  r.onstart(); session.stop()
  assert.equal(r.stopped, true)
  r.onresult({ results: [[{ transcript: 'First part ' }], [{ transcript: 'second part' }]] }); r.onend()
  assert.deepEqual(events.at(-1), ['complete', 'First part second part'])
  const other = setup(); other.recognition.onstart()
  other.recognition.onresult({ results: [[{ transcript: 'discard me' }]] })
  other.session.cancel(); other.recognition.onend()
  assert.equal(other.events.some(e => e[0] === 'complete'), false)
})
