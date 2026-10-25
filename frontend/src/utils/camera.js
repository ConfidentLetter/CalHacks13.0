/**
 * macOS Desk View exposes virtual cameras named "MacBook Air桌上视角相机" / "…的iPhone的桌上视角相机"
 * (English systems: "… Desk View Camera"): a perspective-corrected top-down view of the desk — the demo camera.
 */
export function isDeskView(label) {
  return /桌上视角|desk\s*view/i.test(label || '')
}

export function findDeskView(devices) {
  return (devices || []).find((d) => isDeskView(d.label)) || null
}

/**
 * getUserMedia video constraints. With no camera picked, ask for the back camera: on a phone the default is the
 * selfie camera, which can't see the page (laptop webcams ignore facingMode). A picked camera is used exactly.
 */
export function videoConstraints(sourceId) {
  const size = { width: { ideal: 1920 }, height: { ideal: 1080 } }
  return sourceId ? { deviceId: { exact: sourceId }, ...size } : { facingMode: { ideal: 'environment' }, ...size }
}
