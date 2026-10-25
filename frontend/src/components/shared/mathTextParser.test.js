import katex from 'katex'
import assert from 'node:assert/strict'
import test from 'node:test'
import { parseMathText } from './mathTextParser.js'

test('parses inline and display LaTeX delimiters', () => {
  const tokens = parseMathText('Use $x^2$ and \\(y_1\\).\n$$\\frac{1}{2}$$')

  assert.deepEqual(tokens.filter(({ type }) => type === 'math'), [
    { type: 'math', value: 'x^2', display: false },
    { type: 'math', value: 'y_1', display: false },
    { type: 'math', value: '\\frac{1}{2}', display: true },
  ])
})

test('formats bare equations while preserving surrounding prose', () => {
  const tokens = parseMathText('Set x^2 + 1 = 5, then solve.')

  assert.deepEqual(tokens, [
    { type: 'text', value: 'Set ' },
    { type: 'math', value: 'x^2 + 1 = 5', display: false },
    { type: 'text', value: ', then solve.' },
  ])
})

test('formats bare LaTeX commands in prose', () => {
  assert.deepEqual(parseMathText('Try \\frac{1}{2} next.'), [
    { type: 'text', value: 'Try ' },
    { type: 'math', value: '\\frac{1}{2}', display: false },
    { type: 'text', value: ' next.' },
  ])
})

test('formats a standalone equation as display math and keeps line breaks', () => {
  const tokens = parseMathText('Check this:\nx^2 + 1 = 5')

  assert.deepEqual(tokens, [
    { type: 'text', value: 'Check this:' },
    { type: 'text', value: '\n' },
    { type: 'math', value: 'x^2 + 1 = 5', display: true },
  ])
})

test('formats force equations with sigma notation and implicit indexed masses', () => {
  assert.deepEqual(parseMathText('ΣF_x = f_s = m1 a_x'), [
    { type: 'math', value: String.raw`\sum F_x = f_s = m_{1} a_x`, display: true },
  ])
})

test('formats friction inequalities with Greek coefficients', () => {
  assert.deepEqual(parseMathText('f_s ≤ μ_s N'), [
    { type: 'math', value: String.raw`f_s \leq \mu_s N`, display: true },
  ])
  assert.deepEqual(parseMathText('f_s = μ_s m1 g'), [
    { type: 'math', value: String.raw`f_s = \mu_s m_{1} g`, display: true },
  ])
})

test('formats indexed terms in free-body diagram labels', () => {
  const tokens = parseMathText('Block 1 (N_21, m1g, f_s); block 2 (N_2, m2g, N_12, f_k, f_s, T).')

  assert.deepEqual(tokens.filter(({ type }) => type === 'math'), [
    { type: 'math', value: '1', display: false },
    { type: 'math', value: 'N_{21}', display: false },
    { type: 'math', value: 'm_{1}g', display: false },
    { type: 'math', value: 'f_s', display: false },
    { type: 'math', value: '2', display: false },
    { type: 'math', value: 'N_2', display: false },
    { type: 'math', value: 'm_{2}g', display: false },
    { type: 'math', value: 'N_{12}', display: false },
    { type: 'math', value: 'f_k', display: false },
    { type: 'math', value: 'f_s', display: false },
    { type: 'math', value: 'T', display: false },
  ])
})

test('converts Unicode subscript digits and removes zero-width formatting marks', () => {
  assert.deepEqual(parseMathText('Fₓ = m₁aₓ\u200B'), [
    { type: 'math', value: 'F_{x} = m_{1}a_{x}', display: true },
  ])
})

test('preserves currency wording while rendering its numeric value', () => {
  assert.deepEqual(parseMathText('The answer is $5.00.'), [
    { type: 'text', value: 'The answer is $' },
    { type: 'math', value: '5.00', display: false },
    { type: 'text', value: '.' },
  ])
})

test('keeps hyphenated prose and ordinals as plain text', () => {
  for (const text of ['Your crossed-out line is fine.', 'the power-rule step']) {
    assert.deepEqual(parseMathText(text).filter(({ type }) => type === 'math'), [], text)
  }
})

test('does not glue a following word onto a bare equation', () => {
  const math = parseMathText('the inside is 3x^2 + 1 and not just x').filter(({ type }) => type === 'math')
  assert.deepEqual(math.map(({ value }) => value), ['3x^2 + 1', 'x'])
})

test('still formats calculus notation with differentials', () => {
  const math = parseMathText('so dy/dx = 2x here, and sin x + 1 = 2 too').filter(({ type }) => type === 'math')
  assert.deepEqual(math.map(({ value }) => value), ['dy/dx = 2x', String.raw`\sin x + 1 = 2`])
})

test('renders standalone numbers, decimals, percentages and mathematical symbols', () => {
  const tokens = parseMathText('Use 2 blocks, 9.81 m/s, 50%, θ and ∞.')
  const plain = tokens.filter(t => t.type === 'text').map(t => t.value).join('')
  assert.doesNotMatch(plain, /[0-9θ∞%]/)
})

test('renders standalone variable labels without converting ordinary prose', () => {
  const tokens = parseMathText('Compare x with T and N; this is a sentence.')
  assert.deepEqual(tokens.filter(t => t.type === 'math').map(t => t.value), ['x', 'T', 'N'])
  assert.match(tokens.filter(t => t.type === 'text').map(t => t.value).join(''), /this is a sentence/)
})

test('renders plain square roots and function arguments as complete math', () => {
  const tokens = parseMathText('Escape speed is v_esc = sqrt(2GM/R).')
  assert.ok(tokens.some(t => t.type === 'math' && t.value === String.raw`v_{esc} = \sqrt{2GM/R}`))
})

test('accepts numeric and empty render values', () => {
  assert.deepEqual(parseMathText(42), [{ type: 'math', value: '42', display: false }])
  assert.deepEqual(parseMathText(null), [])
})


test('preserves prose apostrophes and URLs while formatting their surrounding numbers', () => {
  const tokens = parseMathText("Pip's 2 examples: https://example.com/page/123")
  assert.deepEqual(tokens.filter(t => t.type === 'math').map(t => t.value), ['2'])
  assert.ok(tokens.some(t => t.type === 'text' && t.value.includes('https://example.com/page/123')))
})


test('keeps multi-character subscripts together in LaTeX', () => {
  const math = parseMathText('Escape speed is v_esc = sqrt(2GM/R).').filter(t => t.type === 'math')
  assert.equal(math[0].value, String.raw`v_{esc} = \sqrt{2GM/R}`)
})


test('all recognized numeric and symbolic fragments are valid KaTeX', () => {
  const samples = [
    'Use 2 blocks, 9.81 m/s, 50%, θ and ∞.',
    'Escape speed is v_esc = sqrt(2GM/R).',
    'Compare x with T and N; f(x) = x^2 + 1.',
    'The 3rd-4th steps use 0s and 20ms.',
    'Symbols √ ∫ ∑ ∂ ∇ ≈ ± = < >.',
  ]
  for (const source of samples) {
    for (const token of parseMathText(source).filter(t => t.type === 'math')) {
      assert.doesNotThrow(() => katex.renderToString(token.value, { throwOnError: true }), `${source}: ${token.value}`)
    }
  }
})


test('renders LaTeX text and unit commands without exposing their source', () => {
  assert.deepEqual(parseMathText(String.raw`Mass uses \mathrm{kg} and \text{two blocks}.`).filter(t => t.type === 'math').map(t => t.value), [String.raw`\mathrm{kg}`, String.raw`\text{two blocks}`])
})
