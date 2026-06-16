<template>
  <div>
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">
            <NIcon><Search /></NIcon>
          </div>
          <span>{{ t('channels.tabSingle') }}</span>
        </div>
      </div>
      <div class="card-body">
        <div class="sph-input-row">
          <NInput
            v-model:value="url"
            :placeholder="t('channels.singleUrlHint')"
            @keydown.enter="onParse"
          />
          <NButton type="primary" :loading="parsing" @click="onParse">
            {{ t('channels.singleParse') }}
          </NButton>
        </div>
        <div v-if="parsing" class="sph-status">
          {{ t('channels.singleParsing') }}
        </div>
        <div v-else-if="errorMsg" class="sph-status sph-status--err">
          {{ errorMsg }}
        </div>
      </div>
    </div>

    <div v-if="feedInfo" class="card sph-result" style="margin-top: 16px;">
      <div class="card-header">
        <div class="card-title">
          <span>{{ t('channels.singleResultTitle') }}</span>
        </div>
      </div>
      <div class="card-body">
        <div v-if="feedInfo" class="sph-video-card">
          <div class="sph-video-media">
            <video
              v-if="bestVideoUrl"
              :src="bestVideoUrl"
              :poster="feedInfo.coverUrl"
              controls
              preload="metadata"
            ></video>
            <img
              v-else-if="feedInfo.coverUrl"
              :src="feedInfo.coverUrl"
              :alt="feedInfo.description || 'cover'"
              class="sph-video-cover"
              onerror="this.style.display='none'"
            />
          </div>

          <div class="sph-video-meta">
            <div v-if="authorInfo" class="sph-author">
              <img
                v-if="authorInfo.headImgUrl"
                :src="authorInfo.headImgUrl"
                :alt="authorInfo.nickname || 'avatar'"
                class="sph-author__avatar"
                onerror="this.style.display='none'"
              />
              <span class="sph-author__name">{{ authorInfo.nickname || t('channels.singleAuthorAnon') }}</span>
              <img
                v-if="authorInfo.authIconUrl"
                :src="authorInfo.authIconUrl"
                class="sph-author__badge"
                onerror="this.style.display='none'"
              />
            </div>

            <div v-if="feedInfo.description" class="sph-desc">
              {{ feedInfo.description }}
            </div>

            <div class="sph-stats">
              <span v-if="feedInfo.likeCountFmt" class="sph-stat">
                👍 {{ feedInfo.likeCountFmt }}
              </span>
              <span v-if="feedInfo.favCountFmt" class="sph-stat">
                ❤ {{ feedInfo.favCountFmt }}
              </span>
              <span v-if="feedInfo.forwardCountFmt" class="sph-stat">
                ↗ {{ feedInfo.forwardCountFmt }}
              </span>
              <span v-if="feedInfo.commentCountFmt" class="sph-stat">
                💬 {{ feedInfo.commentCountFmt }}
              </span>
            </div>

            <div class="sph-actions">
              <NButton
                v-if="feedInfo.h264VideoInfo?.videoUrl"
                type="primary"
                size="small"
                :loading="downloading === 'h264'"
                @click="onDownload('h264')"
              >
                {{ t('channels.singleQuality264') }} · {{ t('channels.download') }}
              </NButton>
              <NButton
                v-if="feedInfo.h265VideoInfo?.videoUrl"
                size="small"
                :loading="downloading === 'h265'"
                @click="onDownload('h265')"
              >
                {{ t('channels.singleQuality265') }} · {{ t('channels.download') }}
              </NButton>
              <NButton
                v-if="feedInfo.originVideoUrl"
                size="small"
                :loading="downloading === 'raw'"
                @click="onDownload('raw')"
              >
                {{ t('channels.singleDownloadRaw') }}
              </NButton>
            </div>

            <div v-if="originLink" class="sph-link">
              <a :href="originLink" target="_blank" class="text-link">
                {{ originLink }}
              </a>
            </div>
          </div>
        </div>
      </div>

      <details class="sph-json-section">
        <summary>{{ t('channels.singleJsonRaw') }}</summary>
        <pre class="sph-json-pre">{{ rawJson }}</pre>
      </details>
    </div>

    <div v-if="feedInfo" class="sph-footer">
      {{ t('channels.singleFooter') }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NIcon, NInput, useMessage } from 'naive-ui'
import { Search } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { parseSph } from '@/api/channels'

const { t } = useI18n()
const message = useMessage()

/**
 * 解析结果：后端 parse_sph 直接透传 WeChat API 原始 camelCase 字段
 * (headImgUrl, likeCountFmt, coverUrl, videoUrl, h264VideoInfo, ...)。
 * 在此处用 computed 取值，让模板保持与 wx-sph-parser 静态页一致的字段路径。
 */
const url = ref('')
const parsing = ref(false)
const rawRaw = ref<any>(null)
const errorMsg = ref('')
const downloading = ref<'' | 'h264' | 'h265' | 'raw'>('')

const feedInfo = computed<any>(() => rawRaw.value?.feedInfo || null)
const authorInfo = computed<any>(() => rawRaw.value?.authorInfo || null)

const bestVideoUrl = computed<string>(() => {
  const fi: any = feedInfo.value
  if (!fi) return ''
  return (
    fi.h264VideoInfo?.videoUrl ||
    fi.h265VideoInfo?.videoUrl ||
    fi.videoUrl ||
    ''
  )
})

const originLink = computed<string>(() => {
  const fi: any = feedInfo.value
  if (!fi) return bestVideoUrl.value
  return fi.originVideoUrl || bestVideoUrl.value
})

const rawJson = computed<string>(() => {
  if (!rawRaw.value) return ''
  try {
    return JSON.stringify(rawRaw.value, null, 2)
  } catch {
    return ''
  }
})

async function onParse() {
  if (!url.value.trim()) return
  parsing.value = true
  errorMsg.value = ''
  rawRaw.value = null
  try {
    const r = await parseSph(url.value.trim())
    // 后端返回的是 WeChat API 原始 camelCase 字段
    const raw = (r as any).data ?? (r as any)
    rawRaw.value = raw?.data ?? raw
  } catch (e: any) {
    const status = e?.response?.status
    const code = e?.response?.data?.code
    if (status === 401 && code === 'NO_COOKIE') {
      errorMsg.value = t('channels.noCookieRedirect')
    } else if (code === 'PARSE_FAILED') {
      errorMsg.value = t('channels.errParseFailed', { msg: e.response.data.error })
    } else if (code === 'FEED_FAILED') {
      errorMsg.value = t('channels.errFeedFailed', { msg: e.response.data.error })
    } else if (code === 'TIMEOUT') {
      errorMsg.value = t('channels.errTimeout')
    } else {
      errorMsg.value = e?.response?.data?.error || e?.message || String(e)
    }
  } finally {
    parsing.value = false
  }
}

/**
 * 直接从 finder.video.qq.com 拉 blob 触发浏览器下载。
 * 与 wx-sph-parser 静态页 downloadVideo() 同构 (fetch → blob → a[download])。
 * 不走本服务 /api/channels/download，避免空 task_id 误报。
 */
async function onDownload(kind: 'h264' | 'h265' | 'raw') {
  const fi: any = feedInfo.value
  if (!fi) return
  const videoUrl =
    kind === 'h264' ? fi.h264VideoInfo?.videoUrl :
    kind === 'h265' ? fi.h265VideoInfo?.videoUrl :
    fi.originVideoUrl
  if (!videoUrl) return

  const prev = downloading.value
  downloading.value = kind
  message.info(t('channels.singleDownloading'))
  let blobUrl: string | null = null
  try {
    const resp = await fetch(videoUrl)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    blobUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = sanitizeFilename(fi.description, fi.createtime) || 'video.mp4'
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  } catch (e: any) {
    message.error(t('channels.singleDownloadFailed', { msg: e?.message || String(e) }))
  } finally {
    if (blobUrl) URL.revokeObjectURL(blobUrl)
    downloading.value = prev
  }
}

function sanitizeFilename(desc?: string, createtime?: number): string {
  if (desc) {
    return desc.replace(/[\\/:*?"<>|]/g, '').trim().slice(0, 200) + '.mp4'
  }
  if (createtime) {
    const d = new Date(Number(createtime) * 1000)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}.mp4`
  }
  return ''
}
</script>

<style scoped>
.sph-input-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.sph-input-row > :first-child {
  flex: 1 1 320px;
  min-width: 0;
}

.sph-status {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.5;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--surface2);
}

.sph-status--err {
  color: var(--error);
  background: var(--error-dim);
  border: 1px solid rgba(181, 51, 51, 0.22);
}

.sph-result {
  overflow: hidden;
}

.sph-video-card {
  display: flex;
  gap: 18px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.sph-video-media {
  flex: 0 0 auto;
  width: 320px;
  max-width: 100%;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
  aspect-ratio: 9 / 16;
  display: flex;
  align-items: center;
  justify-content: center;
}

.sph-video-media video,
.sph-video-media .sph-video-cover {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  background: #000;
}

.sph-video-meta {
  flex: 1 1 320px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 14px;
  line-height: 1.55;
}

.sph-author {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.sph-author__avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface2);
}

.sph-author__name {
  font-weight: 600;
  color: var(--text);
}

.sph-author__badge {
  width: 16px;
  height: 16px;
}

.sph-desc {
  color: var(--text-muted);
  word-break: break-all;
  white-space: pre-wrap;
}

.sph-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  color: var(--text-dim);
  font-size: 12px;
}

.sph-stat {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.sph-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.sph-link {
  font-size: 12px;
  word-break: break-all;
  color: var(--text-dim);
}

.sph-link a {
  color: var(--accent);
  text-decoration: none;
}

.sph-link a:hover {
  color: var(--accent-hover);
  text-decoration: underline;
}

.sph-json-section {
  border-top: 1px solid var(--border-cream);
  margin-top: 4px;
}

.sph-json-section summary {
  padding: 10px 22px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
}

.sph-json-pre {
  margin: 0;
  padding: 14px 22px 18px;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-muted);
  background: var(--surface2);
  border-top: 1px solid var(--border-cream);
  max-height: 360px;
  overflow: auto;
  white-space: pre;
}

@media (max-width: 640px) {
  .sph-video-media {
    width: 100%;
    aspect-ratio: 16 / 9;
  }
}

.sph-footer {
  text-align: center;
  margin-top: 32px;
  padding-top: 16px;
  border-top: 1px solid var(--border-cream);
  font-size: 12px;
  color: var(--text-dim);
}
</style>
