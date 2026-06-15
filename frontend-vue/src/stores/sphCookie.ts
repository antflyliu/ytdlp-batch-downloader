import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
    type SphCookieStatus,
    type SphRefreshState,
    getSphCookieStatus,
    saveSphCookie,
    startSphRefresh,
    getSphRefreshStatus,
    cancelSphRefresh,
} from '@/api/channels'

export const useSphCookieStore = defineStore('sphCookie', () => {
    const status = ref<SphCookieStatus | null>(null)
    const refreshState = ref<SphRefreshState>({
        state: 'idle',
        pid: null,
        started_at: null,
        finished_at: null,
        last_error: null,
        cookie_updated: false,
    })
    let pollTimer: number | null = null

    async function fetchStatus() {
        try {
            const r = await getSphCookieStatus()
            // 后端信封: {ok, data: SphCookieStatus}；stores 需要 data 字段
            status.value = (r as any).data ?? (r as any)
        } catch (e) {
            console.error('[sphCookieStore] fetchStatus failed', e)
        }
    }

    async function saveCookie(cookie: string) {
        await saveSphCookie(cookie, 'manual')
        await fetchStatus()
    }

    async function startRefresh() {
        await startSphRefresh()
        await startPolling()
    }

    async function cancelRefresh() {
        await cancelSphRefresh()
        if (pollTimer !== null) {
            clearInterval(pollTimer)
            pollTimer = null
        }
        await fetchStatus()
    }

    async function startPolling() {
        if (pollTimer !== null) return
        await fetchStatus()
        pollTimer = window.setInterval(async () => {
            try {
                const r = await getSphRefreshStatus()
                refreshState.value = (r as any).data ?? (r as any)
            } catch (e) {
                console.error('[sphCookieStore] polling failed', e)
            }
            if (refreshState.value.state === 'success' || refreshState.value.state === 'failed') {
                if (pollTimer !== null) {
                    clearInterval(pollTimer)
                    pollTimer = null
                }
                await fetchStatus()
            }
        }, 2000)
    }

    function stopPolling() {
        if (pollTimer !== null) {
            clearInterval(pollTimer)
            pollTimer = null
        }
    }

    return {
        status,
        refreshState,
        fetchStatus,
        saveCookie,
        startRefresh,
        cancelRefresh,
        startPolling,
        stopPolling,
    }
})
