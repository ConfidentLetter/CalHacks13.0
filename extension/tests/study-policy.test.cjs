const test = require('node:test')
const assert = require('node:assert/strict')
const policy = require('../study-policy.js')
const target = { tabId: 4, windowId: 2, url: 'https://school.edu/problems/1' }
const tab = { id: 4, windowId: 2, url: target.url, active: true }

test('session IDs accept only bounded simple identifiers', () => {
  assert.equal(policy.validSessionId('study-123_ab'), true)
  for (const value of ['', '../session', 'a'.repeat(101), null, 25]) assert.equal(policy.validSessionId(value), false)
})
test('interval must be an explicit supported choice of at least ten seconds', () => {
  for (const value of [10, 20, 30, 60]) assert.equal(policy.validInterval(value), true)
  for (const value of [0, 9, 11, 61, '10', NaN]) assert.equal(policy.validInterval(value), false)
})
test('capture binds the exact visible tab, focused window and original URL', () => {
  assert.equal(policy.matchesTarget(target, tab, true), true)
  for (const changed of [{ id: 8 }, { windowId: 3 }, { active: false }, { url: `${target.url}#other` }]) {
    assert.equal(policy.matchesTarget(target, { ...tab, ...changed }, true), false)
  }
  assert.equal(policy.matchesTarget(target, tab, false), false)
  assert.equal(policy.matchesTarget(target, null, true), false)
})
test('study capture rejects dashboard and sensitive pages including query routes', () => {
  const dashboard = 'http://localhost:5173'
  for (const url of ['chrome://settings', 'https://chromewebstore.google.com/detail/x', `${dashboard}/#/capture`, 'https://school.edu/account', 'https://school.edu/?next=checkout', 'https://school.edu/quizzes/3/take']) {
    assert.equal(policy.safeStudyUrl(url, dashboard), false, url)
  }
  assert.equal(policy.safeStudyUrl(target.url, dashboard), true)
})
test('due checks reject stopped, mismatched, busy and early work', () => {
  const state = { ...target, running: true, generation: 'a', intervalSec: 10, lastAttemptAt: 1000 }
  assert.equal(policy.isDue(state, tab, true, 11000, false), true)
  for (const changed of [{ running: false }, { lastAttemptAt: 10001 }, { busyUntil: 12000 }]) {
    assert.equal(policy.isDue({ ...state, ...changed }, tab, true, 11000, false), false)
  }
  assert.equal(policy.isDue(state, tab, true, 11000, true), false)
  assert.equal(policy.isCurrent(state, 'a'), true)
  assert.equal(policy.isCurrent({ ...state, running: false }, 'a'), false)
  assert.equal(policy.isCurrent(state, 'old'), false)
})
