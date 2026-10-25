import test from 'node:test'
import assert from 'node:assert/strict'
import { deleteReadingCopies } from './deleteReading.js'

test('a synced extension record deletes backend and local copies before succeeding', async () => {
  const calls = []
  await deleteReadingCopies({ id: 'a', source: 'extension' }, {
    remoteItems: [{ id: 'a' }], extensionItems: [{ id: 'a', synced: true }],
    deleteRemote: async (id) => calls.push(`remote:${id}`),
    deleteLocal: async (id) => calls.push(`local:${id}`),
  })
  assert.deepEqual(calls, ['remote:a', 'local:a'])
})
test('an unsynced local record can be deleted without an online backend', async () => {
  await deleteReadingCopies({ id: 'a', source: 'extension', synced: false }, {
    remoteItems: [], extensionItems: [{ id: 'a', synced: false }],
    deleteRemote: async () => assert.fail('should not contact backend'), deleteLocal: async () => {},
  })
})
test('backend failure is reported instead of claiming a successful delete', async () => {
  await assert.rejects(deleteReadingCopies({ id: 'a', source: 'extension' }, {
    remoteItems: [{ id: 'a' }], extensionItems: [],
    deleteRemote: async () => { throw new Error('offline') }, deleteLocal: async () => {},
  }), /offline/)
})
test('extension deletion must be acknowledged', async () => {
  await assert.rejects(deleteReadingCopies({ id: 'a', source: 'backend' }, {
    remoteItems: [{ id: 'a' }], extensionItems: [{ id: 'a' }],
    deleteRemote: async () => {}, deleteLocal: async () => { throw new Error('extension unavailable') },
  }), /extension unavailable/)
})
