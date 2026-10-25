const test = require('node:test')
const assert = require('node:assert/strict')
const { SAMPLE_SIZE, changedTiles, grayscale } = require('../tile-diff.js')

function signature(value = 0) {
  return new Array(SAMPLE_SIZE * SAMPLE_SIZE).fill(value)
}

test('grayscale signatures preserve the 64×64 sample dimensions', () => {
  const rgba = new Uint8ClampedArray(SAMPLE_SIZE * SAMPLE_SIZE * 4)
  for (let i = 0; i < rgba.length; i += 4) rgba.set([10, 20, 30, 255], i)
  const result = grayscale(rgba)
  assert.equal(result.length, SAMPLE_SIZE * SAMPLE_SIZE)
  assert.equal(result[0], Math.round(0.299 * 10 + 0.587 * 20 + 0.114 * 30))
})

test('tile diff reports only 4×4 regions with at least five changed sample pixels', () => {
  const previous = signature()
  const current = signature()
  const tile = 5
  const left = (tile % 4) * 16
  const top = Math.floor(tile / 4) * 16
  for (let i = 0; i < 4; i++) current[(top * SAMPLE_SIZE) + left + i] = 255
  assert.deepEqual(changedTiles(previous, current), [])
  current[(top * SAMPLE_SIZE) + left + 4] = 255
  assert.deepEqual(changedTiles(previous, current), [tile])
})

test('a missing or incompatible baseline treats all sixteen tiles as changed', () => {
  assert.deepEqual(changedTiles(null, signature()), Array.from({ length: 16 }, (_, i) => i))
  assert.deepEqual(changedTiles(new Array(1), signature()), Array.from({ length: 16 }, (_, i) => i))
  assert.deepEqual(changedTiles(signature(), [1]), [])
})
