export function conversationLink(item, messages) {
  const match = [...messages].reverse().find((m) =>
    (item.messageId && m.id === item.messageId) ||
    (item.type === 'chat' && m.role === 'user' && m.content === item.detail) ||
    (item.type === 'reading' && m.sources?.some((s) => s.type === 'reading' && s.url === (item.url || item.detail))),
  )
  if (match) return `#/tutor?message=${encodeURIComponent(match.id)}`
  const topic = item.type === 'chat' ? item.detail : item.type === 'reading'
    ? `Help me understand "${item.title}" (${item.url || item.detail}).`
    : `Help me work through "${item.title}". ${item.detail || ''}`
  return `#/tutor?topic=${encodeURIComponent(topic)}`
}

export function savedConversationLink(item) {
  let messages = []
  try { messages = JSON.parse(localStorage.getItem('synapse.chat.v2')) || [] } catch { /* unavailable storage */ }
  return conversationLink(item, messages)
}
