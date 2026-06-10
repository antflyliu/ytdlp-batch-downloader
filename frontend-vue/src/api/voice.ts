import request from '@/api/request'

export interface VoiceProviderOption {
  id: string
  label?: string
  capabilities?: string[]
  configured?: boolean
  modes?: string[]
  fields?: Record<string, unknown>
  safety?: Record<string, unknown>
  config_reason?: string
}

export interface VoiceProvidersResponse {
  capability?: string
  flow?: string
  selected_provider?: Record<string, unknown>
  providers: VoiceProviderOption[]
}

export interface VoiceSynthesisTaskPayload {
  text: string
  provider?: string
  flow?: string
  mode?: string
  voice?: string
  language?: string
  model?: string
  response_format?: string
  speed?: number
  pitch?: number
  volume?: number
  style?: string
  fallback_allowed?: boolean
}

export interface VoiceTaskListResponse {
  tasks: Array<Record<string, unknown>>
  total?: number
  limit?: number
  offset?: number
}

const query = (params: Record<string, string | number | boolean | undefined>) => {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === '') return
    search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const voiceFileUrl = (path: string) => `/api/voice/file?path=${encodeURIComponent(path)}`

export default {
  listProviders(params: { capability?: string; flow?: string } = {}) {
    return request<VoiceProvidersResponse>({
      url: `/api/voice/providers${query(params)}`,
      method: 'get',
    })
  },

  checkEnv(data: { include_remote?: boolean; timeout_seconds?: number } = {}) {
    return request<Record<string, unknown>>({
      url: '/api/voice/env/check',
      method: 'post',
      data,
    })
  },

  smokeTest(data: Record<string, unknown>) {
    return request<Record<string, unknown>>({
      url: '/api/voice/smoke-test',
      method: 'post',
      data,
    })
  },

  createSynthesisTask(data: VoiceSynthesisTaskPayload) {
    return request<Record<string, unknown>>({
      url: '/api/voice/synthesis/tasks',
      method: 'post',
      data,
    })
  },

  listTasks(params: { kind?: string; limit?: number; offset?: number } = {}) {
    return request<VoiceTaskListResponse>({
      url: `/api/voice/tasks${query(params)}`,
      method: 'get',
    })
  },

  getTask(taskId: string) {
    return request<Record<string, unknown>>({
      url: `/api/voice/tasks/${encodeURIComponent(taskId)}`,
      method: 'get',
    })
  },

  cancelTask(taskId: string) {
    return request<Record<string, unknown>>({
      url: `/api/voice/tasks/${encodeURIComponent(taskId)}/cancel`,
      method: 'post',
    })
  },
}
