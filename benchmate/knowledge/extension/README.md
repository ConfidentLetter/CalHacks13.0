# BenchMate Study Mode (Chrome extension, Manifest V3)

Load unpacked: `chrome://extensions` → Developer mode → "Load unpacked" → pick this folder.

- Popup toggle **Study mode** (off by default). Options page holds the domain allow-list.
- After 30 s on an allow-listed page, the service worker POSTs `{url, text, seconds}` to `http://localhost:8000/read`
  (T5's server → `knowledge.record_read`). Progress is re-posted every minute and when you leave the page.
- Chrome's PDF viewer gives content scripts no text, so PDFs are sent with `text: null` and `#page=N` in the URL
  when present; `record_read` downloads/ingests the PDF itself and resolves the page from the fragment.
- Privacy: the endpoint is forced to localhost/127.0.0.1; nothing else is contacted.
