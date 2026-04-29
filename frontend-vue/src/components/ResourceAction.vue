<template>
  <div class="resource-action">
    <!-- Download button -->
    <NButton
      v-if="canDownload(row)"
      type="success"
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
import { NButton, NPopconfirm, NDropdown } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import axios from 'axios'
import type { MediaInfo } from '@/stores/resourceStore'
// @ts-ignore
import { getDecryptionArray } from '@/assets/js/decrypt.js'

const props = defineProps<{ row: MediaInfo }>()
const emit = defineEmits<{
  (e: 'delete', urlSign: string): void
}>()

const { t } = useI18n()
const $message = (window as any).$message

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000'
const token = (window as any).__MONITOR_API_TOKEN__ || ''

const canDownload = (row: MediaInfo) => {
  return row.Classify !== 'live' && row.Classify !== 'm3u8'
}

const uint8ArrayToBase64 = (bytes: any) => {
  return window.btoa(Array.from(bytes, (byte: any) => String.fromCharCode(byte)).join(''))
}

const handleDownload = async () => {
  try {
    // Transform DecodeKey to decodeStr like master version:
    // 1. Use ISAAC64 WASM to generate 128KB keystream from DecodeKey
    // 2. Convert to base64 for transmission to Go backend
    const decodeStr = props.row.DecodeKey
      ? uint8ArrayToBase64(getDecryptionArray(props.row.DecodeKey))
      : ''

    const payload = { ...props.row, decodeStr }
    const resp = await axios.post(
      `${API_BASE}/api/res/download`,
      payload,
      { headers: { Authorization: `Bearer ${token}` } }
    )
    const data = resp.data
    if (data && data.code === 1) {
      $message.success(t('message.downloadSuccess'))
    } else if (data && data.error) {
      $message.error(data.error || t('message.downloadFailed'))
    } else if (data && data.message) {
      $message.error(data.message)
    } else {
      $message.error(t('message.downloadFailed'))
    }
  } catch (e: any) {
    // Axios wraps the error; access response data safely
    const errData = e.response?.data
    // errData could be an object {error, ...} or a plain string from Go http.Error()
    if (errData && typeof errData === 'object' && errData.error) {
      $message.error(errData.error)
    } else if (errData && typeof errData === 'object' && errData.message) {
      $message.error(errData.message)
    } else if (typeof errData === 'string' && errData.length > 0) {
      $message.error(errData)
    } else {
      $message.error(e.message || t('message.downloadFailed'))
    }
  }
}

const handleDelete = () => {
  emit('delete', props.row.UrlSign)
}

const copyLink = () => {
  navigator.clipboard.writeText(props.row.Url)
  $message.success(t('message.copied'))
}

const openInBrowser = () => {
  window.open(props.row.Url, '_blank')
}

const copyJson = () => {
  navigator.clipboard.writeText(JSON.stringify(props.row, null, 2))
  $message.success(t('message.copied'))
}

const wechatDecrypt = () => {
  // DecodeKey present - trigger decrypt flow
  // Opens Preview modal in decrypt mode
  $message.info(t('message.decryptNotImplemented'))
}

const moreOptions = computed(() => [
  { label: t('action.copyLink'), key: 'copyLink' },
  { label: t('action.openBrowser'), key: 'openBrowser' },
  { label: t('action.copyJson'), key: 'copyJson' },
  ...(props.row.DecodeKey ? [{ label: t('action.wechatDecrypt'), key: 'wechatDecrypt' }] : []),
])

const handleSelect = (key: string) => {
  switch (key) {
    case 'copyLink': copyLink(); break
    case 'openBrowser': openInBrowser(); break
    case 'copyJson': copyJson(); break
    case 'wechatDecrypt': wechatDecrypt(); break
  }
}
</script>

<style scoped>
.resource-action {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  min-width: max-content;
  padding: 2px;
  border-radius: 12px;
  background: #fffdf8;
  box-shadow: 0 0 0 1px rgba(20, 20, 19, 0.04);
  white-space: nowrap;
}

.resource-action :deep(.n-button) {
  min-width: 76px;
  flex-shrink: 0;
}

.resource-action :deep(.n-button:last-child) {
  min-width: 64px;
}
</style>
