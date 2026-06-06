import request from '@/api/request'

export interface RssFeed {
  id: number
  title: string
  feed_url: string
  site_url?: string
  category?: string
  enabled: boolean
  fetch_interval_minutes: number
  last_fetch_at?: string | null
  last_fetch_status?: string | null
  last_fetch_error?: string | null
  created_at?: string
  updated_at?: string
}

export interface RssItem {
  id: number
  feed_id: number
  feed_title?: string
  feed_url?: string
  title: string
  link?: string
  author?: string
  published_at?: string
  summary?: string
  content_html?: string
  preview_image?: string
  media?: Array<Record<string, unknown>>
  article_task_id?: string | null
  read_status?: string
}

export interface RssFeedPayload {
  title?: string
  feed_url: string
  site_url?: string
  category?: string
  enabled?: boolean
  fetch_interval_minutes?: number
}

export function listRssFeeds() {
  return request.get<{ feeds: RssFeed[] }>('/api/rss/feeds')
}

export function saveRssFeed(payload: RssFeedPayload) {
  return request.post<{ ok: boolean; feed: RssFeed }>('/api/rss/feeds', payload)
}

export function deleteRssFeed(feedId: number) {
  return request.delete<{ ok: boolean }>(`/api/rss/feeds/${feedId}`)
}

export function refreshRssFeed(feedId: number, maxItems = 50) {
  return request.post<{ ok: boolean; feed_id: number; stored: number }>(`/api/rss/feeds/${feedId}/refresh`, {
    max_items: maxItems,
  })
}

export function listRssItems(params: { feed_id?: number; limit?: number; offset?: number } = {}) {
  return request.get<{ items: RssItem[]; limit: number; offset: number }>('/api/rss/items', { params })
}

export function generateRssArticle(itemId: number, payload: { target_lang?: string; auto_translate?: boolean } = {}) {
  return request.post<{ ok: boolean; task_id: string }>(`/api/rss/items/${itemId}/generate`, payload)
}

export function importRssOpml(opml: string) {
  return request.post<{ ok: boolean; imported: number; invalid_items: unknown[]; duplicate_items: unknown[] }>(
    '/api/rss/opml/import',
    { opml },
  )
}

export function exportRssOpml() {
  return request.get<{ opml: string }>('/api/rss/opml/export')
}
