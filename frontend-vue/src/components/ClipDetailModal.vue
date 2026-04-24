<template>
  <NModal
    :show="true"
    preset="card"
    :title="t('clipDetail.taskLabel')"
    style="max-width: 800px; width: 90vw"
    :mask-closable="true"
    @update:show="emit('close')"
  >
    <div v-if="loading">
      <NSpin size="medium" />
      <div class="text-sm text-gray-500 mt-2">{{ t('clip.pageLoading') }}</div>
    </div>

    <div v-else-if="detail">
      <!-- Task meta -->
      <div class="task-meta mb-6">
        <NDescriptions :column="2" label-placement="left" size="small">
          <NDescriptionsItem :label="t('clipHistory.tableAccount')">{{ detail.account_name }}</NDescriptionsItem>
          <NDescriptionsItem :label="t('clipHistory.tableTitle')">{{ detail.video_title || t('clip.unknownVideo') }}</NDescriptionsItem>
          <NDescriptionsItem :label="t('clipHistory.tableStatus')">
            <NTag :type="statusTagType(detail.status)" size="small">{{ statusLabel(detail.status) }}</NTag>
          </NDescriptionsItem>
          <NDescriptionsItem :label="t('clipHistory.tableCreated')">{{ formatDate(detail.created_at) }}</NDescriptionsItem>
        </NDescriptions>
      </div>

      <!-- Clips section -->
      <div class="section mb-6">
        <div class="section-title mb-3">{{ t('clipDetail.clips') }} ({{ detail.clips?.length || 0 }})</div>
        <div v-if="!detail.clips?.length" class="text-sm text-gray-400">
          {{ t('clipDetail.noClips') }}
        </div>
        <div v-else class="clip-list">
          <div
            v-for="clip in detail.clips"
            :key="clip.id"
            class="clip-item"
          >
            <div class="clip-info">
              <span class="clip-score">
                <NTag type="success" size="small">{{ t('clip.scoreLabel') }}: {{ clip.score }}</NTag>
              </span>
              <span class="clip-duration text-sm text-gray-500 ml-3">
                {{ formatDuration(clip.duration) }}
              </span>
            </div>
            <NButton
              v-if="clip.video_url"
              size="tiny"
              @click="playClip(clip.video_url)"
            >
              {{ t('clip.clipPlay') }}
            </NButton>
          </div>
        </div>
      </div>

      <!-- Collections section -->
      <div class="section">
        <div class="section-title mb-3">{{ t('clipDetail.collections') }} ({{ detail.collections?.length || 0 }})</div>
        <div v-if="!detail.collections?.length" class="text-sm text-gray-400">
          {{ t('clipDetail.noCollections') }}
        </div>
        <NDataTable
          v-else
          :columns="collectionColumns"
          :data="detail.collections"
          :pagination="false"
          :row-key="(row: CollectionItem) => row.id"
          size="small"
        />
      </div>
    </div>

    <div v-else class="text-red-500">
      {{ t('clip.loadTaskFailed') }}
    </div>

    <template #footer>
      <NButton @click="emit('close')">{{ t('common.cancel') }}</NButton>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NModal, NButton, NTag, NDescriptions, NDescriptionsItem, NDataTable, NSpin, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { ClipTaskDetail, ClipItem, CollectionItem } from '@/api/clips'
import clipsApi from '@/api/clips'

const props = defineProps<{
  id: number
}>()

const emit = defineEmits<{
  close: []
}>()

const { t } = useI18n()
const message = useMessage()

const loading = ref(false)
const detail = ref<ClipTaskDetail | null>(null)

const statusTagType = (status: string) => {
  const map: Record<string, 'default' | 'info' | 'success' | 'error'> = {
    pending: 'default',
    running: 'info',
    done: 'success',
    error: 'error',
  }
  return map[status] || 'default'
}

const statusLabel = (status: string) => {
  const map: Record<string, string> = {
    pending: t('clipHistory.statusPending'),
    running: t('clipHistory.statusRunning'),
    done: t('clipHistory.statusDone'),
    error: t('clipHistory.statusError'),
  }
  return map[status] || status
}

const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString()
  } catch {
    return dateStr
  }
}

const formatDuration = (seconds: number) => {
  if (!seconds) return '0s'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

const playClip = (url: string) => {
  window.open(url, '_blank')
}

const collectionColumns = [
  {
    title: 'ID',
    key: 'id',
    width: 80,
  },
  {
    title: 'Name',
    key: 'name',
    ellipsis: true,
  },
  {
    title: t('clipHistory.tableClips'),
    key: 'clip_count',
    width: 80,
  },
]

onMounted(async () => {
  loading.value = true
  try {
    const res = await clipsApi.detail(props.id)
    detail.value = res.data
  } catch {
    message.error(t('clip.loadTaskFailed'))
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.clip-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}
.clip-item:last-child {
  border-bottom: none;
}
.clip-info {
  display: flex;
  align-items: center;
}
</style>
