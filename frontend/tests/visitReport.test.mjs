import test from 'node:test'
import assert from 'node:assert/strict'
import { buildVisitSummary, escapeHtml, visitReportDocument } from '../src/visitReport.ts'

function record(id, changes = {}) {
  return { id, started_at: '2026-07-01', ended_at: null, chief_complaint: '头痛', symptoms: [], notes: '',
    medications: [], severity: 2, status: 'ongoing', outcome: 'ongoing',
    vitals: { temperature: null, heart_rate: null, spo2: null },
    created_at: '2026-07-01T10:00:00Z', updated_at: '2026-07-01T10:00:00Z', ...changes }
}

test('offline report embeds styles and escaped title with a restrictive content policy', () => {
  const markup = '<article class="visit-report">&lt;script&gt;hello&lt;/script&gt;</article>'
  const html = visitReportDocument(markup, '.visit-report { color: #000; }', '</title><script>alert(1)</script>')
  assert.ok(html.startsWith('<!doctype html>'))
  assert.ok(html.includes('<html lang="zh-CN">'))
  assert.ok(html.includes("default-src 'none'; style-src 'unsafe-inline'"))
  assert.ok(html.includes('<style>.visit-report { color: #000; }</style>'))
  assert.ok(html.includes(markup))
  assert.ok(!html.includes('<script>'))
  assert.ok(!html.includes('<link '))
})

test('empty summaries contain zero counts and no date span', () => {
  assert.deepEqual(buildVisitSummary([]), {
    records: [], count: 0, ongoingCount: 0, endedCount: 0,
    firstDate: null, lastDate: null, symptoms: [], medications: [],
  })
})

test('symptoms and medication names count once per record, trim whitespace and omit empty names', () => {
  const summary = buildVisitSummary([
    record('a', { symptoms: [' 咳嗽 ', '咳嗽', '', '  ', '发热'], medications: [
      { name: '药 A', dose: '一片', frequency: '每日' }, { name: ' 药 A ', dose: '两片', frequency: '每日' },
      { name: ' ', dose: '', frequency: '' }, { name: '药 B', dose: '', frequency: '' },
    ] }),
    record('b', { symptoms: ['咳嗽'], medications: [{ name: '药 A', dose: '', frequency: '' }] }),
  ])
  assert.deepEqual(summary.symptoms, [{ name: '咳嗽', count: 2 }, { name: '发热', count: 1 }])
  assert.deepEqual(summary.medications, [{ name: '药 A', count: 2 }, { name: '药 B', count: 1 }])
})

test('frequency ties follow Chinese name order', () => {
  const names = ['头痛', '发热', '咳嗽']
  const summary = buildVisitSummary([record('a', {
    symptoms: names,
    medications: names.map(name => ({ name, dose: '', frequency: '' })),
  })])
  const expected = [...names].sort((a, b) => a.localeCompare(b, 'zh-CN'))
  assert.deepEqual(summary.symptoms.map(item => item.name), expected)
  assert.deepEqual(summary.medications.map(item => item.name), expected)
})

test('records sort by start date, creation date and id without changing inputs; date span uses start dates', () => {
  const items = [record('c', { started_at: '2026-07-03', status: 'ended', ended_at: '2026-08-10' }),
    record('b'), record('a'), record('early', { created_at: '2026-07-01T09:00:00Z' })]
  const original = structuredClone(items)
  const summary = buildVisitSummary(items)
  assert.deepEqual(summary.records.map(item => item.id), ['early', 'a', 'b', 'c'])
  assert.notEqual(summary.records, items)
  assert.deepEqual(items, original)
  assert.equal(summary.count, 4)
  assert.equal(summary.ongoingCount, 3)
  assert.equal(summary.endedCount, 1)
  assert.equal(summary.firstDate, '2026-07-01')
  assert.equal(summary.lastDate, '2026-07-03')
})

test('HTML escaping protects user text including quotes and preexisting entities', () => {
  assert.equal(escapeHtml('<script title="x" data-x=\'y\'>A & B</script>'),
    '&lt;script title=&quot;x&quot; data-x=&#39;y&#39;&gt;A &amp; B&lt;/script&gt;')
  assert.equal(escapeHtml('&lt;'), '&amp;lt;')
  assert.equal(escapeHtml('中文记录'), '中文记录')
})
