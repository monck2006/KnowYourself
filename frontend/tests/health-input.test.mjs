import test from 'node:test'
import assert from 'node:assert/strict'
import { toEpisodeInput } from '../src/episodeInput.ts'
import { coarseGrid } from '../src/healthLabels.ts'

test('reloaded records serialize only allowed input fields and retain medication course details', () => {
  const record = { id: 'server-id', version: 9, analysis: { level: 'recorded' }, created_at: 'server-time',
    chief_complaint: '  咳嗽 ', symptoms: ['咳嗽'], started_at: '2026-07-01', status: 'ongoing',
    disease_category: 'infectious', infection_group: 'respiratory',
    medications: [{ name: ' 药品A ', dose: '1', frequency: '每日', started_at: '2026-07-01', ended_at: '2026-07-03', adherence: 'missed', response: 'unchanged', notes: ' 漏用一次 ', server_only: true }] }
  const input = toEpisodeInput(record)
  for (const key of ['id', 'version', 'analysis', 'created_at']) assert.equal(key in input, false)
  assert.equal(input.chief_complaint, '咳嗽')
  assert.deepEqual(input.medications[0], { name: '药品A', dose: '1', frequency: '每日', started_at: '2026-07-01', ended_at: '2026-07-03', adherence: 'missed', response: 'unchanged', notes: '漏用一次' })
  assert.equal(input.infection_group, 'respiratory')
  input.symptoms.push('乏力'); input.medications[0].notes = '改变'
  assert.deepEqual(record.symptoms, ['咳嗽']); assert.equal(record.medications[0].notes, ' 漏用一次 ')
})
test('legacy records gain neutral defaults and infection group is cleared outside infectious category', () => {
  const input = toEpisodeInput({ status: 'ongoing', ended_at: '2026-07-03', infection_group: 'respiratory', medications: [{ name: 'A', dose: '', frequency: '' }] })
  assert.equal(input.ended_at, null); assert.equal(input.disease_category, 'unknown'); assert.equal(input.infection_group, 'unspecified')
  assert.equal(input.diagnosis_source, 'unknown'); assert.deepEqual(input.observation_ids, [])
  assert.equal(input.medications[0].adherence, 'unknown'); assert.equal(input.medications[0].response, 'unknown')
})
test('location quantization floors both hemispheres and rejects invalid coordinates', () => {
  assert.equal(coarseGrid(30.123456, 120.987654), 'grid:301:1209')
  assert.equal(coarseGrid(-0.01, -120.01), 'grid:-1:-1201')
  for (const [lat, lon] of [[NaN, 0], [Infinity, 0], [90.1, 0], [0, -180.1]]) assert.throws(() => coarseGrid(lat, lon))
})

test('editing a record preserves saved assessment answers without sharing mutable objects', () => {
  const saved = { assessment_answers: [{ question_id: 'breathing_difficulty', answer: 'yes' }] }
  const input = toEpisodeInput(saved)
  assert.deepEqual(input.assessment_answers, saved.assessment_answers)
  input.assessment_answers[0].answer = 'no'
  assert.equal(saved.assessment_answers[0].answer, 'yes')
})
