// Pip's replies are read aloud by the browser's speech synthesis. The text on screen keeps its math notation;
// spokenText() turns that notation into words so "x^2" is read "x squared" instead of "x caret 2".

const PREFERRED_VOICES = ['Samantha', 'Ava', 'Allison', 'Susan', 'Zoe', 'Google US English', 'Microsoft Aria', 'Microsoft Jenny']
// macOS novelty voices that ship with English locales but are no good for tutoring.
const NOVELTY_VOICES = /^(Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Good News|Jester|Organ|Superstar|Trinoids|Whisper|Wobble|Zarvox|Fred|Junior|Ralph|Kathy)\b/

const LATEX_WORDS = { cdot: ' times ', times: ' times ', div: ' divided by ', pi: ' pi ', theta: ' theta ', infty: ' infinity ', le: ' at most ', leq: ' at most ', ge: ' at least ', geq: ' at least ', neq: ' not equal to ' }

function exponentWord(power) {
  const p = power.trim()
  if (p === '2') return ' squared'
  if (p === '3') return ' cubed'
  return ` to the power ${p}`
}

// Mathy parentheses are read the way people say them: "4(3x+1)" → "4 times the quantity 3x+1,", "4(4)" → "4 times 4".
// Parenthesised prose keeps its parentheses. ⦇ marks an implicit product, resolved once the parens are gone.
function readParens(text) {
  let prev
  let out = text
  do {
    prev = out
    out = out.replace(/\(([^()]*)\)/g, (whole, inner) => {
      if (/[A-Za-z]{3,}/.test(inner)) return `⦅${inner}⦆`
      return /[-+=−*/]/.test(inner.trim().slice(1)) ? ` ⦇the quantity ${inner}, ` : ` ⦇${inner} `
    })
  } while (out !== prev)
  return out
    .replace(/([A-Za-z0-9])\s*⦇/g, '$1 times ')
    .replace(/⦇/g, '')
    .replace(/⦅/g, '(')
    .replace(/⦆/g, ')')
}

export function spokenText(text) {
  if (!text) return ''
  let s = String(text)
    .replace(/["“”`]/g, '')
    .replace(/\\(?:left|right)\b/g, '')
    .replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, ' $1 over $2 ')
    .replace(/\\sqrt\{([^{}]*)\}/g, ' the square root of $1 ')
    .replace(/\\([A-Za-z]+)/g, (_, word) => LATEX_WORDS[word] ?? ` ${word} `)
    .replace(/(?<![A-Za-z])([A-Za-z])(['′]?)\(([^()\s]{1,3})\)/g, (_, f, prime, arg) => ` ${f}${prime ? ' prime' : ''} of ${arg} `)
  s = readParens(s)
    .replace(/\s*\^\s*\{([^{}]*)\}/g, (_, p) => exponentWord(p))
    .replace(/\s*\^\s*([A-Za-z0-9]+)/g, (_, p) => exponentWord(p))
    .replace(/[{}\\]/g, ' ')
    .replace(/\s*=\s*/g, ' equals ')
    .replace(/\s*\+\s*/g, ' plus ')
    .replace(/\s*−\s*/g, ' minus ')
    .replace(/\s+-\s+/g, ' minus ')
    .replace(/(\d)-(\d)/g, '$1 minus $2')
    .replace(/\s*[*·×]\s*/g, ' times ')
    .replace(/(\d)([a-z])(?![A-Za-z])/g, '$1 $2')
  return s.replace(/\s+([.,;:!?])/g, '$1').replace(/\s+/g, ' ').trim()
}

// A natural English voice: a known good one first, then any en-US, then any English voice.
export function pickVoice(voices) {
  const usable = (voices || []).filter((v) => /^en[-_]/i.test(v.lang) && !NOVELTY_VOICES.test(v.name))
  for (const name of PREFERRED_VOICES) {
    const hit = usable.find((v) => v.name.startsWith(name) && /^en[-_]US/i.test(v.lang))
    if (hit) return hit
  }
  return usable.find((v) => /^en[-_]US/i.test(v.lang)) || usable[0] || null
}
