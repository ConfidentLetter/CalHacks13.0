import { getDocument, GlobalWorkerOptions } from './vendor/pdfjs/pdf.min.mjs'
GlobalWorkerOptions.workerSrc = chrome.runtime.getURL('vendor/pdfjs/pdf.worker.min.mjs')

async function parse(url) {
  let task
  const controller = new AbortController()
  const timeout = setTimeout(() => {
    controller.abort()
    task?.destroy().catch(() => {})
  }, 25000)
  try {
    if (!/^https?:$/.test(new URL(url).protocol)) throw new Error('Open an online PDF on an approved study site')
    const response = await fetch(url, { credentials: 'include', signal: controller.signal })
    if (!response.ok) throw new Error(`PDF download failed (HTTP ${response.status})`)
    const reader = response.body.getReader()
    const chunks = []
    let bytes = 0
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      bytes += value.length
      if (bytes > 20 * 1024 * 1024) { await reader.cancel(); throw new Error('PDF is larger than 20 MB') }
      chunks.push(value)
    }
    const data = new Uint8Array(bytes)
    let offset = 0
    for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.length }
    task = getDocument({ data, isEvalSupported: false, useWasm: false })
    task.onPassword = () => { task.destroy().catch(() => {}) }
    const doc = await task.promise
    const texts = []
    let length = 0
    for (let i = 1; i <= Math.min(doc.numPages, 10) && length < 4000; i++) {
      const page = await doc.getPage(i)
      const content = await page.getTextContent()
      const text = content.items.map(item => item.str || '').join(' ').replace(/\s+/g, ' ').trim()
      if (text) { texts.push(`[Page ${i}] ${text}`); length += text.length }
      page.cleanup()
    }
    const text = texts.join('\n').slice(0, 4000)
    return { pages: doc.numPages, text, scanned: !text, error: null }
  } catch (err) {
    return { pages: 0, text: '', error: err.message || 'Could not extract this PDF' }
  } finally {
    clearTimeout(timeout)
    try { await task?.destroy() } catch { /* failed parser already reported above */ }
  }
}
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (sender.id !== chrome.runtime.id || msg?.target !== 'pdf-offscreen' || msg.type !== 'pdf:parse') return false
  parse(msg.url).then(reply, () => reply({ error: 'Could not extract this PDF', text: '', pages: 0 }))
  return true
})
