import request from '@/api/request'

export type WechatCollectFormat = 'html' | 'markdown' | 'text' | 'json'

export interface WechatCollectConfig {
  wechat_exporter_base_url: string
  wechat_collection_output_dir: string
  wechat_collection_default_format: WechatCollectFormat
  wechat_collection_delay_seconds: number
  wechat_collection_max_articles: number
  configured: boolean
}

export interface WechatCollectStartPayload {
  article_url?: string
  fakeid?: string
  account_name?: string
  urls?: string[]
  keyword?: string
  format?: WechatCollectFormat
  output_dir?: string
  max_articles?: number
  delay_seconds?: number
  page_size?: number
}

export interface WechatCollectTask {
  task_id: string
  status: 'running' | 'done' | 'error' | 'cancelled' | string
  total: number
  completed: number
  success: number
  failed: number
  current: string
  account: Record<string, any>
  output_dir: string
  cancel_requested: boolean
  created_at: string
  finished_at?: string
  error?: string
  results?: Array<Record<string, any>>
}

export default {
  getConfig() {
    return request.get<WechatCollectConfig>('/api/wechat-collect/config')
  },

  checkAuth(authKey?: string, baseUrl?: string) {
    return request.post('/api/wechat-collect/auth/check', {
      auth_key: authKey,
      base_url: baseUrl,
    })
  },

  preview(payload: WechatCollectStartPayload & { limit?: number; auth_key?: string; base_url?: string }) {
    return request.post('/api/wechat-collect/preview', payload)
  },

  start(payload: WechatCollectStartPayload) {
    return request.post<{ task_id: string; status: string }>('/api/wechat-collect/start', payload)
  },

  listTasks() {
    return request.get<{ tasks: WechatCollectTask[] }>('/api/wechat-collect/tasks')
  },

  getTask(taskId: string) {
    return request.get<WechatCollectTask>(`/api/wechat-collect/tasks/${taskId}`)
  },

  cancelTask(taskId: string) {
    return request.post(`/api/wechat-collect/tasks/${taskId}/cancel`, {})
  },
}
