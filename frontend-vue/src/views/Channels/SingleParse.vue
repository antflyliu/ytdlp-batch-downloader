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
        <NInput
          v-model:value="url"
          :placeholder="t('channels.singleUrlHint')"
          @keydown.enter="onParse"
        />
        <div style="margin-top: 12px;">
          <NButton type="primary" :loading="parsing" @click="onParse">
            {{ t('channels.singleParse') }}
          </NButton>
        </div>
        <div v-if="errorMsg" style="color: var(--error); font-size: 12px; margin-top: 8px;">
          {{ errorMsg }}
        </div>
      </div>
    </div>

    <div v-if="result" class="card" style="margin-top: 16px;">
      <div class="card-body" style="display: flex; gap: 16px;">
        <img
          v-if="result.feedInfo.cover_url"
          :src="result.feedInfo.cover_url"
          style="width: 240px; aspect-ratio: 16/9; object-fit: cover; border-radius: 12px;"
          :alt="result.feedInfo.description || 'cover'"
        />
        <div style="flex: 1; min-width: 0;">
          <h3 style="font-family: var(--font); font-size: 20px; margin-bottom: 8px;">
            {{ result.feedInfo.description || '(无标题)' }}
          </h3>
          <div class="meta-row">
            {{ t('channels.singleAuthor', { name: result.authorInfo.nickname || '匿名' }) }}
          </div>
          <div v-if="result.feedInfo.like_count_fmt" class="meta-row">
            {{ t('channels.singleLikes', { count: result.feedInfo.like_count_fmt }) }}
          </div>
          <div style="margin-top: 12px; display: flex; flex-direction: column; gap: 6px;">
            <NButton
              v-if="result.feedInfo.h264_video_info?.video_url"
              type="primary"
              @click="onDownload"
            >
              {{ t('channels.singleQuality264') }} · {{ t('channels.download') }}
            </NButton>
            <NButton
              v-if="result.feedInfo.h265_video_info?.video_url"
              @click="onDownload"
            >
              {{ t('channels.singleQuality265') }} · {{ t('channels.download') }}
            </NButton>
            <NButton quaternary @click="onCopyUrl">
              {{ t('channels.singleCopyUrl') }}
            </NButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NIcon, NInput, useMessage } from 'naive-ui'
import { Search } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { parseSph, downloadFromSph, type SphParseResult } from '@/api/channels'

const { t } = useI18n()
const message = useMessage()
const url = ref('')
const parsing = ref(false)
const result = ref<SphParseResult | null>(null)
const errorMsg = ref('')

async function onParse() {
  if (!url.value.trim()) return
  parsing.value = true
  errorMsg.value = ''
  result.value = null
  try {
    const r = await parseSph(url.value.trim())
    result.value = (r as any).data ?? (r as any)
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

async function onDownload() {
  if (!url.value.trim()) return
  try {
    await downloadFromSph({ sph_url: url.value.trim() })
    message.success('下载任务已提交')
  } catch (e: any) {
    message.error(e?.response?.data?.error || e?.message || String(e))
  }
}

async function onCopyUrl() {
  const raw = result.value?.feedInfo?.origin_video_url
  if (!raw) return
  try {
    await navigator.clipboard.writeText(raw)
    message.success(t('channels.copiedToClipboard'))
  } catch {
    message.error('复制失败')
  }
}
</script>
