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
