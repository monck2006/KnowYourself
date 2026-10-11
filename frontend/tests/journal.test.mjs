import test from 'node:test'
import assert from 'node:assert/strict'
import { episodesCsv, selectEpisodes } from '../src/journal.ts'

const filters = { search: '', status: 'all', from: '', to: '', sort: 'newest' }
function record(id, changes = {}) {
  return { id, started_at: '2026-07-01', ended_at: null, chief_complaint: '头痛', symptoms: ['乏力'], notes: '',
    medications: [], severity: 2, status: 'ongoing', outcome: 'ongoing',
    vitals: { temperature: null, heart_rate: null, spo2: null },
    created_at: '2026-07-01T10:00:00Z', updated_at: '2026-07-01T10:00:00Z', ...changes }
}

test('search combines terms across symptoms, notes and medications without case sensitivity', () => {
  const items = [record('a', { notes: '早晨', medications: [{ name: 'Medicine', dose: '1', frequency: '每日' }] }), record('b')]
  assert.deepEqual(selectEpisodes(items, { ...filters, search: '  MEDICINE  乏力 早晨 ' }).map(item => item.id), ['a'])
})

test('inclusive date range and status combine; invalid ranges return no records', () => {
  const items = [record('a'), record('b', { started_at: '2026-07-02', status: 'ended' }), record('c', { started_at: '2026-07-03', status: 'ended' })]
  assert.deepEqual(selectEpisodes(items, { ...filters, from: '2026-07-02', to: '2026-07-03', status: 'ended' }).map(item => item.id), ['c', 'b'])
  assert.equal(selectEpisodes(items, { ...filters, from: '2026-07-03', to: '2026-07-01' }).length, 0)
})

test('sorting is deterministic, supports recent updates and never mutates source order', () => {
  const items = [record('a', { severity: 5, updated_at: '2026-08-01T10:00:00Z' }), record('b', { started_at: '2026-07-02' }), record('c', { started_at: '2026-07-03' })]
  for (const [sort, expected] of [['newest', ['c', 'b', 'a']], ['oldest', ['a', 'b', 'c']], ['updated', ['a', 'c', 'b']], ['severity', ['a', 'c', 'b']]]) {
    assert.deepEqual(selectEpisodes(items, { ...filters, sort }).map(item => item.id), expected)
  }
  assert.deepEqual(items.map(item => item.id), ['a', 'b', 'c'])
})

test('CSV escapes quotes, commas, line breaks, preserves missing vitals and has a Chinese Excel BOM', () => {
  const csv = episodesCsv([record('a', { chief_complaint: '头痛,"记录"', notes: '第一行\n第二行' })])
  assert.ok(csv.startsWith('\uFEFF'))
  assert.ok(csv.includes('"头痛,""记录"""'))
  assert.ok(csv.includes('"第一行\n第二行"'))
  assert.ok(csv.includes('"仍在观察","","",""'))
})

test('CSV neutralizes formulas even with leading spaces and control characters', () => {
  for (const value of ['=HYPERLINK("example")', ' +1', '-1', '@SUM(A1)', '\tvalue', '\rvalue', '\nvalue']) {
    const csv = episodesCsv([record('a', { notes: value })])
    assert.ok(csv.includes(`"'${value.replaceAll('"', '""')}"`), value)
  }
  assert.ok(episodesCsv([]).includes('开始日期'))
})
