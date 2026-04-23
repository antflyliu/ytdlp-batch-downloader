<template>
  <div class="settings-view p-4">
    <NCard :title="t('settings.title')">
      <NForm :model="formValue" label-placement="left" label-width="140">
        <!-- SaveDirectory -->
        <NFormItem :label="t('settings.saveDirectory')" required>
          <NInput v-model:value="formValue.SaveDirectory" placeholder="/path/to/downloads" />
          <NButton @click="selectDirectory">{{ t('settings.browse') }}</NButton>
        </NFormItem>

        <!-- DownNumber -->
        <NFormItem :label="t('settings.downNumber')">
          <NInputNumber v-model:value="formValue.DownNumber" :min="1" :max="10" />
        </NFormItem>

        <!-- TaskNumber -->
        <NFormItem :label="t('settings.taskNumber')">
          <NInputNumber v-model:value="formValue.TaskNumber" :min="1" :max="32" />
        </NFormItem>

        <!-- FilenameLen -->
        <NFormItem :label="t('settings.filenameLen')">
          <NInputNumber v-model:value="formValue.FilenameLen" :min="1" :max="255" />
        </NFormItem>

        <!-- FilenameTime -->
        <NFormItem :label="t('settings.filenameTime')">
          <NSwitch v-model:value="formValue.FilenameTime" />
        </NFormItem>

        <!-- InsertTail -->
        <NFormItem :label="t('settings.insertTail')">
          <NSwitch v-model:value="formValue.InsertTail" />
        </NFormItem>

        <!-- Save button -->
        <NFormItem>
          <NButton type="primary" @click="saveSettings" :loading="saving">
            {{ t('settings.save') }}
          </NButton>
        </NFormItem>
      </NForm>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NCard, NForm, NFormItem, NInput, NInputNumber, NSwitch, NButton } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import axios from 'axios'

const { t } = useI18n()
const $message = (window as any).$message

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000'
const token = (window as any).__MONITOR_API_TOKEN__ || ''

const saving = ref(false)
const formValue = ref({
  SaveDirectory: '',
  DownNumber: 3,
  TaskNumber: 8,
  FilenameLen: 100,
  FilenameTime: false,
  InsertTail: true,
})

onMounted(async () => {
  try {
    const resp = await axios.get(`${API_BASE}/api/proxy/config`, {
      params: { api_token: token }
    })
    const data = resp.data
    formValue.value = {
      SaveDirectory: data.SaveDirectory || '',
      DownNumber: data.DownNumber || 3,
      TaskNumber: data.TaskNumber || 8,
      FilenameLen: data.FilenameLen || 100,
      FilenameTime: data.FilenameTime ?? false,
      InsertTail: data.InsertTail ?? true,
    }
  } catch (e) {
    $message.error(t('settings.loadFailed'))
  }
})

const saveSettings = async () => {
  if (!formValue.value.SaveDirectory) {
    $message.warning(t('settings.directoryRequired'))
    return
  }
  saving.value = true
  try {
    // Step 1: Save to Python config.json
    await axios.post(
      `${API_BASE}/api/config`,
      { download_output_path: formValue.value.SaveDirectory },
      { headers: { Authorization: `Bearer ${token}` } }
    )
    // Step 2: Sync to Go
    await axios.post(
      `${API_BASE}/api/proxy/config`,
      { SaveDirectory: formValue.value.SaveDirectory },
      { headers: { Authorization: `Bearer ${token}` } }
    )
    $message.success(t('settings.saved'))
  } catch (e: any) {
    $message.error(e.message || t('settings.saveFailed'))
  } finally {
    saving.value = false
  }
}

const selectDirectory = () => {
  // For web, this would typically use an<input type="file" webkitdirectory>
  // Or open a native dialog via pywebview
  $message.info(t('settings.selectDirectoryTip'))
}
</script>