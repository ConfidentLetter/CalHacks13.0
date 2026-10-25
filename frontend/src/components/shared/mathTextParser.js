const EXPLICIT_MATH = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\\)\$(?!\s)[^$\n]+?\$)/g
const MATH_TERM = String.raw`(?:\\[A-Za-z]+(?:\{[^{}]*\})*|(?:Σ|∑)?(?:\d+(?:\.\d+)?)?[A-Za-zΑ-Ωα-ω](?:[A-Za-z0-9Α-Ωα-ω]*)(?:[_^](?:\{[^{}]*\}|[A-Za-z0-9+-]+))?|\d+(?:\.\d+)?)`
const EQUATION = new RegExp(
  `${MATH_TERM}(?:\\s*(?:=|<=|>=|≤|≥|≠|<|>|[+\\-×÷*/])\\s*${MATH_TERM})+`,
)
const LATEX_COMMAND = String.raw`\\(?:frac|sqrt|sum|prod|int|lim|sin|cos|tan|log|ln|pi|theta|alpha|beta|gamma|delta|Delta|cdot|times|leq|geq|neq|approx|infty|pm|partial|nabla|dots|ldots|overline|mathbf|mathrm|text)\b(?:\{[^{}]*\})*(?:[_^](?:\{[^{}]*\}|[A-Za-z0-9+-]+))*`
const MATH_ATOM = String.raw`(?:[A-Za-zΑ-Ωα-ω](?:[_^](?:\{[^{}]*\}|[A-Za-z0-9+-]+))|[A-Za-z]\d+[A-Za-z])`
const INLINE_MATH = new RegExp(`${EQUATION.source}|${LATEX_COMMAND}|${MATH_ATOM}`, 'g')
const FORMULA_LINE = /^[A-Za-zΑ-Ωα-ω0-9\s\\{}()[\].,=<>_^+\-*/×÷%|Σ∑−≤≥≠₀-₉ₓ]+$/
const LATEX_WORDS = new Set(['frac', 'sqrt', 'sum', 'prod', 'int', 'lim', 'sin', 'cos', 'tan', 'log', 'ln', 'mu', 'leq', 'geq', 'neq', 'times', 'div'])

const SUBSCRIPT_CHARS = {
  '₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4', '₅': '5',
  '₆': '6', '₇': '7', '₈': '8', '₉': '9', 'ₓ': 'x',
}
const GREEK_COMMANDS = {
  'α': String.raw`\alpha`, 'β': String.raw`\beta`, 'γ': String.raw`\gamma`,
  'δ': String.raw`\delta`, 'Δ': String.raw`\Delta`, 'θ': String.raw`\theta`,
  'λ': String.raw`\lambda`, 'μ': String.raw`\mu`, 'π': String.raw`\pi`,
  'ρ': String.raw`\rho`, 'σ': String.raw`\sigma`, 'τ': String.raw`\tau`,
  'φ': String.raw`\phi`, 'ω': String.raw`\omega`,
}

function normalizeMath(value) {
  return value
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, '')
    .replace(/[₀-₉ₓ]+/g, (chars) => `_{${[...chars].map((char) => SUBSCRIPT_CHARS[char]).join('')}}`)
    .replace(/Σ(?=[A-Za-z])/g, String.raw`\sum `)
    .replace(/[α-ωΔ]/g, (letter) => GREEK_COMMANDS[letter] || letter)
    .replace(/≤/g, String.raw`\leq`)
    .replace(/≥/g, String.raw`\geq`)
    .replace(/≠/g, String.raw`\neq`)
    .replace(/×/g, String.raw`\times`)
    .replace(/÷/g, String.raw`\div`)
    .replace(/−/g, '-')
    .replace(/([A-Za-z])(\d+)(?=[A-Za-z]|\s|$)/g, '$1_{$2}')
}

// A run of 2+ letters is prose unless it is a LaTeX command, a known function name, or a differential (dx, dt).
function containsProse(value) {
  for (const { 0: word, index } of value.matchAll(/[A-Za-z]{2,}/g)) {
    if (value[index - 1] === '\\') continue
    if (LATEX_WORDS.has(word) || /^d[a-z]$/.test(word)) continue
    return true
  }
  return false
}

function isFormulaLine(value) {
  if (!value || !FORMULA_LINE.test(value) || !/[=<>≤≥≠^_\\+*/×÷-]/.test(value)) return false
  return [...value.matchAll(/[A-Za-z]+/g)].every(([word]) => word.length === 1 || LATEX_WORDS.has(word))
}

function parsePlainText(value) {
  const tokens = []
  const lines = value.split(/(\r?\n)/)

  for (const line of lines) {
    if (/^\r?\n$/.test(line)) {
      tokens.push({ type: 'text', value: line })
      continue
    }

    const trimmed = line.trim()
    const normalized = normalizeMath(trimmed)
    if (isFormulaLine(normalized)) {
      const leading = line.match(/^\s*/)[0]
      const trailing = line.match(/\s*$/)[0]
      if (leading) tokens.push({ type: 'text', value: leading })
      tokens.push({ type: 'math', value: normalized, display: true })
      if (trailing) tokens.push({ type: 'text', value: trailing })
      continue
    }

    let lastIndex = 0
    INLINE_MATH.lastIndex = 0
    for (const match of line.matchAll(INLINE_MATH)) {
      const start = match.index
      const end = start + match[0].length
      if (/[A-Za-z0-9]/.test(line[start - 1] || '') || /[A-Za-z0-9]/.test(line[end] || '')) continue
      if (containsProse(match[0])) continue
      if (start > lastIndex) tokens.push({ type: 'text', value: line.slice(lastIndex, start) })
      tokens.push({ type: 'math', value: normalizeMath(match[0]), display: false })
      lastIndex = end
    }
    if (lastIndex < line.length) tokens.push({ type: 'text', value: line.slice(lastIndex) })
  }

  return tokens
}

function explicitMathToken(value) {
  if (value.startsWith('$$') && value.endsWith('$$')) {
    return { type: 'math', value: value.slice(2, -2), display: true }
  }
  if (value.startsWith('\\[') && value.endsWith('\\]')) {
    return { type: 'math', value: value.slice(2, -2), display: true }
  }
  if (value.startsWith('\\(') && value.endsWith('\\)')) {
    return { type: 'math', value: value.slice(2, -2), display: false }
  }
  return { type: 'math', value: value.slice(1, -1), display: false }
}

export function parseMathText(value) {
  const tokens = []
  let lastIndex = 0

  for (const match of value.matchAll(EXPLICIT_MATH)) {
    const start = match.index
    if (start > lastIndex) tokens.push(...parsePlainText(value.slice(lastIndex, start)))
    tokens.push(explicitMathToken(match[0]))
    lastIndex = start + match[0].length
  }

  if (lastIndex < value.length) tokens.push(...parsePlainText(value.slice(lastIndex)))
  return tokens
}
