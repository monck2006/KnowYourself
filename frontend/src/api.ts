import { Capacitor } from '@capacitor/core'
import type { AuthResponse, Episode, EpisodeInput, Overview, User } from './types'

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
  const data = response.status === 204 ? null : await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    const fallback = response.status === 401 ? '登录已过期，请重新登录。' : response.status === 409 ? '这条记录已在其他设备更新。请重新载入后编辑，避免覆盖新内容。' : '操作未完成，请稍后重试。'
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join('；') : fallback
    throw new ApiError(response.status, message || fallback)
  }
  return data as T
}

export const api = {
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
  episodes: () => request<Episode[]>('/episodes'),
  episode: (id: string) => request<Episode>(`/episodes/${encodeURIComponent(id)}`),
  create: (input: EpisodeInput) => request<Episode>('/episodes', 'POST', input),
  update: (id: string, input: EpisodeInput, version: number) => request<Episode>(`/episodes/${encodeURIComponent(id)}`, 'PUT', { ...input, version }),
  delete: (id: string, version: number) => request(`/episodes/${encodeURIComponent(id)}?version=${version}`, 'DELETE'),
  overview: () => request<Overview>('/overview'),
  export: () => request<unknown>('/export'),
  deleteAccount: async (password: string) => { await request('/account', 'DELETE', { password }); accessToken = '' },
}

export async function exportRecords() {
  const data = await api.export()
  const filename = `知己健康记录-${new Date().toISOString().slice(0, 10)}.json`
  const content = JSON.stringify(data, null, 2)
  if (isNative) {
    const [{ Filesystem, Directory, Encoding }, { Share }] = await Promise.all([import('@capacitor/filesystem'), import('@capacitor/share')])
    const saved = await Filesystem.writeFile({ path: filename, data: content, directory: Directory.Cache, encoding: Encoding.UTF8 })
    try { await Share.share({ title: '知己健康记录', url: saved.uri, dialogTitle: '保存或分享健康记录' }) }
    finally { await Filesystem.deleteFile({ path: filename, directory: Directory.Cache }).catch(() => undefined) }
  } else {
    const url = URL.createObjectURL(new Blob([content], { type: 'application/json;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
