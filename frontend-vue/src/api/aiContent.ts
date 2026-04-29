import request from '@/api/request'

export interface ArticleTaskCreatePayload {
  monitor_video_id?: number
  video_id?: string
  video_url?: string
  video_title?: string
  target_lang?: string
  auto_translate?: boolean
}

export interface VideoTaskCreatePayload {
  mode?: string
  topic?: string
  script?: string
  template?: string
  n_scenes?: number
  prompt_prefix?: string
  tts_workflow?: string
  image_workflow?: string
  bgm_volume?: number
}

export interface AiTemplateOption {
  label?: string
  value?: string
  name?: string
  path?: string
  description?: string
}

export default {
  createArticleTask(data: ArticleTaskCreatePayload) {
    return request<Record<string, unknown>>({
      url: '/api/article/generate',
      method: 'post',
      data,
    })
  },

  listArticleTasks() {
    return request<Record<string, unknown> | unknown[]>({
      url: '/api/article/list',
      method: 'get',
    })
  },

  getArticleTask(taskId: string) {
    return request<Record<string, unknown>>({
      url: `/api/article/${taskId}`,
      method: 'get',
    })
  },

  cancelArticleTask(taskId: string) {
    return request<Record<string, unknown>>({
      url: `/api/article/${taskId}/cancel`,
      method: 'post',
    })
  },

  createVideoTask(data: VideoTaskCreatePayload) {
    return request<Record<string, unknown>>({
      url: '/api/video-generate',
      method: 'post',
      data,
    })
  },

  listVideoTasks() {
    return request<Record<string, unknown> | unknown[]>({
      url: '/api/video-generate/list',
      method: 'get',
    })
  },

  getVideoTask(taskId: string) {
    return request<Record<string, unknown>>({
      url: `/api/video-generate/${taskId}`,
      method: 'get',
    })
  },

  cancelVideoTask(taskId: string) {
    return request<Record<string, unknown>>({
      url: `/api/video-generate/${taskId}/cancel`,
      method: 'post',
    })
  },

  listVideoTemplates() {
    return request<Record<string, unknown> | AiTemplateOption[]>({
      url: '/api/video-generate/templates',
      method: 'get',
    })
  },
}
