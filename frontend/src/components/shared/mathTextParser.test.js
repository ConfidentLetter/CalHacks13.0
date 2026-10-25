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
    { type: 'math', value: 'N_21', display: false },
    { type: 'math', value: 'm_{1}g', display: false },
    { type: 'math', value: 'f_s', display: false },
    { type: 'math', value: 'N_2', display: false },
    { type: 'math', value: 'm_{2}g', display: false },
    { type: 'math', value: 'N_12', display: false },
    { type: 'math', value: 'f_k', display: false },
    { type: 'math', value: 'f_s', display: false },
  ])
})

test('converts Unicode subscript digits and removes zero-width formatting marks', () => {
  assert.deepEqual(parseMathText('Fₓ = m₁aₓ\u200B'), [
    { type: 'math', value: 'F_{x} = m_{1}a_{x}', display: true },
  ])
})

test('leaves ordinary prose and currency untouched', () => {
  assert.deepEqual(parseMathText('The answer is $5.00.'), [
    { type: 'text', value: 'The answer is $5.00.' },
  ])
})
