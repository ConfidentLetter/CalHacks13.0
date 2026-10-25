import test from 'node:test'
import assert from 'node:assert/strict'

test('deletion waits for acknowledgement, removes the cached record, and reports extension errors', async () => {
  let listener
  let sent
  globalThis.window = {
    location: { origin: 'http://localhost:5173' },
    addEventListener: (_type, fn) => { listener = fn },
    postMessage: (msg) => { sent = msg },
  }
  const { bridge, startBridge, getBridgeState } = await import('../../services/extensionBridge.js')
  startBridge()
  const receive = (msg) => listener({ source: window, origin: window.location.origin, data: { source: 'synapse-extension', ...msg } })
  receive({ type: 'readings', payload: { items: [{ id: 'a' }] } })
  let finished = false
  const deletion = bridge.deleteReading('a').then(() => { finished = true })
  await Promise.resolve()
  assert.equal(finished, false)
  receive({ type: 'mutation-result', requestId: sent.requestId, payload: { deletedIds: ['a'] } })
  await deletion
  assert.deepEqual(getBridgeState().readings, [])
  const failed = bridge.deleteReading('b')
  receive({ type: 'mutation-result', requestId: sent.requestId, payload: { error: 'Storage failed' } })
  await assert.rejects(failed, /Storage failed/)
  delete globalThis.window
})
