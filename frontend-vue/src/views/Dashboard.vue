<template>
  <div>
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('nav.dashboard') }}</div>
      </div>
    </div>

    <!-- Stats grid -->
    <div class="card">
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('dashboard.statAccounts') }}</div>
          <div class="stat-value">{{ accountCount }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('dashboard.statScans') }}</div>
          <div class="stat-value">{{ totalScans }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('dashboard.statNew') }}</div>
          <div class="stat-value">{{ totalNewVideos }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('dashboard.statQuota') }}</div>
          <div class="stat-value">{{ quotaPercent }}%</div>
          <div class="progress-bar-wrap">
            <div class="progress-bar-track">
              <div class="progress-bar-fill" :style="{ width: quotaPercent + '%', background: quotaColor }"></div>
            </div>
          </div>
          <div class="stat-sub">{{ quotaUsed.toLocaleString() }} / {{ quotaLimit.toLocaleString() }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('dashboard.statLast') }}</div>
          <div class="stat-value stat-value--sm">{{ lastScanTime }}</div>
        </div>
      </div>
    </div>

    <!-- Event log -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon" aria-hidden="true">事</div>
          <span>{{ t('dashboard.eventLog') }}</span>
        </div>
        <div class="text-dim text-xs">{{ t('dashboard.eventCount', { n: events.length }) }}</div>
      </div>
      <div class="card-body">
        <div class="log-area" ref="logAreaRef">
          <template v-if="loadingEvents">
            <div class="log-line">
              <span class="log-time">—</span>
              <span class="log-msg">{{ t('common.loading') }}</span>
            </div>
          </template>
          <template v-else-if="events.length === 0">
            <div class="empty-state" style="padding: 24px">
              <div class="empty-title" style="font-size: 13px">{{ t('dashboard.noRecords') }}</div>
            </div>
          </template>
          <template v-else>
            <div
              v-for="ev in events"
              :key="ev.id"
              class="log-line"
            >
              <span class="log-time">{{ formatTime(ev.scan_started_at) }}</span>
              <span class="log-msg" :class="logMsgClass(ev.status)">{{ formatEventMsg(ev) }}</span>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'
import { useEventStore } from '@/stores/eventStore'
import request from '@/api/request'

const { t } = useI18n()
const message = useMessage()
const eventStore = useEventStore()

// ── Stats state ──────────────────────────────────────────────────────────────
interface AccountStat {
  id: number
  name: string
  channel_url: string
  total_scans: number
  total_new_videos: number
  last_scan_at: string
  is_running: boolean
}

interface ScanEvent {
  id: number
  account_name: string
  channel_url: string
  status: string
  total_videos: number
  new_videos: number
  error_message: string
  duration_ms: number
  scan_started_at: string
  scan_ended_at: string
}

interface QuotaItem {
  api_key_env: string
  used: number
  daily_quota: number
  key_name: string
  is_active: boolean
}

const accountStats = ref<AccountStat[]>([])
const events = shallowRef<ScanEvent[]>([])
const quotaItems = ref<QuotaItem[]>([])
const loadingEvents = ref(false)

// ── Computed aggregates ──────────────────────────────────────────────────────
const accountCount = computed(() => accountStats.value.length)
const totalScans = computed(() => accountStats.value.reduce((s, a) => s + (a.total_scans || 0), 0))
const totalNewVideos = computed(() => accountStats.value.reduce((s, a) => s + (a.total_new_videos || 0), 0))
const lastScanTime = computed(() => {
  const latest = accountStats.value
    .map(a => a.last_scan_at)
    .filter(Boolean)
    .sort()
    .reverse()[0]
  return latest ? formatTime(latest) : '—'
})

// Sum quota across all keys
const quotaUsed = computed(() => quotaItems.value.reduce((s, q) => s + (q.used || 0), 0))
const quotaLimit = computed(() => quotaItems.value.reduce((s, q) => s + (q.daily_quota || 0), 0))
const quotaPercent = computed(() => {
  if (quotaLimit.value === 0) return 0
  return Math.min(Math.round((quotaUsed.value / quotaLimit.value) * 100), 100)
})
const quotaColor = computed(() => {
  const p = quotaPercent.value
  if (p >= 90) return 'var(--error)'
  if (p >= 70) return 'var(--warning)'
  return 'var(--accent)'
})

// ── Formatting helpers ───────────────────────────────────────────────────────
const formatTime = (ts: string) => {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  } catch {
    return ts
  }
}

const logMsgClass = (status: string) => {
  if (status === 'success') return 'log-msg--ok'
  if (status === 'error') return 'log-msg--err'
  return 'log-msg--info'
}

const formatEventMsg = (ev: ScanEvent) => {
  if (ev.status === 'success') {
    return `${ev.account_name}: ${t('eventLog.returnedN', { total: ev.total_videos })} ${t('eventLog.newN', { new: ev.new_videos })} ${t('eventLog.durationMs', { ms: ev.duration_ms })}`
  }
  if (ev.status === 'error') {
    return `${ev.account_name}: ${t('eventLog.failed')} ${ev.error_message}`
  }
  return `${ev.account_name}: ${t('eventLog.inProgress')}`
}

// ── Data fetching ────────────────────────────────────────────────────────────
const fetchStats = async () => {
  try {
    const resp = await request.get<AccountStat[]>('/api/stats')
    accountStats.value = Array.isArray(resp.data) ? resp.data : []
  } catch {
    message.warning(t('eventLog.loadFailed'))
  }
}

const fetchEvents = async () => {
  loadingEvents.value = true
  try {
    const resp = await request.get<ScanEvent[]>('/api/events', { params: { limit: 20 } })
    events.value = Array.isArray(resp.data) ? resp.data : []
  } catch {
    message.warning(t('eventLog.loadFailed'))
  } finally {
    loadingEvents.value = false
  }
}

const fetchQuota = async () => {
  try {
    const resp = await request.get<{ items: QuotaItem[] }>('/api/quota')
    const data = resp.data as { items?: QuotaItem[] }
    quotaItems.value = Array.isArray(data?.items) ? data.items : []
  } catch {
    // quota is non-critical
  }
}

// ── SSE scan event handling ───────────────────────────────────────────────────
const logAreaRef = ref<HTMLElement | null>(null)

const handleScanEvent = (data: unknown) => {
  // data may be the event object directly or wrapped
  const ev = (data && typeof data === 'object') ? (data as Partial<ScanEvent>) : null
  if (!ev || !ev.id) return

  const scanEvent: ScanEvent = {
    id: ev.id as number,
    account_name: (ev as any).account_name || '',
    channel_url: (ev as any).channel_url || '',
    status: (ev as any).status || 'info',
    total_videos: (ev as any).total_videos || 0,
    new_videos: (ev as any).new_videos || 0,
    error_message: (ev as any).error_message || '',
    duration_ms: (ev as any).duration_ms || 0,
    scan_started_at: (ev as any).scan_started_at || new Date().toISOString(),
    scan_ended_at: (ev as any).scan_ended_at || '',
  }

  // Prepend new event, keep max 20
  events.value = [scanEvent, ...events.value].slice(0, 20)

  // Refresh stats after a new scan event
  fetchStats()
  fetchQuota()
}

// ── Lifecycle ────────────────────────────────────────────────────────────────
onMounted(async () => {
  await Promise.all([fetchStats(), fetchEvents(), fetchQuota()])
  eventStore.addHandle('scanEvent', handleScanEvent)
})

onUnmounted(() => {
  eventStore.removeHandle('scanEvent')
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 0 0 16px;
  gap: 16px;
}
.page-title {
  font-family: var(--font);
  font-size: 20px;
  font-weight: 500;
  color: var(--text);
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  overflow: hidden;
  flex-shrink: 0;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  gap: 12px;
}
.card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-title-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  background: var(--accent-dim);
  color: var(--accent);
}
.card-body {
  padding: 16px 20px;
}

/* Stats grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  padding: 16px 20px;
}
@media (max-width: 900px) {
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}
@media (max-width: 600px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
.stat-card {
  background: var(--surface2);
  border-radius: var(--r-md);
  padding: 14px 16px;
  border: 1px solid var(--border);
}
.stat-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 6px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text);
  font-family: var(--mono);
}
.stat-value--sm {
  font-size: 14px;
}

/* Quota progress bar */
.progress-bar-wrap {
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 4px;
}
.progress-bar-track {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}
.progress-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}
.stat-sub {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

/* Log area */
.log-area {
  background: var(--bg);
  border-radius: var(--r-md);
  padding: 12px 16px;
  max-height: 240px;
  overflow-y: auto;
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.8;
  color: var(--text-muted);
}
.log-line {
  display: flex;
  gap: 8px;
}
.log-time {
  color: var(--text-dim);
  flex-shrink: 0;
}
.log-msg {
  color: var(--text-muted);
}
.log-msg--ok {
  color: var(--success);
}
.log-msg--err {
  color: var(--error);
}
.log-msg--info {
  color: var(--accent);
}

/* Empty state */
.empty-state {
  text-align: center;
  padding: 24px;
  color: var(--text-muted);
}
.empty-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--text);
}

.text-dim {
  font-size: 11px;
  color: var(--text-dim);
}
.text-xs {
  font-size: 11px;
}
</style>
