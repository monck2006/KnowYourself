import type { Episode } from './types'

export interface VisitFrequency { name: string; count: number }
export interface VisitSummary {
  records: Episode[]
  count: number
  ongoingCount: number
  endedCount: number
  firstDate: string | null
  lastDate: string | null
  symptoms: VisitFrequency[]
  medications: VisitFrequency[]
}

function frequencies(episodes: readonly Episode[], names: (episode: Episode) => string[]): VisitFrequency[] {
  const counts = new Map<string, number>()
  for (const episode of episodes) {
    const uniqueNames = new Set(names(episode).map(name => name.trim()).filter(Boolean))
    for (const name of uniqueNames) counts.set(name, (counts.get(name) ?? 0) + 1)
  }
  return Array.from(counts, ([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN'))
}

export function buildVisitSummary(episodes: readonly Episode[]): VisitSummary {
  const records = [...episodes].sort((a, b) => a.started_at.localeCompare(b.started_at)
    || a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))
  return {
    records,
    count: records.length,
    ongoingCount: records.filter(episode => episode.status === 'ongoing').length,
    endedCount: records.filter(episode => episode.status === 'ended').length,
    firstDate: records[0]?.started_at ?? null,
    lastDate: records.at(-1)?.started_at ?? null,
    symptoms: frequencies(records, episode => episode.symptoms),
    medications: frequencies(records, episode => episode.medications.map(item => item.name)),
  }
}

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]!)
}

/** markup must come from the report element after Vue has escaped all user text. */
export function visitReportDocument(markup: string, styles: string, displayName: string): string {
  return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' +
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">' +
    `<title>${escapeHtml(displayName)} · 就诊摘要</title><style>${styles}</style></head><body>${markup}</body></html>`
}
