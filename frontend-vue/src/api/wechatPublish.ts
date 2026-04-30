import request from '@/api/request'

export interface WechatPublishPayload {
  draft_path?: string
  article_task_id?: string
  title?: string
  content?: string
  author?: string
  digest?: string
  theme?: string
  color?: string
  renderer?: string
  cover_image?: string
  need_open_comment?: boolean
  only_fans_can_comment?: boolean
}

export interface WechatPublishTask {
  task_id: string
  article_task_id?: string
  title?: string
  author?: string
  theme?: string
  color?: string
  publish_mode: 'draft' | 'publish'
  status: string
  wx_article_id?: string
  wx_url?: string
  error?: string
  created_at?: string
  updated_at?: string
  finished_at?: string
}

export interface WechatPublishResponse {
  task_id: string
  status: string
  renderer?: string
  html_path?: string
  warnings?: string[]
}

export default {
  getConfig() {
    return request<{
      wechat_app_id: string
      wechat_default_author: string
      wechat_default_theme: string
      wechat_default_color: string
      wechat_markdown_renderer: string
      wechat_baoyu_markdown_to_html_script: string
      wechat_need_open_comment: boolean
      wechat_only_fans_can_comment: boolean
      configured: boolean
    }>({
      url: '/api/wechat/config',
      method: 'get',
    })
  },

  saveToDraft(data: WechatPublishPayload) {
    return request<WechatPublishResponse>({
      url: '/api/wechat/draft',
      method: 'post',
      data,
    })
  },

  publishNow(data: WechatPublishPayload) {
    return request<WechatPublishResponse>({
      url: '/api/wechat/publish',
      method: 'post',
      data,
    })
  },

  getTaskStatus(taskId: string) {
    return request<WechatPublishTask>({
      url: `/api/wechat/tasks/${taskId}`,
      method: 'get',
    })
  },
}
