import test from 'node:test'
import assert from 'node:assert/strict'
import { conversationLink } from './links.js'
test('journal questions link to the saved user message', () => {
  assert.equal(conversationLink({ type: 'chat', detail: 'Why?' }, [{ id: 'm1', role: 'user', content: 'Why?' }]), '#/tutor?message=m1')
})
test('readings link to the conversation that cited that page', () => {
  assert.equal(conversationLink({ type: 'reading', title: 'Physics', url: 'https://example.com' }, [{ id: 'm2', sources: [{ type: 'reading', url: 'https://example.com' }] }]), '#/tutor?message=m2')
})
test('items with no saved conversation open an editable context prompt', () => {
  const href = conversationLink({ type: 'reading', title: 'Physics', url: 'https://example.com' }, [])
  assert.match(decodeURIComponent(href), /topic=Help me understand "Physics"/)
})
