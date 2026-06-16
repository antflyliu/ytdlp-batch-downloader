import { defineStore } from 'pinia'
import { ref } from 'vue'
import { batchParse, markSphDownloaded } from '@/api/channels'

export interface QueueItem {
    id: number
    url: string
    status: 'parsing' | 'ready' | 'downloading' | 'done' | 'failed'
    progress?: number
    size?: string
    error?: string
    videoUrl?: string
    /** raw 模式下保存的原始视频 URL（无 watermark/transcode） */
    originVideoUrl?: string
    /** 视频号作者描述/标题，用于生成下载文件名 + 队列行展示 */
    description?: string
    /** 完整 feedInfo（保留以便下载时按 quality 字段选不同源） */
    feedInfo?: any
    /** 解析阶段开始时间（ms），用于显示 elapsed */
    parsingStartedAt?: number
    parsingElapsed?: number
    historyId?: string
}

export const useSphQueueStore = defineStore('sphQueue', () => {
    const items = ref<QueueItem[]>([])
    let nextId = 1

    function addBatch(urls: string[]) {
        const seen = new Set(items.value.map((i) => i.url))
        const now = Date.now()
        for (const u of urls) {
            if (seen.has(u)) continue
            items.value.push({
                id: nextId++,
                url: u,
                status: 'parsing',
                parsingStartedAt: now,
            })
        }
    }

    /**
     * 解析阶段进行中：定时刷新每个 parsing 项的 elapsed 计数（仅前端 UI 提示用）。
     * 调用方应避免重复启动 timer——可以加单例 flag。
     */
    function startParsingTicker() {
        const tick = () => {
            const now = Date.now()
            for (const item of items.value) {
                if (item.status === 'parsing' && item.parsingStartedAt) {
                    item.parsingElapsed = Math.floor((now - item.parsingStartedAt) / 1000)
                }
            }
        }
        tick()
        const timer = setInterval(tick, 1000)
        return () => clearInterval(timer)
    }

    function sanitizeFilename(desc?: string, createtime?: number): string {
        if (desc) return desc.replace(/[\\/:*?"<>|]/g, '').trim().slice(0, 200) + '.mp4'
        if (createtime) {
            const d = new Date(Number(createtime) * 1000)
            const pad = (n: number) => String(n).padStart(2, '0')
            return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}.mp4`
        }
        return ''
    }

    /**
     * 简单 async pool:N 个 worker 并发消费共享队列,直到耗尽。
     * 用于把串行下载改成并发下载(用户可配 1-10,默认 3)。
     * 不引入 p-limit/lodash 等依赖,代码 ~10 行。
     * fn 自带 try/catch(由调用方负责错误标记),worker 不抛。
     */
    async function runWithConcurrency<T>(items: T[], limit: number, fn: (item: T) => Promise<void>): Promise<void> {
        const queue = [...items]
        const worker = async () => {
            while (queue.length > 0) {
                const item = queue.shift() as T
                await fn(item)
            }
        }
        const workerCount = Math.max(1, Math.min(limit, items.length))
        await Promise.all(Array.from({ length: workerCount }, () => worker()))
    }

    /**
     * 浏览器侧直接拉取 finder.video.qq.com 的 blob 并触发下载。
     * 与 SingleParse.vue 的 onDownload 同构。
     * raw=true 走 originVideoUrl(原始无水印/无转码版本),
     * raw=false 回退 h264 > h265 > videoUrl(默认清晰度,由 WeChat API 自定)。
     */
    async function downloadDirectly(item: QueueItem, raw: boolean): Promise<void> {
        const fi: any = item.feedInfo
        if (!fi) throw new Error('no feedInfo')
        const videoUrl = raw
            ? (fi.originVideoUrl || '')
            : (fi.h264VideoInfo?.videoUrl || fi.h265VideoInfo?.videoUrl || fi.videoUrl || '')
        if (!videoUrl) throw new Error('no video url')

        const resp = await fetch(videoUrl)
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const contentLength = Number(resp.headers.get('content-length') || 0)
        const reader = resp.body?.getReader()
        if (!reader) {
            // 老浏览器 / 无 ReadableStream：退回一次性 blob
            const blob = await resp.blob()
            await saveBlob(blob, item, fi)
            return
        }
        const chunks: Uint8Array[] = []
        let received = 0
        // eslint-disable-next-line no-constant-condition
        while (true) {
            const { done, value } = await reader.read()
            if (done) break
            if (value) {
                chunks.push(value)
                received += value.byteLength
                if (contentLength > 0) {
                    item.progress = Math.floor((received / contentLength) * 100)
                }
            }
        }
        const blob = new Blob(chunks, { type: 'video/mp4' })
        item.size = formatBytes(received)
        await saveBlob(blob, item, fi)
        // 2026-06-16:下载成功后异步标记 history(失败不抛错,只 console.warn)
        if (item.historyId) {
            const filename = sanitizeFilename(item.description, fi.createtime) || 'video.mp4'
            markSphDownloaded(item.historyId, filename).catch((e) => {
                console.warn('[sph] mark_downloaded failed:', e)
            })
        }
    }

    function formatBytes(n: number): string {
        if (n < 1024) return `${n} B`
        if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
        if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
        return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
    }

    async function saveBlob(blob: Blob, item: QueueItem, fi: any): Promise<void> {
        const blobUrl = URL.createObjectURL(blob)
        try {
            const a = document.createElement('a')
            a.href = blobUrl
            a.download = sanitizeFilename(item.description, fi.createtime) || 'video.mp4'
            a.style.display = 'none'
            document.body.appendChild(a)
            a.click()
            document.body.removeChild(a)
        } finally {
            setTimeout(() => URL.revokeObjectURL(blobUrl), 0)
        }
    }

    async function processBatch(raw = false, concurrency = 3) {
        const parsingItems = items.value.filter((i) => i.status === 'parsing')
        if (parsingItems.length === 0) return

        const urls = parsingItems.map((i) => i.url)
        try {
            const r = await batchParse(urls, 3)
            // 响应形状：{ ok, data: { results, summary } }
            // axios 后 r.data === 响应体，所以 results 在 r.data.data.results
            // （与 SingleParse.vue 的 raw?.data ?? raw 解包方式一致）
            const results = (r as any).data?.data?.results ?? (r as any).data?.results ?? []
            for (const res of results) {
                const item = items.value.find((i) => i.url === res.url)
                if (!item) continue
                if (res.ok) {
                    item.status = 'ready'
                    const fi = res.data?.data?.feedInfo
                    item.videoUrl = fi?.h264VideoInfo?.videoUrl || fi?.h265VideoInfo?.videoUrl || fi?.videoUrl || ''
                    item.originVideoUrl = fi?.originVideoUrl || ''
                    item.description = fi?.description || ''
                    item.feedInfo = fi
                } else {
                    item.status = 'failed'
                    item.error = res.error
                }
                // 2026-06-16:每个 results[i] 都带 history_id(成功/失败都有),
                // 失败时为空串。下载成功后用此 id 调 markSphDownloaded。
                item.historyId = (res as any).history_id || item.historyId || ''
            }
        } catch (e: any) {
            for (const item of parsingItems) {
                item.status = 'failed'
                item.error = e?.message || 'parse failed'
            }
            return
        }

        // 2026-06-16 优化:从串行 for...of 改为并发池,UI 上 N 个 item 状态同时变 'downloading'。
        // downloadDirectly 内部已 mark item.status='downloading',并发安全:每个 item 状态独立。
        // 失败由 downloadDirectly 内部 catch 后写到 item.error,不再向外抛。
        const readyItems = items.value.filter((i) => i.status === 'ready')
        for (const item of readyItems) {
            item.status = 'downloading'
        }
        await runWithConcurrency(readyItems, concurrency, async (item) => {
            try {
                await downloadDirectly(item, raw)
                item.status = 'done'
            } catch (e: any) {
                item.status = 'failed'
                item.error = e?.message || 'download failed'
            }
        })
    }

    function clear() {
        items.value = []
    }

    function remove(id: number) {
        items.value = items.value.filter((i) => i.id !== id)
    }

    return { items, addBatch, processBatch, startParsingTicker, clear, remove }
})
