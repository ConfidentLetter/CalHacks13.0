import { test } from 'node:test'
import assert from 'node:assert/strict'
import { StudyView, resetSessionId } from './studyView.js'

test('Stop rejects a poll that started before capture stopped', () => {
  const view = new StudyView()
  const poll = view.readToken()
  view.freeze()
  assert.equal(view.isCurrent(poll), false)
  assert.equal(view.readToken(), null)
})

test('resuming accepts new reads without reviving old polls', () => {
  const view = new StudyView()
  const stale = view.readToken()
  view.freeze()
  view.resume()
  assert.equal(view.isCurrent(stale), false)
  assert.equal(view.isCurrent(view.readToken()), true)
})

test('screen reset retains session shared with the extension', () => {
  assert.equal(resetSessionId('extension-session', 'screen', () => 'new-id'), 'extension-session')
  assert.equal(resetSessionId('camera-session', 'camera', () => 'new-id'), 'new-id')
})
