<template>
  <div class="ai-voice-page">
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('aiVoice.title') }}</div>
        <div class="page-desc">{{ t('aiVoice.desc') }}</div>
      </div>
      <div class="page-actions">
        <NButton tertiary :loading="providersLoading" @click="loadProviders">
          {{ t('aiVoice.refreshProviders') }}
        </NButton>
        <NButton tertiary :loading="tasksLoading" @click="refreshTasks">
          {{ t('aiVoice.refreshTasks') }}
        </NButton>
      </div>
    </div>

    <div class="ai-voice-grid">
      <NCard class="ai-voice-card" :title="t('aiVoice.synthesisTitle')">
        <NAlert type="info" :show-icon="false" class="ai-voice-disclosure">
          {{ t('aiVoice.disclosure') }}
        </NAlert>

        <NForm :model="form" label-placement="top" class="ai-voice-form">
          <NFormItem class="ai-voice-wide" :label="t('aiVoice.text')">
            <NInput
              v-model:value="form.text"
              type="textarea"
              :autosize="{ minRows: 6, maxRows: 12 }"
              :placeholder="t('aiVoice.textPlaceholder')"
            />
          </NFormItem>

          <NFormItem :label="t('aiVoice.provider')">
            <NSelect
              v-model:value="form.provider"
              :options="providerOptions"
              :loading="providersLoading"
              filterable
            />
          </NFormItem>

          <NFormItem :label="t('aiVoice.voice')">
            <NInput v-model:value="form.voice" :placeholder="t('aiVoice.voicePlaceholder')" />
          </NFormItem>

          <NFormItem :label="t('aiVoice.language')">
            <NInput v-model:value="form.language" placeholder="zh-CN" />
          </NFormItem>

          <NFormItem :label="t('aiVoice.format')">
            <NSelect v-model:value="form.response_format" :options="formatOptions" />
          </NFormItem>

          <NFormItem :label="t('aiVoice.speed')">
            <NInputNumber v-model:value="form.speed" :min="0.25" :max="4" :step="0.05" :show-button="false" style="width: 100%" />
          </NFormItem>

          <NFormItem :label="t('aiVoice.mode')">
            <NInput v-model:value="form.mode" :placeholder="t('aiVoice.modePlaceholder')" />
          </NFormItem>
        </NForm>

        <div class="ai-voice-actions">
          <NButton type="primary" :loading="submitting" :disabled="!canSubmit" @click="submitTask">
            {{ t('aiVoice.submit') }}
          </NButton>
          <span class="ai-voice-help">{{ t('aiVoice.submitHint') }}</span>
        </div>
      </NCard>

      <NCard class="ai-voice-card" :title="t('aiVoice.providersTitle')">
        <div v-if="providersLoading" class="ai-voice-empty">
          <NSpin size="small" />
        </div>
        <div v-else-if="!providers.length" class="ai-voice-empty">
          <NEmpty :description="t('aiVoice.noProviders')" />
        </div>
        <div v-else class="provider-list">
          <button
            v-for="provider in providers"
            :key="provider.id"
            type="button"
            class="provider-item"
            :class="{ 'provider-item--active': provider.id === form.provider }"
            @click="form.provider = provider.id"
          >
            <div>
              <div class="provider-item__title">{{ provider.label || provider.id }}</div>
              <div class="provider-item__meta">{{ provider.id }}</div>
            </div>
            <NTag size="small" :bordered="false" :type="provider.configured ? 'success' : 'warning'">
              {{ provider.configured ? t('aiVoice.configured') : t('aiVoice.unconfigured') }}
            </NTag>
          </button>
        </div>
      </NCard>
    </div>

    <NCard class="ai-voice-card" :title="t('aiVoice.tasksTitle')">
      <div v-if="tasksLoading && !tasks.length" class="ai-voice-empty">
        <NSpin size="small" />
      </div>
      <div v-else-if="!tasks.length" class="ai-voice-empty">
        <NEmpty :description="t('aiVoice.noTasks')" />
      </div>
      <div v-else class="voice-task-list">
        <div v-for="task in tasks" :key="taskId(task)" class="voice-task">
          <div class="voice-task__head">
            <div>
              <div class="voice-task__title">{{ task.provider || t('aiVoice.unknownProvider') }}</div>
              <div class="voice-task__meta">
                <span>{{ taskId(task) }}</span>
                <span>{{ formatDateTime(task.updated_at || task.created_at) }}</span>
              </div>
            </div>
            <NTag :bordered="false" :type="statusType(taskStatus(task))">
              {{ statusLabel(taskStatus(task)) }}
            </NTag>
          </div>

          <div class="voice-task__body">
            <div class="voice-task__message">{{ task.message || task.stage || '—' }}</div>
            <div v-if="task.error" class="voice-task__error">{{ task.error }}</div>
            <audio v-if="audioSrc(task)" class="voice-task__audio" :src="audioSrc(task)" controls preload="none"></audio>
          </div>

          <div class="voice-task__foot">
            <span>{{ t('aiVoice.progress', { n: Number(task.progress || 0) }) }}</span>
            <NButton
              v-if="canCancel(task)"
              text
              type="warning"
              size="small"
              :loading="cancellingTaskId === taskId(task)"
              @click="cancelTask(taskId(task))"
            >
              {{ t('aiVoice.cancel') }}
            </NButton>
          </div>
        </div>
      </div>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NAlert,
  NButton,
  NCard,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpin,
  NTag,
  useMessage,
} from 'naive-ui'
import voiceApi, { voiceFileUrl, type VoiceProviderOption, type VoiceSynthesisTaskPayload } from '@/api/voice'

const POLL_INTERVAL_MS = 3000
const TERMINAL_STATUSES = new Set(['done', 'error', 'cancelled', 'interrupted'])

const { t } = useI18n()
const message = useMessage()

const providers = ref<VoiceProviderOption[]>([])
const tasks = ref<Array<Record<string, any>>>([])
const providersLoading = ref(false)
const tasksLoading = ref(false)
const submitting = ref(false)
const cancellingTaskId = ref('')
let pollTimer: number | null = null

const form = reactive<VoiceSynthesisTaskPayload>({
  text: '',
  provider: 'silent',
  flow: 'manual_voice',
  voice: '',
  language: 'zh-CN',
  response_format: 'wav',
  speed: 1,
  mode: '',
  fallback_allowed: true,
})

const providerOptions = computed(() => providers.value.map((provider) => ({
  label: `${provider.label || provider.id}${provider.configured ? '' : ` (${t('aiVoice.unconfigured')})`}`,
  value: provider.id,
})))

const formatOptions = computed(() => [
  { label: 'wav', value: 'wav' },
  { label: 'mp3', value: 'mp3' },
  { label: 'm4a', value: 'm4a' },
])

const canSubmit = computed(() => Boolean(form.text.trim() && form.provider))

const normalizeArray = (value: unknown) => Array.isArray(value) ? value : []

const loadProviders = async () => {
  providersLoading.value = true
  try {
    const res = await voiceApi.listProviders({ capability: 'speech_synthesis', flow: 'manual_voice' })
    providers.value = normalizeArray(res.data?.providers) as VoiceProviderOption[]
    if (!providers.value.some((provider) => provider.id === form.provider) && providers.value.length) {
      form.provider = providers.value[0].id
    }
  } catch (error: any) {
    providers.value = []
    message.error(error?.response?.data?.error || error?.message || t('aiVoice.loadProvidersFailed'))
  } finally {
    providersLoading.value = false
  }
}

const refreshTasks = async () => {
  tasksLoading.value = true
  try {
    const res = await voiceApi.listTasks({ kind: 'synthesis', limit: 20, offset: 0 })
    tasks.value = normalizeArray(res.data?.tasks) as Array<Record<string, any>>
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('aiVoice.loadTasksFailed'))
  } finally {
    tasksLoading.value = false
  }
}

const submitTask = async () => {
  submitting.value = true
  try {
    const payload: VoiceSynthesisTaskPayload = {
      text: form.text.trim(),
      provider: form.provider,
      flow: 'manual_voice',
      mode: form.mode?.trim() || undefined,
      voice: form.voice?.trim() || undefined,
      language: form.language?.trim() || undefined,
      response_format: form.response_format || 'wav',
      speed: form.speed,
      fallback_allowed: form.fallback_allowed,
    }
    const res = await voiceApi.createSynthesisTask(payload)
    const taskId = String(res.data?.task_id || '')
    message.success(taskId ? t('aiVoice.createdWithId', { id: taskId }) : t('aiVoice.created'))
    await refreshTasks()
    startPolling()
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('aiVoice.createFailed'))
  } finally {
    submitting.value = false
  }
}

const cancelTask = async (id: string) => {
  cancellingTaskId.value = id
  try {
    await voiceApi.cancelTask(id)
    message.success(t('aiVoice.cancelRequested'))
    await refreshTasks()
    if (tasks.value.some((task) => !TERMINAL_STATUSES.has(taskStatus(task)))) {
      startPolling()
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('aiVoice.cancelFailed'))
  } finally {
    cancellingTaskId.value = ''
  }
}

const startPolling = () => {
  stopPolling()
  pollTimer = window.setTimeout(async () => {
    await refreshTasks()
    if (tasks.value.some((task) => !TERMINAL_STATUSES.has(taskStatus(task)))) {
      startPolling()
    }
  }, POLL_INTERVAL_MS)
}

const stopPolling = () => {
  if (pollTimer) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

const taskId = (task: Record<string, any>) => String(task.task_id || task.id || '')
const taskStatus = (task: Record<string, any>) => String(task.status || 'pending').toLowerCase()

const canCancel = (task: Record<string, any>) => {
  const status = taskStatus(task)
  return Boolean(taskId(task) && (status === 'pending' || status === 'running' || status === 'cancelling'))
}

const audioSrc = (task: Record<string, any>) => {
  const path = String(task.output_audio_path || '')
  return path && taskStatus(task) === 'done' ? voiceFileUrl(path) : ''
}

const statusLabel = (status: string) => {
  const key = `aiVoice.status.${status}`
  const label = t(key)
  return label === key ? status : label
}

const statusType = (status: string) => {
  if (status === 'done') return 'success'
  if (status === 'error' || status === 'interrupted') return 'error'
  if (status === 'cancelled' || status === 'cancelling') return 'warning'
  return 'info'
}

const formatDateTime = (value: unknown) => {
  const raw = String(value || '')
  if (!raw) return '—'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString()
}

onMounted(async () => {
  await Promise.all([loadProviders(), refreshTasks()])
  if (tasks.value.some((task) => !TERMINAL_STATUSES.has(taskStatus(task)))) {
    startPolling()
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.ai-voice-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ai-voice-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
  gap: 16px;
  align-items: start;
}

.ai-voice-card {
  border-radius: 20px;
}

.ai-voice-disclosure {
  margin-bottom: 16px;
}

.ai-voice-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.ai-voice-wide {
  grid-column: 1 / -1;
}

.ai-voice-actions,
.voice-task__foot,
.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.ai-voice-help,
.provider-item__meta,
.voice-task__meta,
.voice-task__message,
.voice-task__foot {
  color: var(--text-muted);
  font-size: 12px;
}

.ai-voice-empty {
  min-height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.provider-list,
.voice-task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.provider-item,
.voice-task {
  width: 100%;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
}

.provider-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  text-align: left;
  cursor: pointer;
}

.provider-item--active {
  border-color: rgba(201, 100, 66, 0.42);
  box-shadow: 0 0 0 1px rgba(201, 100, 66, 0.14);
}

.provider-item__title,
.voice-task__title {
  color: var(--text);
  font-size: 15px;
  font-weight: 600;
}

.voice-task {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.voice-task__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.voice-task__meta {
  display: flex;
  gap: 10px;
  margin-top: 4px;
  flex-wrap: wrap;
}

.voice-task__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.voice-task__error {
  padding: 10px 12px;
  border: 1px solid rgba(181, 51, 51, 0.22);
  border-radius: 12px;
  background: rgba(181, 51, 51, 0.08);
  color: var(--error);
  font-size: 12px;
  line-height: 1.5;
}

.voice-task__audio {
  width: 100%;
}

.voice-task__foot {
  justify-content: space-between;
}

@media (max-width: 1100px) {
  .ai-voice-grid,
  .ai-voice-form {
    grid-template-columns: 1fr;
  }
}
</style>
