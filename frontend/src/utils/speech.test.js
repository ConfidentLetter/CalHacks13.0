import assert from 'node:assert/strict'
import test from 'node:test'
import { pickVoice, spokenText } from './speech.js'

test('reads exponents, primes and equals as words', () => {
  assert.equal(spokenText("f'(x) = 4(3x^2 + 1)^3"), 'f prime of x equals 4 times the quantity 3 x squared plus 1, cubed')
})

test('strips LaTeX braces, backslashes and quotes', () => {
  assert.equal(spokenText('the line "f(x)=(3x^{2}+1)^{4}" is fine'), 'the line f of x equals the quantity 3 x squared plus 1, to the power 4 is fine')
  assert.equal(spokenText('\\frac{1}{2} and \\sqrt{x}'), '1 over 2 and the square root of x')
})

test('leaves ordinary prose and hyphenated words alone', () => {
  assert.equal(spokenText('Your crossed-out line shows the right instinct.'), 'Your crossed-out line shows the right instinct.')
  assert.equal(spokenText('In the photo from 03:45, look at L1.'), 'In the photo from 03:45, look at L1.')
})

test('reads a single bracketed number as a product', () => {
  assert.equal(spokenText("f'(1) = 4(4)^3 = 256"), 'f prime of 1 equals 4 times 4 cubed equals 256')
})

test('reads dashes between numbers as minus and keeps times', () => {
  assert.equal(spokenText('x - 1 = 5 − 2'), 'x minus 1 equals 5 minus 2')
})

const v = (name, lang, extra = {}) => ({ name, lang, localService: true, default: false, ...extra })

test('prefers a natural en-US voice over the system default', () => {
  const voices = [v('Tingting', 'zh-CN', { default: true }), v('Fred', 'en-US'), v('Samantha', 'en-US'), v('Daniel', 'en-GB')]
  assert.equal(pickVoice(voices).name, 'Samantha')
})

test('falls back to any English voice, then to null', () => {
  assert.equal(pickVoice([v('Tingting', 'zh-CN'), v('Daniel', 'en-GB')]).name, 'Daniel')
  assert.equal(pickVoice([v('Tingting', 'zh-CN')]), null)
  assert.equal(pickVoice([]), null)
})
