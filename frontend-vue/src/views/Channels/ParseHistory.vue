<template>
  <div>
    <div class="filter-bar" style="margin-bottom: 16px; display: flex; gap: 12px;">
      <NInput
        v-model:value="keyword"
        :placeholder="t('channels.historySearch')"
        clearable
        style="max-width: 360px"
        @update:value="onSearchDebounced"
      />
    </div>

    <div v-if="items.length === 0" class="empty-state">
      <div class="empty-state__icon">
        <NIcon :size="24"><FilmOutline /></NIcon>
      </div>
      <div class="empty-state__title">{{ t('channels.historyEmpty') }}</div>
    </div>

    <div v-else class="sph-history-grid">
      <div
        v-for="item in items"
        :key="item.id"
        class="sph-history-card sph-history-card--no-cover"
      >
        <div class="sph-history-card__body">
          <div class="sph-history-card__title">{{ item.video_title || '(无标题)' }}</div>
          <div class="sph-history-card__meta">
            <span>{{ item.author_nickname || '匿名' }}</span>
            <span>·</span>
            <span>{{ formatTime(item.parsed_at) }}</span>
          </div>
          <div>
            <span v-if="item.downloaded" class="status-badge status-badge--ok">
              {{ t('channels.downloaded') }}
            </span>
            <span v-else class="status-badge">{{ t('channels.download') }}</span>
          </div>

          <div class="sph-history-card__actions">
            <NButton
              type="primary"
              size="tiny"
              :loading="downloading[item.id] === 'h264'"
              :disabled="!canDownload(item)"
              @click="onDownload(item, 'h264')"
            >
              {{ t('channels.singleQuality264') }} · {{ t('channels.download') }}
            </NButton>
            <NButton
              size="tiny"
              :loading="downloading[item.id] === 'h265'"
              :disabled="!canDownload(item)"
              @click="onDownload(item, 'h265')"
            >
              {{ t('channels.singleQuality265') }} · {{ t('channels.download') }}
            </NButton>
            <NButton
              size="tiny"
              :loading="downloading[item.id] === 'raw'"
              :disabled="!canDownload(item)"
              @click="onDownload(item, 'raw')"
            >
              {{ t('channels.singleDownloadRaw') }}
            </NButton>
          </div>

          <div class="sph-history-card__row">
            <NButton
              size="tiny"
              quaternary
              :loading="reparsing[item.id]"
              @click="onReparse(item)"
            >
              {{ t('channels.historyReparse') }}
            </NButton>
            <span v-if="item.parse_status === 'failed'" class="status-badge status-badge--err">
              {{ t('channels.historyParseFailed') }}
            </span>
            <span v-else-if="reparsedAt[item.id]" class="sph-history-card__hint">
              {{ t('channels.historyReparsedAt', { time: formatTime(reparsedAt[item.id]!) }) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="total > limit" style="margin-top: 16px; display: flex; justify-content: center;">
      <NPagination
        v-model:page="page"
        :page-count="Math.ceil(total / limit)"
        @update:page="loadPage"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { NButton, NIcon, NInput, NPagination, useMessage } from 'naive-ui'
import { FilmOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { listSphHistory, parseSph, type SphHistoryItem } from '@/api/channels'

const { t } = useI18n()
const message = useMessage()
const items = ref<SphHistoryItem[]>([])
const total = ref(0)
const page = ref(1)
const limit = 20
const keyword = ref('')

const downloading = reactive<Record<string, '' | 'h264' | 'h265' | 'raw'>>({})
const reparsing = reactive<Record<string, boolean>>({})
const reparsedAt = reactive<Record<string, string | null>>({})

let searchTimer: number | null = null

/**
 * 选择当前质量的视频 URL：
 *   - h264 → h264VideoUrl 或 videoUrl 兜底
 *   - h265 → h265VideoUrl
 *   - raw  → videoUrl（即解析的 originVideoUrl，无水印/转码版本）
 */
function pickVideoUrl(item: SphHistoryItem, kind: 'h264' | 'h265' | 'raw'): string {
    if (kind === 'h264') return item.h264_video_url || item.video_url || ''
    if (kind === 'h265') return item.h265_video_url || ''
    return item.video_url || ''
}

function canDownload(item: SphHistoryItem): boolean {
    return Boolean(pickVideoUrl(item, 'h264') || pickVideoUrl(item, 'h265') || pickVideoUrl(item, 'raw'))
}

function sanitizeFilename(desc?: string, parsedAt?: string): string {
    if (desc) return desc.replace(/[\\/:*?"<>|]/g, '').trim().slice(0, 200) + '.mp4'
    if (parsedAt) {
        const d = new Date(parsedAt)
        if (!isNaN(d.getTime())) {
            const pad = (n: number) => String(n).padStart(2, '0')
            return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}.mp4`
        }
    }
    return 'video.mp4'
}

async function downloadDirectly(item: SphHistoryItem, kind: 'h264' | 'h265' | 'raw'): Promise<void> {
    const url = pickVideoUrl(item, kind)
    if (!url) {
        message.warning(t('channels.historyNoUrl'))
        return
    }
    const prev = downloading[item.id] || ''
    downloading[item.id] = kind
    let blobUrl: string | null = null
    try {
        const resp = await fetch(url)
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const blob = await resp.blob()
        blobUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = blobUrl
        a.download = sanitizeFilename(item.video_title, item.parsed_at)
        a.style.display = 'none'
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
    } catch (e: any) {
        // 链接可能过期：提示用户重新解析
        message.error(t('channels.singleDownloadFailed', { msg: e?.message || String(e) }))
    } finally {
        if (blobUrl) URL.revokeObjectURL(blobUrl)
        downloading[item.id] = prev
    }
}

async function onDownload(item: SphHistoryItem, kind: 'h264' | 'h265' | 'raw') {
    await downloadDirectly(item, kind)
}

async function loadPage() {
    try {
        const r = await listSphHistory({
            limit,
            offset: (page.value - 1) * limit,
            keyword: keyword.value || undefined,
        })
        items.value = (r as any).data?.data?.items ?? (r as any).data?.items ?? []
        total.value = (r as any).data?.data?.total ?? (r as any).data?.total ?? 0
    } catch (e: any) {
        message.error(e?.response?.data?.error || e?.message || String(e))
    }
}

async function onReparse(item: SphHistoryItem) {
    if (!item.sph_url) {
        message.warning(t('channels.historyNoSphUrl'))
        return
    }
    reparsing[item.id] = true
    try {
        // 修复：重新解析直接走 /api/channels/parse_sph?url=<sph_url>，
        // 不复用 /api/channels/history（之前是错误设计）。
        const r = await parseSph(item.sph_url)
        // parseSph 响应形状：{ ok, data: { authorInfo, feedInfo } }，axios 把它放在 r.data
        const payload = (r as any).data?.data ?? (r as any).data ?? r
        const fi = payload?.feedInfo || {}
        const ai = payload?.authorInfo || {}
        const nowIso = new Date().toISOString()
        const idx = items.value.findIndex((it) => it.id === item.id)
        if (idx >= 0) {
            const old = items.value[idx]
            // 保留 downloaded / downloaded_path / downloaded_at：重新解析不该清空下载状态
            items.value[idx] = {
                ...old,
                video_url: fi.originVideoUrl || fi.videoUrl || old.video_url,
                h264_video_url: (fi.h264VideoInfo || {}).videoUrl || old.h264_video_url || '',
                h265_video_url: (fi.h265VideoInfo || {}).videoUrl || old.h265_video_url || '',
                cover_url: fi.coverUrl || old.cover_url,
                video_title: fi.description || old.video_title,
                description: fi.description || old.description,
                author_nickname: ai.nickname || old.author_nickname,
                parsed_at: nowIso,
            }
        }
        reparsedAt[item.id] = nowIso
        message.success(t('channels.historyReparseOk'))
    } catch (e: any) {
        const code = e?.response?.data?.code
        if (code === 'NO_COOKIE') {
            message.error(t('channels.noCookieRedirect'))
        } else {
            message.error(t('channels.historyReparseFailed', { msg: e?.response?.data?.error || e?.message || String(e) }))
        }
    } finally {
        reparsing[item.id] = false
    }
}

function onSearchDebounced() {
  if (searchTimer !== null) clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    page.value = 1
    loadPage()
  }, 300)
}

function formatTime(iso: string) {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const now = Date.now()
  const diffMin = Math.floor((now - d.getTime()) / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  if (diffMin < 1440) return `${Math.floor(diffMin / 60)}小时前`
  return d.toLocaleDateString('zh-CN')
}

onMounted(loadPage)
</script>

<style scoped>
.sph-history-card {
  display: flex;
  flex-direction: column;
}

/* 修复：列表中不渲染 cover_url（cover_url 来自 finder.video.qq.com 的 stodownload，
   任何 GET 都会被算作"调用下载接口"）。仅在用户主动点下载时再请求视频 URL。*/
.sph-history-card--no-cover {
  border-left: 3px solid var(--accent);
}

.sph-history-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.sph-history-card__row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 11px;
}

.sph-history-card__hint {
  color: var(--text-dim);
}
</style>
