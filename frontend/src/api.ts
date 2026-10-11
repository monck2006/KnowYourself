import { Capacitor } from '@capacitor/core'
import type { AuthResponse, CompetitionDatasetId, CompetitionSamples, CompetitionSplit, CompetitionStatus, DrugLabels, Episode, EpisodeInput, ExportData, HealthContext, HealthProfile, KnowledgeStatus, KnowledgeTopic, KnowledgeTopics, ObservationInput, Observations, Overview, RegionalSummary, User, Workspace } from './types'
import { today } from './format'
import { episodesCsv } from './journal'
import type { Analysis, Assessment, IntakeContext, IntakeDraft, IntakeTurn, ModelExplanation, ModelStatus } from './types'
export const isNative = Capacitor.isNativePlatform()
const baseURL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
let accessToken = ''

export const connectionError = (() => {
  if (!isNative) return ''
  try { if (new URL(baseURL).protocol === 'https:') return '' } catch { /* handled below */ }
  return '此应用尚未配置安全的服务连接，请联系应用管理员完成配置。'
})()

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  if (connectionError) throw new ApiError(0, connectionError)
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') headers['X-Zhiji-Client'] = '1'
  if (isNative && accessToken) headers.Authorization = `Bearer ${accessToken}`
  let response: Response
  try {
    response = await fetch(`${baseURL}/api/v1${path}`, {
      method, headers, credentials: isNative ? 'omit' : 'include',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(20000),
    })
  } catch {
    throw new ApiError(0, '暂时无法连接服务，请检查网络后重试。你的输入仍保留在当前页面。')
  }
  let data
  try { data = response.status === 204 ? null : await response.json() }
  catch {
    throw new ApiError(response.status, response.ok ? '服务返回的数据不完整，请重试。' : '服务暂时不可用，请稍后重试。')
  }
  if (!response.ok) {
    const detail = data?.detail
    const fallback = response.status === 401 ? '登录已过期，请重新登录。' : response.status === 409 ? '这条记录已在其他设备更新。请重新载入后编辑，避免覆盖新内容。' : '操作未完成，请稍后重试。'
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join('；') : fallback
    throw new ApiError(response.status, message || fallback)
  }
  if (data == null && response.status !== 204) throw new ApiError(response.status, '服务返回的数据不完整，请重试。')
  return data as T
}

export const api = {
  intakeContext: (): IntakeContext => ({ client_time: new Date().toISOString(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai', timezone_offset_minutes: -new Date().getTimezoneOffset() }),
  me: () => request<User>('/auth/me'),
  login: async (username: string, password: string) => {
    const data = await request<AuthResponse>('/auth/login', 'POST', { username, password })
    if (isNative) accessToken = data.access_token
    return data.user
  },
  register: async (username: string, display_name: string, password: string) => {
    const data = await request<AuthResponse>('/auth/register', 'POST', { username, display_name, password, consent: true })
    if (isNative) accessToken = data.access_token
    return data.user
  },
  logout: async () => { await request('/auth/logout', 'POST'); accessToken = '' },
  updateProfile: (display_name: string) => request<User>('/account/profile', 'PUT', { display_name }),
  changePassword: (current_password: string, new_password: string) => request<void>('/account/password', 'POST', { current_password, new_password }),
  workspace: () => request<Workspace>('/workspace'),
  episodes: () => request<Episode[]>('/episodes'),
  episode: (id: string) => request<Episode>(`/episodes/${encodeURIComponent(id)}`),
  assessment: (id: string) => request<Assessment>(`/episodes/${encodeURIComponent(id)}/assessment`),
  modelStatus: () => request<ModelStatus>('/assistant/status'),
  intakeTriage: (draft: IntakeDraft) => request<Analysis>('/intake/triage', 'POST', draft),
  intakeTurn: (draft: IntakeDraft, message: string, turns: number, cloud_consent: boolean, context?: IntakeContext) =>
    request<IntakeTurn>('/intake/assistant', 'POST', { draft, message, turns, cloud_consent, ...(context ?? api.intakeContext()) }),
  explainAssessment: (id: string, version: number, cloud_consent: boolean) => request<{ assessment: Assessment; explanation: ModelExplanation }>(`/episodes/${encodeURIComponent(id)}/assessment/explanation`, 'POST', { version, cloud_consent }),
  create: (input: EpisodeInput) => request<Episode>('/episodes', 'POST', input),
  update: (id: string, input: EpisodeInput, version: number) => request<Episode>(`/episodes/${encodeURIComponent(id)}`, 'PUT', { ...input, version }),
  delete: (id: string, version: number) => request(`/episodes/${encodeURIComponent(id)}?version=${version}`, 'DELETE'),
  overview: () => request<Overview>('/overview'),
  healthContext: () => request<HealthContext>('/health/context'),
  healthProfile: () => request<HealthProfile>('/health/profile'),
  saveHealthProfile: (profile: Omit<HealthProfile, 'updated_at'>) => request<HealthProfile>('/health/profile', 'PUT', profile),
  observations: (days = 30) => request<Observations>(`/health/observations?days=${days}&limit=200`),
  importObservations: (items: ObservationInput[]) => request<{ inserted: number; duplicates: number }>('/health/observations/import', 'POST', { items }),
  healthRegion: () => request<RegionalSummary>('/health/region'),
  knowledgeStatus: () => request<KnowledgeStatus>('/knowledge/status'),
  knowledgeTopics: (query = '', page = 1) => request<KnowledgeTopics>(`/knowledge/topics?${new URLSearchParams({ q: query, page: String(page), page_size: '12' })}`),
  knowledgeTopic: (id: string) => request<KnowledgeTopic>(`/knowledge/topics/${encodeURIComponent(id)}`),
  knowledgeDrugs: (query: string) => request<DrugLabels>(`/knowledge/drugs?${new URLSearchParams({ q: query })}`),
  competitionStatus: () => request<CompetitionStatus>('/knowledge/competition/status'),
  competitionSamples: (dataset: CompetitionDatasetId, split: CompetitionSplit, query = '', page = 1) => request<CompetitionSamples>(`/knowledge/competition?${new URLSearchParams({ dataset, split, q: query, page: String(page), page_size: '10' })}`),
  export: () => request<ExportData>('/export'),
  deleteAccount: async (password: string) => { await request('/account', 'DELETE', { password }); accessToken = '' },
}

export async function exportRecords() {
  const data = await api.export()
  await saveTextFile(`知己健康记录-${today()}.json`, JSON.stringify(data, null, 2), 'application/json')
}

export async function exportEpisodeCsv(episodes: readonly Episode[]) {
  await saveTextFile(`知己健康记录-${today()}.csv`, episodesCsv(episodes), 'text/csv')
}

export async function saveTextFile(filename: string, content: string, mimeType: string) {
  if (isNative) {
    const [{ Filesystem, Directory, Encoding }, { Share }] = await Promise.all([import('@capacitor/filesystem'), import('@capacitor/share')])
    const saved = await Filesystem.writeFile({ path: filename, data: content, directory: Directory.Cache, encoding: Encoding.UTF8 })
    try { await Share.share({ title: '知己健康记录', url: saved.uri, dialogTitle: '保存或分享健康记录' }) }
    finally { await Filesystem.deleteFile({ path: filename, directory: Directory.Cache }).catch(() => undefined) }
  } else {
    const url = URL.createObjectURL(new Blob([content], { type: `${mimeType};charset=utf-8` }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
