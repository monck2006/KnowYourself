import type { Episode, EpisodeStatus } from './types'
import { outcomeLabels } from './format.ts'

export type JournalSort = 'newest' | 'oldest' | 'updated' | 'severity'
export interface JournalFilters {
  search: string
  status: 'all' | EpisodeStatus
  from: string
  to: string
  sort: JournalSort
}

export function selectEpisodes(episodes: readonly Episode[], filters: JournalFilters): Episode[] {
  const terms = filters.search.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  if (filters.from && filters.to && filters.from > filters.to) return []
  return episodes.filter(episode => {
    if (filters.status !== 'all' && episode.status !== filters.status) return false
    if (filters.from && episode.started_at < filters.from) return false
    if (filters.to && episode.started_at > filters.to) return false
    if (!terms.length) return true
    const text = [episode.chief_complaint, episode.notes, ...episode.symptoms,
      ...episode.medications.map(item => `${item.name} ${item.dose} ${item.frequency}`)].join(' ').toLocaleLowerCase()
    return terms.every(term => text.includes(term))
  }).sort((a, b) => {
    const recent = b.started_at.localeCompare(a.started_at) || b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id)
    if (filters.sort === 'oldest') return -recent
    if (filters.sort === 'updated') return b.updated_at.localeCompare(a.updated_at) || recent
    if (filters.sort === 'severity') return b.severity - a.severity || recent
    return recent
  })
}

function csvCell(value: string | number | null): string {
  let text = value == null ? '' : String(value)
  // Quoting alone does not stop spreadsheet applications from evaluating formulas.
  if (typeof value === 'string' && (/^[\t\r\n]/.test(text) || /^\s*[=+@-]/.test(text))) text = `'${text}`
  return `"${text.replaceAll('"', '""')}"`
}

export function episodesCsv(episodes: readonly Episode[]): string {
  const rows: (string | number | null)[][] = [
    ['开始日期', '结束日期', '主要不适', '症状', '不适程度（1–5）', '状态', '目前变化', '体温（°C）', '心率（次/分）', '血氧（%）', '用药记录', '笔记', '最后修改时间'],
    ...episodes.map(episode => [episode.started_at, episode.ended_at, episode.chief_complaint,
      episode.symptoms.join('；'), episode.severity, episode.status === 'ongoing' ? '持续中' : '已结束',
      outcomeLabels[episode.outcome], episode.vitals.temperature, episode.vitals.heart_rate, episode.vitals.spo2,
      episode.medications.map(item => [item.name, item.dose, item.frequency].filter(Boolean).join(' ')).join('；'),
      episode.notes, episode.updated_at]),
  ]
  return '\uFEFF' + rows.map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n'
}
