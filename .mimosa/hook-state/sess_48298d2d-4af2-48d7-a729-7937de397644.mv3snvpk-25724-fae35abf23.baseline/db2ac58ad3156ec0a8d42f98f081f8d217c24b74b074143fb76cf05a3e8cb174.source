import type { Outcome } from './types'

export function today() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
export function dateLabel(value: string) {
  const date = new Date(`${value.slice(0, 10)}T12:00:00`)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
}
export const outcomeLabels: Record<Outcome, string> = { ongoing: '仍在观察', improving: '有所好转', resolved: '症状已消失', worsened: '有所加重' }
export const severityLabels = ['轻微', '较轻', '中等', '较重', '严重']
