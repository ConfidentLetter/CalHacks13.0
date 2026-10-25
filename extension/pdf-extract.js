// MV3 service workers have no DOM. Parse using our packaged PDF.js in an offscreen document.
const PDFExtractor = (() => {
  let creating
  async function extractFromUrl(url) {
    const contexts = await chrome.runtime.getContexts({
      contextTypes: ['OFFSCREEN_DOCUMENT'], documentUrls: [chrome.runtime.getURL('pdf-offscreen.html')],
    })
    if (!contexts.length) {
      if (!creating) creating = chrome.offscreen.createDocument({
        url: 'pdf-offscreen.html', reasons: ['DOM_PARSER'],
        justification: 'Extract study text from an approved PDF with the bundled PDF.js parser.',
      }).finally(() => { creating = null })
      await creating
    }
    const result = await chrome.runtime.sendMessage({ target: 'pdf-offscreen', type: 'pdf:parse', url })
    if (!result) throw new Error('PDF parser did not respond')
    return result
  }
  return { extractFromUrl }
})()
