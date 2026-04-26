import request from '@/api/request'

export interface ClipTask {
  id: number
  account_id: number
  account_name: string
  video_title: string
  status: 'pending' | 'running' | 'done' | 'error'
  clip_count: number
  collection_count: number
  created_at: string
}

export interface ClipItem {
  id: number
  score: number
  duration: number
  video_url: string
  start_time?: number
  end_time?: number
}

export interface CollectionItem {
  id: number
  name: string
  clip_count: number
}

export interface ClipTaskDetail {
  id: number
  account_id: number
  account_name: string
  video_title: string
  status: string
  clip_count: number
  collection_count: number
  created_at: string
  clips: ClipItem[]
  collections: CollectionItem[]
}

export interface ClipListResponse {
  total: number
  page: number
  limit: number
  items: ClipTask[]
}

export interface ClipCreateResponse {
  ok?: boolean
  task_id?: number
  error?: string
}

export default {
  list(params?: { account_id?: number; status?: string; page?: number; limit?: number }) {
    return request<ClipListResponse>({
      url: '/api/clips',
      method: 'get',
      params,
    })
  },

  detail(id: number) {
    return request<ClipTaskDetail>({
      url: `/api/clips/${id}`,
      method: 'get',
    })
  },

  create(videoId: number) {
    return request<ClipCreateResponse>({
      url: '/api/clips',
      method: 'post',
      data: { video_id: videoId },
    })
  },
}
