<template>
  <div>
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">
            <NIcon><CloudUpload /></NIcon>
          </div>
          <span>{{ t('channels.queueStart') }}</span>
        </div>
      </div>
      <div class="card-body">
        <div class="form-hint">{{ t('channels.queueUrlsHint') }}</div>
        <NInput
          v-model:value="urlText"
          type="textarea"
          :rows="6"
          :placeholder="t('channels.singleUrlHint')"
        />
        <div class="sph-form-row" style="margin-top: 12px;">
          <!-- 2026-06-16 简化:仅保留 raw 选项(对应 originVideoUrl,无水印/无转码)。
               best/1080p/720p/480p 在浏览器侧直传模式下完全等价(详见 sphQueue.ts 注释) -->
          <NCheckbox v-model:checked="downloadRaw">
            {{ t('channels.queueDownloadRaw') }}
          </NCheckbox>
        </div>
        <div style="display: flex; gap: 8px; margin-top: 12px;">
          <NButton type="primary" :loading="processing" @click="onStart">
            {{ t('channels.queueStart') }}
          </NButton>
          <NButton @click="onClear" :disabled="store.items.length === 0">
            {{ t('channels.queueClear') }}
          </NButton>
        </div>
      </div>
    </div>

    <div v-if="store.items.length > 0" class="card" style="margin-top: 16px;">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">
            <NIcon><List /></NIcon>
          </div>
          <span>队列状态 ({{ store.items.length }})</span>
        </div>
      </div>
      <div class="card-body">
        <div class="sph-queue-list">
          <div v-for="item in store.items" :key="item.id" class="sph-queue-item">
            <span class="sph-queue-item__status">
              <span v-if="item.status === 'parsing'" class="status-badge status-badge--warn">
                {{ t('channels.queueParsing', { elapsed: item.parsingElapsed ?? 0 }) }}
              </span>
              <span v-else-if="item.status === 'ready'" class="status-badge status-badge--accent">
                {{ t('channels.queueReady') }}
              </span>
              <span v-else-if="item.status === 'downloading'" class="status-badge status-badge--accent">
                {{ t('channels.queueDownloading', { pct: item.progress ?? 0 }) }}
              </span>
              <span v-else-if="item.status === 'done'" class="status-badge status-badge--ok">
                {{ t('channels.queueDone', { size: item.size || '' }) }}
              </span>
              <span v-else class="status-badge status-badge--err">
                {{ t('channels.queueFailed', { error: item.error || '' }) }}
              </span>
            </span>
            <span style="flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              {{ item.description || item.url }}
            </span>
            <span v-if="item.error && item.status === 'downloading'" class="sph-queue-item__hint">
              {{ item.error }}
            </span>
            <NButton size="small" quaternary @click="store.remove(item.id)">×</NButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { NButton, NCheckbox, NIcon, NInput, useMessage } from 'naive-ui'
import { CloudUpload, List } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useSphQueueStore } from '@/stores/sphQueue'

const { t } = useI18n()
const message = useMessage()
const store = useSphQueueStore()

let stopTicker: (() => void) | null = null
onMounted(() => {
    stopTicker = store.startParsingTicker()
})
onBeforeUnmount(() => {
    stopTicker?.()
    stopTicker = null
})

const urlText = ref('')
// 2026-06-16 简化:仅保留 raw 单一选项。
// 选 true → 下载 originVideoUrl(原始无水印/无转码版本)
// 选 false → 下载 h264VideoInfo/h265VideoInfo/videoUrl(默认清晰度,WeChat API 自定)
const downloadRaw = ref(false)
const processing = ref(false)

async function onStart() {
    const urls = urlText.value.split('\n').map((s) => s.trim()).filter(Boolean)
    if (urls.length === 0) {
        message.warning(t('channels.singleUrlHint'))
        return
    }
    if (urls.length > 50) {
        message.error(t('channels.queueUrlsHint'))
        return
    }
    store.addBatch(urls)
    urlText.value = ''
    processing.value = true
    try {
        await store.processBatch(downloadRaw.value)
    } finally {
        processing.value = false
    }
}

function onClear() {
    store.clear()
}
</script>
