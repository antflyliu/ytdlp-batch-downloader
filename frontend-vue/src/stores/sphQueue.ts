import { defineStore } from 'pinia'
import { ref } from 'vue'
import { batchParse, downloadFromSph } from '@/api/channels'

export interface QueueItem {
    id: number
    url: string
    status: 'parsing' | 'ready' | 'downloading' | 'done' | 'failed'
    progress?: number
    size?: string
    error?: string
    videoUrl?: string
    historyId?: string
}

export const useSphQueueStore = defineStore('sphQueue', () => {
    const items = ref<QueueItem[]>([])
    let nextId = 1

    function addBatch(urls: string[]) {
        const seen = new Set(items.value.map((i) => i.url))
        for (const u of urls) {
            if (seen.has(u)) continue
            items.value.push({ id: nextId++, url: u, status: 'parsing' })
        }
    }

    async function processBatch(quality = 'best', subLangs = 'zh-Hans,en') {
        const parsingItems = items.value.filter((i) => i.status === 'parsing')
        if (parsingItems.length === 0) return

        const urls = parsingItems.map((i) => i.url)
        try {
            const r = await batchParse(urls, 3)
            const results = (r as any).data?.results ?? (r as any).results ?? []
            for (const res of results) {
                const item = items.value.find((i) => i.url === res.url)
                if (!item) continue
                if (res.ok) {
                    item.status = 'ready'
                    item.videoUrl = res.data?.data?.feedInfo?.originVideoUrl || ''
                } else {
                    item.status = 'failed'
                    item.error = res.error
                }
            }
        } catch (e: any) {
            for (const item of parsingItems) {
                item.status = 'failed'
                item.error = e?.message || 'parse failed'
            }
            return
        }

        for (const item of items.value.filter((i) => i.status === 'ready')) {
            item.status = 'downloading'
            try {
                const dl = await downloadFromSph({
                    sph_url: item.url,
                    quality,
                    sub_langs: subLangs,
                })
                item.historyId = (dl as any).data?.task_id ?? (dl as any).task_id
                item.status = 'done'
            } catch (e: any) {
                item.status = 'failed'
                item.error = e?.message || 'download failed'
            }
        }
    }

    function clear() {
        items.value = []
    }

    function remove(id: number) {
        items.value = items.value.filter((i) => i.id !== id)
    }

    return { items, addBatch, processBatch, clear, remove }
})
