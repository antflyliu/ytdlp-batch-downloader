<template>
  <div class="flex gap-2">
    <!-- Download button -->
    <NButton
      v-if="canDownload(row)"
      type="primary"
      size="small"
      @click="handleDownload"
    >
      {{ t('action.download') }}
    </NButton>
    <NButton v-else type="default" size="small" disabled>
      {{ t('action.download') }}
    </NButton>

    <!-- Delete button -->
    <NPopconfirm @positive-click="handleDelete">
      <template #trigger>
        <NButton type="error" size="small">
          {{ t('action.delete') }}
        </NButton>
      </template>
      {{ t('confirm.delete') }}
    </NPopconfirm>

    <!-- More actions dropdown -->
    <NDropdown
      :options="moreOptions"
      @select="handleSelect"
    >
      <NButton size="small">{{ t('action.more') }}</NButton>
    </NDropdown>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NPopconfirm, NDropdown, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import axios from 'axios'
import type { MediaInfo } from '@/stores/resourceStore'

const props = defineProps<{ row: MediaInfo }>()
const emit = defineEmits<{
  (e: 'delete', urlSign: string): void
}>()

const { t } = useI18n()
const message = useMessage()

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000'
const token = sessionStorage.getItem('monitor_api_token') || ''

const canDownload = (row: MediaInfo) => {
  return row.Classify !== 'live' && row.Classify !== 'm3u8'
}

const handleDownload = async () => {
  try {
    const resp = await axios.post(
      `${API_BASE}/api/res/download`,
      props.row,
      { headers: { Authorization: `Bearer ${token}` } }
    )
    if (resp.data.code === 1) {
      message.success(t('message.downloadSuccess'))
    } else {
      message.error(resp.data.message || t('message.downloadFailed'))
    }
  } catch (e: any) {
    message.error(e.message || t('message.downloadFailed'))
  }
}

const handleDelete = () => {
  emit('delete', props.row.UrlSign)
}

const copyLink = () => {
  navigator.clipboard.writeText(props.row.Url)
  message.success(t('message.copied'))
}

const openInBrowser = () => {
  window.open(props.row.Url, '_blank')
}

const copyJson = () => {
  navigator.clipboard.writeText(JSON.stringify(props.row, null, 2))
  message.success(t('message.copied'))
}

const moreOptions = computed(() => [
  { label: t('action.copyLink'), key: 'copyLink', show: true },
  { label: t('action.openBrowser'), key: 'openBrowser', show: true },
  { label: t('action.copyJson'), key: 'copyJson', show: true },
  // DecodeKey decrypt option if DecodeKey present
].filter(o => o.show !== false))

const handleSelect = (key: string) => {
  switch (key) {
    case 'copyLink': copyLink(); break
    case 'openBrowser': openInBrowser(); break
    case 'copyJson': copyJson(); break
  }
}
</script>
