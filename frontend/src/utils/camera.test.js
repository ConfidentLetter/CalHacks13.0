import assert from 'node:assert/strict'
import test from 'node:test'
import { videoConstraints } from './camera.js'

test('default camera prefers the back camera on phones and HD everywhere', () => {
  assert.deepEqual(videoConstraints(''), {
    facingMode: { ideal: 'environment' },
    width: { ideal: 1920 },
    height: { ideal: 1080 },
  })
})

test('an explicitly chosen camera is used exactly, without a facing preference', () => {
  assert.deepEqual(videoConstraints('abc123'), {
    deviceId: { exact: 'abc123' },
    width: { ideal: 1920 },
    height: { ideal: 1080 },
  })
})
