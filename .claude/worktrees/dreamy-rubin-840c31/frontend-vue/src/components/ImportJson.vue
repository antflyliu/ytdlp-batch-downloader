<template>
  <div class="import-json">
    <NModal
      v-model:show="showModal"
      :block-scroll="false"
      preset="card"
      :title="t('importJson.title')"
      style="width: 500px"
    >
      <NUpload
        accept=".json"
        :max="1"
        @change="handleFileChange"
        @remove="handleFileRemove"
      >
        <NButton>{{ t('importJson.selectFile') }}</NButton>
      </NUpload>
      <template #footer>
        <div class="flex gap-2 justify-end">
          <NButton @click="showModal = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :disabled="!fileContent" @click="handleImport">
            {{ t('importJson.import') }}
          </NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NModal, NUpload, NButton } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useResourceStore } from '@/stores/resourceStore'
import type { MediaInfo } from '@/stores/resourceStore'

const { t } = useI18n()
const $message = (window as any).$message
const store = useResourceStore()

const showModal = ref(false)
const fileContent = ref<string | null>(null)

const handleFileChange = (options: { file: any }) => {
  const file = options.file
  if (!file) return
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const text = e.target?.result as string
      // Validate it's valid JSON array
      const parsed = JSON.parse(text)
      if (!Array.isArray(parsed)) {
        $message.error(t('importJson.invalidFormat'))
        return
      }
      fileContent.value = text
    } catch {
      $message.error(t('importJson.invalidJson'))
    }
  }
  reader.readAsText(file.file)
}

const handleFileRemove = () => {
  fileContent.value = null
}

const handleImport = () => {
  if (!fileContent.value) return
  try {
    const items: MediaInfo[] = JSON.parse(fileContent.value)
    store.addResources(items)
    store.saveToStorage()
    $message.success(t('importJson.success', { count: items.length }))
    showModal.value = false
    fileContent.value = null
  } catch {
    $message.error(t('importJson.invalidJson'))
  }
}

defineExpose({ showModal })
</script>
