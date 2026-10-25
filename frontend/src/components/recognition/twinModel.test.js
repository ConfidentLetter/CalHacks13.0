import assert from 'node:assert/strict'
import test from 'node:test'
import { inkRegion, lineFromStep, lineFromTwin, mergeStepsWithTwin } from './twinModel.js'

const estimated = { id: 'L1', order: 0, latex: 'x=1', bbox: [0, 10, 800, 40], bbox_estimated: true }
const measured = { id: 'L2', order: 1, latex: 'y=2', bbox: [100, 300, 200, 40] }

test('a hand-held read keeps the "position estimated" flag from the twin', () => {
  assert.equal(lineFromTwin(estimated).bboxEstimated, true)
  assert.equal(lineFromTwin(measured).bboxEstimated, false)
})

test('the flag also comes through the tutor step and survives the merge', () => {
  assert.equal(lineFromStep({ id: 'L1', label: 'x=1', bbox: [0, 10, 800, 40], bboxEstimated: true }, 0).bboxEstimated, true)
  const [line] = mergeStepsWithTwin([{ id: 'L1', label: 'x=1', status: 'correct' }], { lines: [estimated] })
  assert.equal(line.bboxEstimated, true)
})

test('the writing zoom ignores estimated bands', () => {
  const image = { width: 1000, height: 2000 }
  const lines = [lineFromTwin(estimated), lineFromTwin(measured)]
  assert.equal(inkRegion([lineFromTwin(estimated)], image), null)
  assert.deepEqual(inkRegion(lines, image), inkRegion([lineFromTwin(measured)], image))
})
