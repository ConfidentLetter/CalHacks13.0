import { useMemo } from 'react'
import katex from 'katex'
import { cx } from '../../utils/format'

/**
 * Renders a verbatim LaTeX string with KaTeX. If KaTeX cannot parse it, the exact string is shown in
 * monospace instead — never corrected, never trimmed.
 */
export function Latex({ value, kind = 'math', className, size = 'md', displayMode = false }) {
  const html = useMemo(() => {
    if (!value || kind === 'text') return null
    try {
      return katex.renderToString(value, { throwOnError: true, strict: 'ignore', output: 'html', displayMode })
    } catch {
      return null
    }
  }, [value, kind, displayMode])

  if (!value) return null
  if (html == null) {
    return (
      <code className={cx('font-mono text-[0.95em] break-words whitespace-pre-wrap text-olive', className)}>{value}</code>
    )
  }
  return (
    <span
      className={cx(
        'latex max-w-full overflow-x-auto',
        displayMode ? 'block' : 'inline-block align-middle',
        size === 'sm' && 'latex-sm',
        className,
      )}
      // KaTeX output is generated locally from the string above; it contains no user HTML.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
