// Small grayscale samples stay on the device; only stable changed pages are uploaded.
export class FrameGate {
  constructor({ stableMs = 2000, gapMs = 10000 } = {}) {
    this.stableMs = stableMs
    this.gapMs = gapMs
    this.previous = null
    this.accepted = null
    this.lastMotion = 0
    this.lastAttempt = -Infinity
  }

  difference(a, b) {
    if (!a || !b || a.length !== b.length) return 1
    let changed = 0
    for (let i = 0; i < a.length; i++) if (Math.abs(a[i] - b[i]) > 18) changed++
    return changed / a.length
  }

  sample(gray, at) {
    if (this.difference(gray, this.previous) > 0.01) this.lastMotion = at
    this.previous = gray.slice()
    if (at - this.lastMotion < this.stableMs) return { ready: false, phase: 'Waiting for your writing to settle…' }
    if (this.accepted && this.difference(gray, this.accepted) < 0.003) {
      return { ready: false, phase: 'Your turn — write on the page or send a reply below.' }
    }
    if (at - this.lastAttempt < this.gapMs) return { ready: false, phase: 'Watching for your next step…' }
    return { ready: true, phase: 'Reading your next step…' }
  }

  attempt(at) { this.lastAttempt = at }
  accept(gray) { this.accepted = gray.slice() }
}

export function grayscale(video, canvas) {
  canvas.width = 160
  canvas.height = 120
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  ctx.drawImage(video, 0, 0, 160, 120)
  const pixels = ctx.getImageData(0, 0, 160, 120).data
  const result = new Uint8Array(160 * 120)
  for (let i = 0; i < result.length; i++) {
    result[i] = (pixels[4 * i] + pixels[4 * i + 1] + pixels[4 * i + 2]) / 3
  }
  return result
}
