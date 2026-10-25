import { useMemo } from 'react'
import katex from 'katex'
import { parseMathText } from '../shared/mathTextParser'
import { cx } from '../../utils/format'

/**
 * Renders a verbatim LaTeX string with KaTeX. If KaTeX cannot parse it, the exact string is shown in
 * LaTeX text instead — never corrected, never trimmed.
 */
export function Latex({ value, kind = 'math', className, size = 'md', displayMode = false }) {
  const html = useMemo(() => {
    if (value == null || value === '' || kind === 'text' || kind === 'mixed') return null
    try {
      return katex.renderToString(String(value), { throwOnError: true, strict: 'ignore', output: 'htmlAndMathml', displayMode })
    } catch {
      const escapes = { '\\': '\\textbackslash{}', '{': '\\{', '}': '\\}', '$': '\\$', '&': '\\&', '#': '\\#', '%': '\\%', '_': '\\_', '^': '\\textasciicircum{}', '~': '\\textasciitilde{}' }
      const literal = String(value).replace(/[\\{}$&#%_^~]/g, char => escapes[char])
      return katex.renderToString(`\\text{${literal}}`, { throwOnError: false, strict: 'ignore', output: 'htmlAndMathml' })
    }
  }, [value, kind, displayMode])

  if (value == null || value === '') return null
  if (kind === 'text' || kind === 'mixed') {
    return <span className={className}>{parseMathText(value).map((token, i) => token.type === 'math'
      ? <Latex key={i} value={token.value} displayMode={token.display} size={size} />
      : <span key={i}>{token.value}</span>)}</span>
  }
  if (html == null) {
    return (
      <code className={cx('font-mono text-[0.95em] break-words whitespace-pre-wrap text-olive', className)}>{value}</code>
    )
  }
  return (
    <span
      className={cx(
        'latex max-w-full',
        displayMode ? 'block overflow-x-auto py-1' : 'inline-block align-baseline',
        size === 'sm' && 'latex-sm',
        className,
      )}
      // KaTeX output is generated locally from the string above; it contains no user HTML.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
