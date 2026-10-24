import { useState } from 'react'
import { domainOf } from '../../utils/format'

const TONES = ['bg-butter text-honey', 'bg-sage text-sage-ink', 'bg-paper text-olive']

/**
 * Shows the favicon captured by the extension when available. Otherwise renders a
 * letter avatar, so no third-party favicon service ever sees the user's domains.
 */
export function Favicon({ url, src, size = 32 }) {
  const [failed, setFailed] = useState(false)
  const domain = domainOf(url)
  const tone = TONES[[...domain].reduce((a, c) => a + c.charCodeAt(0), 0) % TONES.length]

  if (src && !failed) {
    return (
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        onError={() => setFailed(true)}
        className="shrink-0 rounded-lg border border-olive/12 bg-white p-1"
        style={{ width: size, height: size }}
      />
    )
  }
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center rounded-lg border border-olive/12 text-xs font-semibold uppercase ${tone}`}
      style={{ width: size, height: size }}
    >
      {domain.charAt(0) || '?'}
    </span>
  )
}
