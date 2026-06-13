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

export interface RssCatalogSource {
  source_key: string
  name: string
  homepage_url?: string
  feeds_url?: string
  status_url?: string
  readme_url?: string
  license?: string
  last_synced_at?: string | null
  last_sync_status?: string | null
  last_sync_error?: string | null
  feed_total?: number
  valid_count?: number
  invalid_count?: number
  limited_count?: number
  success_rate?: string
}

export interface RssCatalogEntry {
  id: number
  source_key: string
  entry_key: string
  entry_type: 'feed' | 'rsshub_route'
  title: string
  category?: string
  feed_url?: string
  site_url?: string
  route_template?: string
  description?: string
  status?: string
  status_valid?: boolean | null
  status_limited?: boolean
  status_code?: number | null
  status_error?: string
  status_checked_at?: string
  imported?: boolean
  feed_id?: number | null
}

export interface RssCatalogSourcePayload {
  name: string
  feeds_url: string
  homepage_url?: string
  status_url?: string
}

export interface RssCatalogSummary {
  total: number
  feed_count: number
  route_count: number
  valid_count: number
  limited_count: number
  invalid_count: number
  category_count: number
  categories: string[]
  source?: RssCatalogSource | null
}

export function listRssFeeds() {
  return request.get<{ feeds: RssFeed[] }>('/api/rss/feeds')
}

export function listRssCatalog(params: { q?: string; category?: string; entry_type?: string; available?: boolean } = {}) {
  return request.get<{ entries: RssCatalogEntry[]; summary: RssCatalogSummary }>('/api/rss/catalog', { params })
}

export function syncRssCatalog() {
  return request.post<{ ok: boolean; summary: RssCatalogSummary }>('/api/rss/catalog/sync', {})
}

export function importRssCatalogEntries(entryIds: number[], fetchIntervalMinutes = 60) {
  return request.post<{ ok: boolean; imported: number; skipped: number; invalid_items: unknown[] }>(
    '/api/rss/catalog/import',
    {
      entry_ids: entryIds,
      fetch_interval_minutes: fetchIntervalMinutes,
    },
  )
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

export function listRssCatalogSources() {
  return request.get<{ sources: RssCatalogSource[] }>('/api/rss/catalog/sources')
}

export function addRssCatalogSource(payload: RssCatalogSourcePayload) {
  return request.post<{ ok: boolean; source: RssCatalogSource }>('/api/rss/catalog/sources', payload)
}

export function deleteRssCatalogSource(sourceKey: string) {
  return request.delete<{ ok: boolean }>(`/api/rss/catalog/sources/${encodeURIComponent(sourceKey)}`)
}

export function syncRssCatalogSource(sourceKey: string) {
  return request.post<{ ok: boolean; summary: RssCatalogSummary }>(
    `/api/rss/catalog/sources/${encodeURIComponent(sourceKey)}/sync`,
    {},
  )
}

export function exportRssOpml() {
  return request.get<{ opml: string }>('/api/rss/opml/export')
}
