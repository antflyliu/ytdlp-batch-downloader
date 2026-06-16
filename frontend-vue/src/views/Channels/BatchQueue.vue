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
        <div class="sph-form-row" style="margin-top: 12px;">
          <!-- 2026-06-16:并发下载控制。
               浏览器→WeChat CDN 多连接可大幅加速(从串行 ~N 倍降为 ~N/3 倍),
               但并发过高会触发浏览器内存压力和潜在的 CDN 限流,默认 3 与解析阶段对齐 -->
          <span class="sph-label">{{ t('channels.queueConcurrency') }}</span>
          <NSlider
            v-model:value="concurrency"
            :min="1"
            :max="10"
            :step="1"
            :marks="{ 1: '1', 3: '3', 5: '5', 10: '10' }"
            style="width: 240px; flex: 0 0 240px;"
          />
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
import { NButton, NCheckbox, NIcon, NInput, NSlider, useMessage } from 'naive-ui'
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
// 2026-06-16 新增:并发下载数。1=串行(最保守),3=默认(对齐解析阶段),5/10=激进。
// 高并发触发风险:浏览器内存压力、WeChat CDN 限流、Chrome "允许下载多个文件" 弹窗。
const concurrency = ref(3)
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
        await store.processBatch(downloadRaw.value, concurrency.value)
    } finally {
        processing.value = false
    }
}

function onClear() {
    store.clear()
}
</script>
