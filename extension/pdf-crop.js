// One-shot overlay: drag a rectangle over the PDF to set the area the observer compares.
// Sends only the rectangle (fractions of the viewport), never page content.
;(() => {
  if (document.getElementById('synapse-pdf-crop')) return
  const layer = document.createElement('div')
  layer.id = 'synapse-pdf-crop'
  layer.style.cssText = 'position:fixed;inset:0;z-index:2147483647;cursor:crosshair;background:rgb(73 70 56 / 0.18);font:13px system-ui,sans-serif'
  const tip = document.createElement('div')
  tip.textContent = 'Drag over the PDF page area. Esc cancels.'
  tip.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);padding:6px 12px;border-radius:4px;background:#fff9ed;color:#494638;border:1px solid #e3c75f'
  const box = document.createElement('div')
  box.style.cssText = 'position:fixed;border:2px solid #a4ba8d;background:rgb(248 229 160 / 0.25);display:none'
  layer.append(tip, box)
  document.documentElement.append(layer)

  let start = null
  const done = () => { layer.remove(); removeEventListener('keydown', onKey, true) }
  const onKey = (e) => { if (e.key === 'Escape') done() }
  addEventListener('keydown', onKey, true)
  layer.addEventListener('mousedown', (e) => {
    start = { x: e.clientX, y: e.clientY }
    Object.assign(box.style, { display: 'block', left: `${start.x}px`, top: `${start.y}px`, width: '0px', height: '0px' })
  })
  layer.addEventListener('mousemove', (e) => {
    if (!start) return
    Object.assign(box.style, { left: `${Math.min(start.x, e.clientX)}px`, top: `${Math.min(start.y, e.clientY)}px`,
      width: `${Math.abs(e.clientX - start.x)}px`, height: `${Math.abs(e.clientY - start.y)}px` })
  })
  layer.addEventListener('mouseup', (e) => {
    if (!start) return
    const rect = { x: Math.min(start.x, e.clientX) / innerWidth, y: Math.min(start.y, e.clientY) / innerHeight,
      width: Math.abs(e.clientX - start.x) / innerWidth, height: Math.abs(e.clientY - start.y) / innerHeight }
    done()
    // Errors (too small, site not approved) show in the popup's PDF status.
    chrome.runtime.sendMessage({ type: 'pdf:crop', url: location.href, rect }).catch(() => {})
  })
})()
