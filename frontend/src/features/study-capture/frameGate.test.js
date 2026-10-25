import { test } from 'node:test'
import assert from 'node:assert/strict'
import { FrameGate } from './frameGate.js'

const page = (value) => new Uint8Array(100).fill(value)

test('first page must settle, then an accepted unchanged page stays quiet', () => {
  const gate = new FrameGate()
  assert.equal(gate.sample(page(0), 0).ready, false)
  assert.equal(gate.sample(page(0), 2100).ready, true)
  gate.attempt(2100)
  gate.accept(page(0))
  assert.equal(gate.sample(page(0), 15000).ready, false)
})

test('writing restarts the stability window and respects request cooldown', () => {
  const gate = new FrameGate()
  gate.sample(page(0), 0)
  gate.attempt(2100)
  gate.accept(page(0))
  assert.equal(gate.sample(page(200), 8000).ready, false)
  assert.equal(gate.sample(page(200), 10100).ready, false)
  assert.equal(gate.sample(page(200), 12500).ready, true)
})

test('failed request can retry without falsely accepting the page', () => {
  const gate = new FrameGate()
  gate.sample(page(0), 0)
  gate.attempt(2100)
  assert.equal(gate.sample(page(0), 12500).ready, true)
})
