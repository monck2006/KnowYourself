import test from 'node:test'
import assert from 'node:assert/strict'
import { emptyIntakeDraft, intakeDraftToEpisodeInput } from '../src/episodeInput.ts'

test('conversation cannot silently manufacture a date or severity on save', () => {
  const draft = { ...emptyIntakeDraft(), chief_complaint: '喉咙不适', symptoms: ['咽痛'] }
  assert.throws(() => intakeDraftToEpisodeInput(draft), /开始日期/)
  assert.equal(draft.severity, null)
  assert.equal(draft.started_at, '')
  assert.throws(() => intakeDraftToEpisodeInput({ ...draft, started_at: '2026-10-10' }))
  const input = intakeDraftToEpisodeInput({ ...draft, started_at: '2026-10-10', severity: 1 })
  assert.equal(input.started_at, '2026-10-10')
  assert.equal(input.severity, 1)
  assert.deepEqual(input.symptoms, ['咽痛'])
})
