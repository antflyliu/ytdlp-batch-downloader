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
          <span class="sph-label">{{ t('channels.queueQuality') }}</span>
          <NSelect
            v-model:value="quality"
            :options="qualityOptions"
            style="width: 160px"
          />
        </div>
        <div class="sph-form-row">
          <span class="sph-label">{{ t('channels.queueSubLangs') }}</span>
          <NInput v-model:value="subLangs" style="width: 200px" placeholder="zh-Hans,en" />
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
              <span v-if="item.status === 'parsing'" class="status-badge status-badge--warn">解析中</span>
              <span v-else-if="item.status === 'ready'" class="status-badge status-badge--accent">已就绪</span>
              <span v-else-if="item.status === 'downloading'" class="status-badge status-badge--accent">下载中</span>
              <span v-else-if="item.status === 'done'" class="status-badge status-badge--ok">完成</span>
              <span v-else class="status-badge status-badge--err">失败</span>
            </span>
            <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              {{ item.url }}
            </span>
            <span v-if="item.error" style="color: var(--error); font-size: 11px;">{{ item.error }}</span>
            <NButton size="small" quaternary @click="store.remove(item.id)">×</NButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NIcon, NInput, NSelect, useMessage } from 'naive-ui'
import { CloudUpload, List } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useSphQueueStore } from '@/stores/sphQueue'

const { t } = useI18n()
const message = useMessage()
const store = useSphQueueStore()

const urlText = ref('')
const quality = ref('best')
const subLangs = ref('zh-Hans,en')
const processing = ref(false)

const qualityOptions = [
    { label: 'best', value: 'best' },
    { label: '1080p', value: '1080p' },
    { label: '720p', value: '720p' },
    { label: '480p', value: '480p' },
]

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
        await store.processBatch(quality.value, subLangs.value)
    } finally {
        processing.value = false
    }
}

function onClear() {
    store.clear()
}
</script>
