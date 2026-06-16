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
        class="sph-history-card"
      >
        <!-- 2026-06-16:渲染 cover_url(对齐 SingleParse 布局)。
             仍用 loading="lazy" 减少离屏 item 的无效 GET,
             权衡用户对"列表要看到视频/封面"的诉求与 cover 可能算作 download counter 的旧顾虑。
             渲染失败或无 cover_url 时显示 ▶ 渐变占位卡(兜底 #1)。 -->
        <div class="sph-history-card__cover">
          <img
            v-if="item.cover_url && !coverError[item.id]"
            :src="item.cover_url"
            :alt="item.video_title || 'cover'"
            class="sph-history-card__cover-img"
            loading="lazy"
            @error="onCoverError(item.id)"
          />
          <div v-else class="sph-history-card__cover-fallback" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="32" height="32" class="sph-history-card__play-icon">
              <path d="M8 5v14l11-7z" fill="currentColor" />
            </svg>
          </div>
        </div>

        <div class="sph-history-card__meta">
          <!-- 2026-06-16:作者头像 + 名字,镜像 SingleParse 的 sph-author 布局。
               头像失败或无 URL 时显示彩色首字母圆(兜底 #2),颜色由 nickname 哈希固定。 -->
          <div class="sph-author">
            <div class="sph-author__avatar-wrapper">
              <img
                v-if="item.author_avatar_url && !avatarError[item.id]"
                :src="item.author_avatar_url"
                :alt="item.author_nickname || 'avatar'"
                class="sph-author__avatar"
                @error="onAvatarError(item.id)"
              />
              <div
                v-else
                class="sph-author__avatar-fallback"
                :style="{ background: avatarBg(item.author_nickname) }"
                :aria-label="item.author_nickname || t('channels.singleAuthorAnon')"
              >
                {{ avatarInitial(item.author_nickname) }}
              </div>
            </div>
            <span class="sph-author__name">{{ item.author_nickname || t('channels.singleAuthorAnon') }}</span>
          </div>

          <div class="sph-history-card__title">{{ item.video_title || '(无标题)' }}</div>

          <div v-if="item.description" class="sph-history-card__desc">
            {{ item.description }}
          </div>

          <div class="sph-history-card__meta-row">
            <span class="sph-history-card__time">{{ formatTime(item.parsed_at) }}</span>
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
import { listSphHistory, parseSph, markSphDownloaded, type SphHistoryItem } from '@/api/channels'

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
// 2026-06-16 新增:cover/avatar 加载失败标记。failed → 显示兜底 UI。
const coverError = reactive<Record<string, boolean>>({})
const avatarError = reactive<Record<string, boolean>>({})

function onCoverError(id: string) { coverError[id] = true }
function onAvatarError(id: string) { avatarError[id] = true }

/**
 * 把 nickname 哈希成稳定 hue,确保同一作者始终显示同一颜色。
 * hsl(55% 饱和 + 50% 亮度) 保证与白色首字母文字对比度。
 */
function avatarBg(name?: string): string {
    if (!name) return 'hsl(200, 55%, 50%)'
    let hash = 0
    for (let i = 0; i < name.length; i++) {
        hash = (hash * 31 + name.charCodeAt(i)) | 0
    }
    const hue = Math.abs(hash) % 360
    return `hsl(${hue}, 55%, 50%)`
}

function avatarInitial(name?: string): string {
    if (!name || !name.trim()) return '?'
    return name.trim().charAt(0).toUpperCase()
}

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
    let success = false
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
        success = true
    } catch (e: any) {
        // 链接可能过期：提示用户重新解析
        message.error(t('channels.singleDownloadFailed', { msg: e?.message || String(e) }))
    } finally {
        if (blobUrl) URL.revokeObjectURL(blobUrl)
        downloading[item.id] = prev
        // 2026-06-16 新增:下载成功后异步标记 history(失败不抛错,只 console.warn)。
        // item.id 本身就是 history_id,直接从 history 列表下载不用再查找。
        if (success && item.id) {
            const filename = sanitizeFilename(item.video_title, item.parsed_at)
            markSphDownloaded(item.id, filename).catch((e) => {
                console.warn('[sph] mark_downloaded failed:', e)
            })
        }
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
                // 2026-06-16 新增:重新解析后刷新 author_avatar_url,失败时保留旧值
                author_avatar_url: ai.headImgUrl || old.author_avatar_url || '',
                video_title: fi.description || old.video_title,
                description: fi.description || old.description,
                author_nickname: ai.nickname || old.author_nickname,
                parsed_at: nowIso,
            }
        }
        // 2026-06-16 新增:重新解析成功后重置 cover/avatar 错误标记,
        // 新 URL 加载成功后会触发新一轮 onload/onerror。
        delete coverError[item.id]
        delete avatarError[item.id]
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
  flex-direction: row;
  gap: 14px;
  /* 2026-06-16 fix: align-items center 替代 stretch。
     cover 有 aspect-ratio: 16/9 无法被拉伸,stretch 时会停留在顶部留白约 100px。
     改为 center 后,cover 在 meta 比它高时垂直居中,meta 仍占满 (flex: 1 1 0) 不受影响。
     详见 specs/bugfixes/sph-history-cover-centering/report.md */
  align-items: center;
  border-left: 3px solid var(--accent);
}

/* 2026-06-16 新增:cover/avatar 横向布局(对齐 SingleParse) */
.sph-history-card__cover {
  flex: 0 0 auto;
  width: 180px;
  aspect-ratio: 16 / 9;
  border-radius: 8px;
  overflow: hidden;
  background: var(--surface2);
  display: flex;
  align-items: center;
  justify-content: center;
}

.sph-history-card__cover-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

/* 兜底 #1:cover 加载失败/无 URL → 深色渐变 + 居中 ▶ 三角形 */
.sph-history-card__cover-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #2c3e50 0%, #1a252f 100%);
  color: rgba(255, 255, 255, 0.55);
}

.sph-history-card__play-icon {
  display: block;
}

.sph-history-card__meta {
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sph-history-card__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.sph-history-card__desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.sph-history-card__meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-dim);
}

.sph-history-card__time {
  color: var(--text-dim);
}

.sph-history-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.sph-history-card__row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  font-size: 11px;
}

.sph-history-card__hint {
  color: var(--text-dim);
}

/* 2026-06-16 新增:作者行(镜像 SingleParse 的 sph-author 样式) */
.sph-author {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.sph-author__avatar-wrapper {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  position: relative;
  border-radius: 50%;
  overflow: hidden;
  background: var(--surface2);
}

.sph-author__avatar {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

/* 兜底 #2:avatar 加载失败/无 URL → 彩色圆 + nickname 首字母 */
.sph-author__avatar-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  user-select: none;
}

.sph-author__name {
  font-weight: 500;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 2026-06-16 新增:小屏(≤640px)cover 占满一行,meta 在下,镜像 SingleParse */
@media (max-width: 640px) {
  .sph-history-card {
    flex-direction: column;
  }
  .sph-history-card__cover {
    width: 100%;
  }
}
</style>
