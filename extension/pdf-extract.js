// PDF text extraction using PDF.js (Worker compatible)
// Detects PDFs, extracts text page-by-page, detects scanned pages

const PDFExtractor = (() => {
  const WORKER_URL = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
  let pdfjs = null

  async function loadPdfJs() {
    if (pdfjs) return pdfjs
    // Load PDF.js library using importScripts (for service workers)
    try {
      importScripts('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js')
      if (typeof self.pdfjsLib === 'undefined') throw new Error('PDF.js failed to load')
      pdfjs = self.pdfjsLib
      pdfjs.GlobalWorkerOptions.workerSrc = WORKER_URL
      return pdfjs
    } catch (err) {
      throw new Error(`Failed to load PDF.js: ${err.message}`)
    }
  }

  async function extractFromUrl(url) {
    try {
      const pdf = await loadPdfJs()
      const doc = await pdf.getDocument(url).promise
      const text = await extractAllPages(pdf, doc)
      return { pages: doc.numPages, text, error: null, scanned: false }
    } catch (err) {
      return { pages: 0, text: '', error: String(err.message || err), scanned: false }
    }
  }

  async function extractFromArrayBuffer(buffer, filename) {
    try {
      const pdf = await loadPdfJs()
      const doc = await pdf.getDocument({ data: buffer }).promise
      const text = await extractAllPages(pdf, doc)
      const scanned = await detectScannedPages(pdf, doc)
      return { pages: doc.numPages, text, error: null, scanned, filename }
    } catch (err) {
      return { pages: 0, text: '', error: String(err.message || err), scanned: false }
    }
  }

  async function extractAllPages(pdf, doc) {
    const MAX_PAGES = 500
    const maxPages = Math.min(doc.numPages, MAX_PAGES)
    const texts = []

    for (let i = 1; i <= maxPages; i++) {
      try {
        const page = await doc.getPage(i)
        const content = await page.getTextContent()
        const pageText = content.items
          .map(item => (item.str || '').trim())
          .filter(s => s)
          .join(' ')
          .replace(/\s+/g, ' ')
        if (pageText) texts.push(`[Page ${i}] ${pageText}`)
      } catch {
        texts.push(`[Page ${i}: unreadable]`)
      }
      if (i % 20 === 0) await new Promise(r => setTimeout(r, 0))
    }
    return texts.join('\n')
  }

  async function detectScannedPages(pdf, doc) {
    const SAMPLE_SIZE = Math.min(5, doc.numPages)
    let unreadable = 0
    for (let i = 1; i <= SAMPLE_SIZE; i++) {
      try {
        const page = await doc.getPage(i)
        const content = await page.getTextContent()
        const textLen = content.items.reduce((s, it) => s + (it.str || '').length, 0)
        if (textLen < 50) unreadable++
      } catch {
        unreadable++
      }
    }
    return unreadable / SAMPLE_SIZE > 0.6
  }

  return { extractFromUrl, extractFromArrayBuffer }
})()
