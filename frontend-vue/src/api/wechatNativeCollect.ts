import request from '@/api/request'

export type WechatNativeFormat = 'html' | 'markdown' | 'text' | 'json'

export interface WechatNativeConfig {
  wechat_collection_output_dir: string
  wechat_collection_default_format: WechatNativeFormat
  wechat_collection_delay_seconds: number
  wechat_collection_max_articles: number
}

export interface WechatNativeSession {
  session_id: string
  nickname?: string
  avatar?: string
  status: string
  expires_at?: string
  last_checked_at?: string
  last_error?: string
  created_at?: string
  updated_at?: string
}

export interface WechatNativeLoginStart {
  login_id: string
  uuid?: string
  qrcode_url?: string
  status?: string
}

export interface WechatNativeTask {
  task_id: string
  provider?: string
  source_mode?: string
  fakeid?: string
  article_url?: string
  account_name?: string
  export_format?: string
  status: 'pending' | 'running' | 'done' | 'error' | 'cancelled' | string
  total: number
  completed: number
  success: number
  failed: number
  current?: string
  error?: string
  cancel_requested?: boolean
  created_at?: string
  updated_at?: string
  finished_at?: string
  results?: Array<{
    status: string
    title?: string
    url?: string
    error?: string
    content_type?: string
    artifact_id?: string
    artifact_name?: string
    artifact_url?: string
    path?: string
  }>
}

export interface WechatNativeArticlePreview {
  aid?: string
  title?: string
  link?: string
  url?: string
  cover?: string
  digest?: string
  author_name?: string
  update_time?: number
  create_time?: number
}

export interface WechatNativeStartPayload {
  session_id: string
  article_url?: string
  fakeid?: string
  account?: Record<string, any>
  account_name?: string
  urls?: Array<string | WechatNativeArticlePreview>
  keyword?: string
  format?: WechatNativeFormat
  output_dir?: string
  max_articles?: number
  delay_seconds?: number
  page_size?: number
}

export default {
  getConfig() {
    return request.get<WechatNativeConfig>('/api/wechat-native/config')
  },

  listSessions() {
    return request.get<{ sessions: WechatNativeSession[] }>('/api/wechat-native/sessions')
  },

  startLogin() {
    return request.post<WechatNativeLoginStart>('/api/wechat-native/login/start', {})
  },

  getQrcodeBlob(loginId: string) {
    return request.get<Blob>(`/api/wechat-native/login/${loginId}/qrcode`, { responseType: 'blob' })
  },

  scanLogin(loginId: string) {
    return request.get<Record<string, any>>(`/api/wechat-native/login/${loginId}/scan`)
  },

  confirmLogin(loginId: string) {
    return request.post<Record<string, any>>(`/api/wechat-native/login/${loginId}/confirm`, {})
  },

  checkSession(sessionId: string) {
    return request.post<Record<string, any>>(`/api/wechat-native/sessions/${sessionId}/check`, {})
  },

  logoutSession(sessionId: string) {
    return request.post<Record<string, any>>(`/api/wechat-native/sessions/${sessionId}/logout`, {})
  },

  searchAccounts(payload: { session_id: string; keyword: string; begin?: number; size?: number }) {
    return request.post<{ accounts: Array<Record<string, any>> }>('/api/wechat-native/accounts/search', payload)
  },

  accountByUrl(payload: { session_id: string; article_url: string }) {
    return request.post<{ account: Record<string, any> }>('/api/wechat-native/accounts/by-url', payload)
  },

  preview(payload: WechatNativeStartPayload & { begin?: number; page_size?: number; limit?: number }) {
    return request.post<{
      account: Record<string, any>
      articles: Array<Record<string, any>>
      total: number
      begin?: number
      page_size?: number
      next_begin?: number | null
      has_more?: boolean
    }>(
      '/api/wechat-native/articles/preview',
      payload,
    )
  },

  cachedArticles(payload: { fakeid: string; keyword?: string; begin?: number; page_size?: number; limit?: number }) {
    return request.post<{
      account: Record<string, any>
      articles: Array<Record<string, any>>
      total: number
      total_count?: number
      begin?: number
      page_size?: number
      next_begin?: number | null
      has_more?: boolean
      source?: string
    }>(
      '/api/wechat-native/articles/cache',
      payload,
    )
  },

  start(payload: WechatNativeStartPayload) {
    return request.post<{ ok: boolean; task_id: string; status: string }>('/api/wechat-native/tasks/start', payload)
  },

  listTasks() {
    return request.get<{ tasks: WechatNativeTask[] }>('/api/wechat-native/tasks')
  },

  getTask(taskId: string) {
    return request.get<WechatNativeTask>(`/api/wechat-native/tasks/${taskId}`)
  },

  getArtifactBlob(artifactId: string) {
    return request.get<Blob>(`/api/wechat-native/artifacts/${encodeURIComponent(artifactId)}`, { responseType: 'blob' })
  },

  cancelTask(taskId: string) {
    return request.post<Record<string, any>>(`/api/wechat-native/tasks/${taskId}/cancel`, {})
  },
}
