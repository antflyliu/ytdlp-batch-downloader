/**
 * 视频号 SPH 解析 API 封装
 * 对应 server/__main__.py 的 9 个 /api/channels/* 端点
 */
import request from '@/api/request'

export interface SphParseResult {
    authorInfo: { nickname: string; head_img_url: string; auth_icon_url: string }
    feedInfo: {
        video_url: string
        origin_video_url: string
        description: string
        cover_url: string
        like_count_fmt: string
        h264_video_info: { video_url: string }
        h265_video_info: { video_url: string }
        createtime: number
    }
}

export interface SphCookieStatus {
    exists: boolean
    source: string | null
    age_seconds: number | null
    preview: string | null
}

export interface SphHistoryItem {
    id: string
    sph_url: string
    video_title: string
    author_nickname: string
    cover_url: string
    video_url: string
    h264_video_url?: string
    h265_video_url?: string
    description?: string
    downloaded: number
    downloaded_path: string | null
    downloaded_at: string | null
    parse_status?: string
    parse_error?: string | null
    parsed_at: string
}

export interface SphRefreshState {
    state: 'idle' | 'running' | 'success' | 'failed'
    pid: number | null
    started_at: string | null
    finished_at: string | null
    last_error: string | null
    cookie_updated: boolean
}

export function parseSph(url: string) {
    return request<{ ok: boolean; data: SphParseResult }>({
        url: '/api/channels/parse_sph',
        method: 'get',
        params: { url },
    })
}

export function batchParse(urls: string[], maxConcurrent = 3) {
    return request<{ ok: boolean; data: { results: any[]; summary: any } }>({
        url: '/api/channels/batch_parse',
        method: 'post',
        data: { urls, max_concurrent: maxConcurrent },
    })
}

export function saveSphCookie(cookie: string, source: 'manual' | 'playwright' = 'manual') {
    return request<{ ok: boolean; data: { updated_at: string; preview: string } }>({
        url: '/api/channels/cookie',
        method: 'post',
        data: { cookie, source },
    })
}

export function getSphCookieStatus() {
    return request<{ ok: boolean; data: SphCookieStatus }>({
        url: '/api/channels/cookie',
        method: 'get',
    })
}

export function startSphRefresh() {
    return request<{ ok: boolean; data: { state: string; pid: number; started_at: string } }>({
        url: '/api/channels/cookie/refresh',
        method: 'post',
    })
}

export function getSphRefreshStatus() {
    return request<{ ok: boolean; data: SphRefreshState }>({
        url: '/api/channels/cookie/refresh-status',
        method: 'get',
    })
}

export function cancelSphRefresh() {
    return request<{ ok: boolean; data: { cancelled: boolean; pid: number } }>({
        url: '/api/channels/cookie/refresh-cancel',
        method: 'post',
    })
}

export function listSphHistory(opts: {
    limit?: number
    offset?: number
    keyword?: string
} = {}) {
    return request<{ ok: boolean; data: { items: SphHistoryItem[]; total: number; limit: number; offset: number } }>({
        url: '/api/channels/history',
        method: 'get',
        params: opts,
    })
}

export function downloadFromSph(opts: {
    history_id?: string
    sph_url?: string
    quality?: string
    sub_langs?: string
}) {
    return request<{ ok: boolean; data: { task_id: string; state: string; video_url: string; output_path: string } }>({
        url: '/api/channels/download',
        method: 'post',
        data: opts,
    })
}

/**
 * 2026-06-16 新增:浏览器侧下载完成后调用,标记 history 为已下载。
 * 失败由调用方 .catch 吞掉(主下载流程已成功,标记失败不应影响用户)。
 */
export function markSphDownloaded(history_id: string, path: string = '') {
    return request<{ ok: boolean; data: { updated: boolean } }>({
        url: '/api/channels/mark_downloaded',
        method: 'post',
        data: { history_id, path },
    })
}
