import request from '@/api/request'

export interface WeReadExporterConfig {
  playwright_installed: boolean
  output_root: string
  cache_dir: string
  requires_visible_browser: boolean
  source_project: string
  supported_formats: string[]
}

export interface WeReadExportResult {
  kind?: string
  status: string
  title?: string
  path?: string
  error?: string
  pages?: number
  chars?: number
  content_type?: string
  artifact_id?: string
  artifact_name?: string
  artifact_url?: string
}

export interface WeReadExportTask {
  task_id: string
  book_id: string
  book_input?: string
  title?: string
  author?: string
  output_dir: string
  cache_dir: string
  save_raw: boolean
  status: 'pending' | 'running' | 'done' | 'error' | 'cancelled' | string
  total: number
  completed: number
  success: number
  failed: number
  skipped: number
  current?: string
  error?: string
  cancel_requested?: boolean
  created_at?: string
  updated_at?: string
  finished_at?: string
  results?: WeReadExportResult[]
}

export interface WeReadStartPayload {
  book: string
  output_dir?: string
  save_raw?: boolean
}

export default {
  getConfig() {
    return request.get<WeReadExporterConfig>('/api/weread-exporter/config')
  },

  start(payload: WeReadStartPayload) {
    return request.post<{ ok: boolean; task_id: string; status: string }>('/api/weread-exporter/tasks/start', payload)
  },

  listTasks() {
    return request.get<{ tasks: WeReadExportTask[] }>('/api/weread-exporter/tasks')
  },

  getTask(taskId: string) {
    return request.get<WeReadExportTask>(`/api/weread-exporter/tasks/${taskId}`)
  },

  cancelTask(taskId: string) {
    return request.post<Record<string, any>>(`/api/weread-exporter/tasks/${taskId}/cancel`, {})
  },
}
