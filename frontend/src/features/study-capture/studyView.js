// In-flight poll results cannot repaint a camera session after Stop or a source change.
export class StudyView {
  constructor() { this.epoch = 0; this.frozen = false }
  freeze() { this.epoch++; this.frozen = true }
  resume() { if (this.frozen) { this.epoch++; this.frozen = false } }
  readToken() { return this.frozen ? null : this.epoch }
  isCurrent(token) { return token !== null && !this.frozen && token === this.epoch }
}

export function resetSessionId(current, mode, create) {
  // The extension keeps posting to its shared screen ID; reset its backend state in place.
  return mode === 'screen' ? current : create()
}
