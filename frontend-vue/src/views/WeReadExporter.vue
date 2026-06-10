<template>
  <div class="weread-page">
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('wereadExporter.title') }}</div>
        <div class="page-desc">{{ t('wereadExporter.desc') }}</div>
      </div>
      <div class="page-actions">
        <NButton tertiary :loading="loadingAll" @click="loadAll">
          {{ t('common.refresh') }}
        </NButton>
      </div>
    </div>

    <NAlert type="warning" :bordered="false">
      {{ t('wereadExporter.notice') }}
    </NAlert>

    <div class="weread-grid">
      <section class="card weread-source-card">
        <div class="card-header">
          <div class="card-title">{{ t('wereadExporter.sourceTitle') }}</div>
        </div>

        <div class="source-body">
          <div class="runtime-strip">
            <div>
              <span>{{ t('wereadExporter.runtime') }}</span>
              <strong>{{ config?.playwright_installed ? t('wereadExporter.runtimeReady') : t('wereadExporter.runtimeMissing') }}</strong>
            </div>
            <div class="runtime-actions">
              <NTag :type="config?.chrome_cdp_available ? 'success' : 'warning'" :bordered="false">
                {{ config?.chrome_cdp_available ? t('wereadExporter.chromeCdpReady') : t('wereadExporter.chromeCdpMissing') }}
              </NTag>
              <NButton
                v-if="config && !config.chrome_cdp_available"
                tertiary
                size="small"
                :loading="startingChrome"
                @click="startChromeCdp"
              >
                {{ t('wereadExporter.startChromeCdp') }}
              </NButton>
            </div>
          </div>

          <NAlert v-if="config && !config.playwright_installed" type="warning" :bordered="false">
            {{ t('wereadExporter.installHint') }}
          </NAlert>

          <NForm :model="form" label-placement="top">
            <NFormItem :label="t('wereadExporter.book')">
              <NInput
                v-model:value="form.book"
                clearable
                placeholder="https://weread.qq.com/web/bookDetail/..."
              />
            </NFormItem>
            <NFormItem :label="t('wereadExporter.outputDir')">
              <NInput v-model:value="form.output_dir" clearable :placeholder="config?.output_root || ''" />
            </NFormItem>
            <NFormItem :label="t('wereadExporter.chromeCdpEndpoint')">
              <NInput v-model:value="form.chrome_cdp_endpoint" clearable placeholder="http://127.0.0.1:9222" />
            </NFormItem>
            <NFormItem :label="t('wereadExporter.chromeCdpProfileDir')">
              <NInput v-model:value="form.chrome_cdp_profile_dir" clearable :placeholder="config?.chrome_cdp_profile_dir || ''" />
            </NFormItem>
            <NFormItem>
              <NCheckbox v-model:checked="form.save_raw">
                {{ t('wereadExporter.saveRaw') }}
              </NCheckbox>
            </NFormItem>
          </NForm>

          <div class="action-row">
            <NButton type="primary" :loading="starting" :disabled="!canStart" @click="startExport">
              {{ t('wereadExporter.start') }}
            </NButton>
            <NButton tertiary @click="fillExample">{{ t('wereadExporter.fillExample') }}</NButton>
          </div>

          <div v-if="config" class="path-list">
            <div>
              <span>{{ t('wereadExporter.outputRoot') }}</span>
              <strong>{{ config.output_root }}</strong>
            </div>
            <div>
              <span>{{ t('wereadExporter.cacheDir') }}</span>
              <strong>{{ config.cache_dir }}</strong>
            </div>
          </div>
        </div>
      </section>

      <section class="card weread-tasks-card">
        <div class="card-header">
          <div class="card-title">{{ t('wereadExporter.tasksTitle') }}</div>
          <NButton tertiary size="small" :loading="loadingTasks" @click="loadTasks">
            {{ t('common.refresh') }}
          </NButton>
        </div>

        <div class="task-layout">
          <div class="task-list">
            <button
              v-for="task in tasks"
              :key="task.task_id"
              type="button"
              class="task-item"
              :class="{ active: selectedTaskId === task.task_id }"
              @click="selectTask(task.task_id)"
            >
              <div class="task-row">
                <strong>{{ task.title || task.book_id || t('wereadExporter.bookFallback') }}</strong>
                <NTag size="small" :bordered="false" :type="statusType(task.status)">
                  {{ statusLabel(task.status) }}
                </NTag>
              </div>
              <div class="task-progress">
                <span>{{ task.completed || 0 }} / {{ task.total || 0 }}</span>
                <span>{{ formatDateTime(task.created_at) }}</span>
              </div>
            </button>
            <NEmpty v-if="!tasks.length" :description="t('wereadExporter.tasksEmpty')" />
          </div>

          <div class="task-detail">
            <NEmpty v-if="!selectedTask" :description="t('wereadExporter.selectTask')" />
            <template v-else>
              <div class="detail-head">
                <div>
                  <div class="detail-title">{{ selectedTask.title || selectedTask.book_id }}</div>
                  <div class="detail-sub">{{ selectedTask.author || selectedTask.current || selectedTask.output_dir }}</div>
                </div>
                <NButton
                  v-if="selectedTask.status === 'running' || selectedTask.status === 'pending'"
                  tertiary
                  type="warning"
                  :loading="cancelling"
                  @click="cancelSelected"
                >
                  {{ t('wereadExporter.cancel') }}
                </NButton>
              </div>

              <div class="progress-card">
                <div class="progress-text">
                  <span>{{ selectedTask.current || statusLabel(selectedTask.status) }}</span>
                  <span>{{ progressPercent }}%</span>
                </div>
                <div class="progress-track">
                  <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
                </div>
              </div>

              <div v-if="selectedTask.error" class="error-box">{{ selectedTask.error }}</div>

              <div class="result-list">
                <div v-for="item in selectedTask.results || []" :key="item.artifact_id || item.path || item.title" class="result-item">
                  <NTag size="small" :bordered="false" :type="resultType(item.status)">
                    {{ resultLabel(item.status) }}
                  </NTag>
                  <div class="result-body">
                    <div class="result-title">{{ item.title || item.artifact_name || item.path }}</div>
                    <div class="result-path">{{ item.error || item.artifact_name || item.path || '—' }}</div>
                  </div>
                  <a
                    v-if="item.artifact_url"
                    class="download-link"
                    :href="item.artifact_url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {{ t('wereadExporter.download') }}
                  </a>
                </div>
                <NEmpty v-if="!(selectedTask.results || []).length" :description="t('wereadExporter.resultsEmpty')" />
              </div>
            </template>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NAlert,
  NButton,
  NCheckbox,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NTag,
  useMessage,
} from 'naive-ui'
import wereadExporterApi, {
  type WeReadExporterConfig,
  type WeReadExportTask,
} from '@/api/wereadExporter'

const POLL_INTERVAL_MS = 2500

const { t } = useI18n()
const message = useMessage()

const config = ref<WeReadExporterConfig | null>(null)
const tasks = ref<WeReadExportTask[]>([])
const selectedTaskId = ref('')
const selectedTask = ref<WeReadExportTask | null>(null)
const loadingAll = ref(false)
const loadingTasks = ref(false)
const starting = ref(false)
const startingChrome = ref(false)
const cancelling = ref(false)
let pollTimer: number | null = null

const form = reactive({
  book: '',
  output_dir: '',
  chrome_cdp_endpoint: '',
  chrome_cdp_profile_dir: '',
  save_raw: true,
})

const canStart = computed(() => Boolean(form.book.trim()) && !starting.value)

const progressPercent = computed(() => {
  const task = selectedTask.value
  if (!task) return 0
  if (task.status === 'done') return 100
  const total = Number(task.total || 0)
  if (!total) return task.status === 'running' ? 8 : 0
  return Math.min(100, Math.round((Number(task.completed || 0) / total) * 100))
})

async function loadConfig() {
  const { data } = await wereadExporterApi.getConfig()
  config.value = data
  if (!form.chrome_cdp_endpoint) {
    form.chrome_cdp_endpoint = data.chrome_cdp_endpoint || 'http://127.0.0.1:9222'
  }
  if (!form.chrome_cdp_profile_dir) {
    form.chrome_cdp_profile_dir = data.chrome_cdp_profile_dir || ''
  }
}

async function loadTasks() {
  loadingTasks.value = true
  try {
    const { data } = await wereadExporterApi.listTasks()
    tasks.value = data.tasks || []
    if (selectedTaskId.value) {
      const found = tasks.value.find(task => task.task_id === selectedTaskId.value)
      if (found) selectedTask.value = found
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wereadExporter.tasksLoadFailed'))
  } finally {
    loadingTasks.value = false
  }
}

async function loadAll() {
  loadingAll.value = true
  try {
    await Promise.all([loadConfig(), loadTasks()])
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wereadExporter.loadFailed'))
  } finally {
    loadingAll.value = false
  }
}

async function startExport() {
  if (!form.book.trim()) return
  starting.value = true
  try {
    const { data } = await wereadExporterApi.start({
      book: form.book.trim(),
      output_dir: form.output_dir.trim() || undefined,
      chrome_cdp_endpoint: form.chrome_cdp_endpoint.trim() || undefined,
      chrome_cdp_profile_dir: form.chrome_cdp_profile_dir.trim() || undefined,
      save_raw: form.save_raw,
    })
    message.success(t('wereadExporter.started'))
    await loadTasks()
    if (data.task_id) {
      await selectTask(data.task_id)
      ensurePolling()
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wereadExporter.startFailed'))
  } finally {
    starting.value = false
  }
}

async function startChromeCdp() {
  startingChrome.value = true
  try {
    const { data } = await wereadExporterApi.startChromeCdp({
      chrome_cdp_endpoint: form.chrome_cdp_endpoint.trim() || undefined,
      chrome_cdp_profile_dir: form.chrome_cdp_profile_dir.trim() || undefined,
    })
    await loadConfig()
    if (data.chrome_cdp_available || data.available) {
      message.success(t('wereadExporter.chromeCdpStarted'))
    } else {
      message.warning(data.error || t('wereadExporter.chromeCdpStartPending'))
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wereadExporter.chromeCdpStartFailed'))
  } finally {
    startingChrome.value = false
  }
}

async function selectTask(taskId: string) {
  selectedTaskId.value = taskId
  try {
    const { data } = await wereadExporterApi.getTask(taskId)
    selectedTask.value = data
    ensurePolling()
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wereadExporter.taskLoadFailed'))
  }
}

async function pollSelectedTask() {
  if (!selectedTaskId.value) return
  try {
    const { data } = await wereadExporterApi.getTask(selectedTaskId.value)
    selectedTask.value = data
    if (!['pending', 'running'].includes(data.status)) {
      stopPolling()
      await loadTasks()
    }
  } catch {
    stopPolling()
  }
}

function ensurePolling() {
  stopPolling()
  if (!['pending', 'running'].includes(selectedTask.value?.status || '')) return
  pollTimer = window.setInterval(() => {
    void pollSelectedTask()
  }, POLL_INTERVAL_MS)
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function cancelSelected() {
  if (!selectedTaskId.value) return
  cancelling.value = true
  try {
    await wereadExporterApi.cancelTask(selectedTaskId.value)
    await pollSelectedTask()
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wereadExporter.cancelFailed'))
  } finally {
    cancelling.value = false
  }
}

function fillExample() {
  form.book = 'https://weread.qq.com/web/bookDetail/dd6324f0813ab9f97g019a24'
}

function statusType(status: string) {
  if (status === 'done') return 'success'
  if (status === 'error') return 'error'
  if (status === 'cancelled' || status === 'interrupted') return 'warning'
  return 'info'
}

function resultType(status: string) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'skipped') return 'warning'
  return 'default'
}

function statusLabel(status: string) {
  return t(`wereadExporter.status.${status}`) || status
}

function resultLabel(status: string) {
  return t(`wereadExporter.resultStatus.${status}`) || status
}

function formatDateTime(value?: string) {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 16)
}

onMounted(() => {
  void loadAll()
})

onUnmounted(stopPolling)
</script>

<style scoped>
.weread-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.weread-grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.9fr) minmax(0, 1.5fr);
  gap: 16px;
  align-items: start;
}

.weread-source-card,
.weread-tasks-card {
  display: flex;
  flex-direction: column;
}

.source-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 22px 22px;
}

.runtime-strip,
.runtime-actions,
.task-row,
.task-progress,
.detail-head,
.progress-text,
.result-item,
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.runtime-strip {
  padding: 4px 0 14px;
  border-bottom: 1px solid var(--border);
}

.runtime-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.runtime-strip span,
.path-list span,
.task-progress,
.detail-sub,
.result-path {
  color: var(--text-muted);
  font-size: 12px;
}

.runtime-strip strong,
.path-list strong {
  display: block;
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: 13px;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.path-list {
  display: grid;
  border-top: 1px solid var(--border);
}

.path-list div {
  display: grid;
  grid-template-columns: minmax(100px, auto) minmax(0, 1fr);
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.task-layout {
  display: grid;
  grid-template-columns: minmax(260px, 0.8fr) minmax(0, 1.2fr);
  gap: 16px;
  min-height: clamp(520px, 68vh, 720px);
  padding: 18px 22px 22px;
}

.task-list,
.result-list {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 10px;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.task-item,
.result-item {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.task-item {
  padding: 12px;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease;
}

.task-item:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.task-item:hover,
.task-item.active {
  border-color: rgba(201, 100, 66, 0.36);
  background: rgba(201, 100, 66, 0.07);
}

.task-row strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-progress {
  margin-top: 8px;
}

.task-detail {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
  padding-left: 16px;
  border-left: 1px solid var(--border);
}

.detail-head {
  align-items: flex-start;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.detail-title {
  color: var(--text);
  font-family: Georgia, serif;
  font-size: 22px;
  font-weight: 500;
  line-height: 1.2;
}

.detail-sub {
  margin-top: 6px;
  overflow-wrap: anywhere;
}

.progress-card {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.progress-track {
  height: 8px;
  margin-top: 10px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(201, 100, 66, 0.1);
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
  transition: width 180ms ease;
}

.progress-text {
  color: var(--text);
  font-size: 13px;
}

.error-box {
  overflow-wrap: anywhere;
  padding: 10px 12px;
  border: 1px solid rgba(208, 48, 80, 0.24);
  border-radius: 8px;
  background: rgba(208, 48, 80, 0.08);
  color: var(--error);
}

.result-list {
  flex: 1 1 auto;
  gap: 0;
}

.result-item {
  align-items: flex-start;
  justify-content: flex-start;
  padding: 12px 0;
  border-width: 0 0 1px;
  border-radius: 0;
  background: transparent;
}

.result-body {
  min-width: 0;
  flex: 1 1 auto;
}

.result-title {
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
}

.result-path {
  margin-top: 4px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.download-link {
  flex: 0 0 auto;
  min-height: 30px;
  padding: 5px 10px;
  border-radius: 8px;
  background: var(--surface3);
  color: var(--accent);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  box-shadow: 0 0 0 1px rgba(201, 100, 66, 0.24);
}

.download-link:hover {
  background: rgba(201, 100, 66, 0.08);
}

@media (max-width: 1080px) {
  .weread-grid,
  .task-layout {
    grid-template-columns: 1fr;
  }

  .task-layout {
    min-height: 0;
  }

  .task-list {
    max-height: min(320px, 44vh);
  }

  .task-detail {
    min-height: 460px;
    padding-top: 16px;
    padding-left: 0;
    border-top: 1px solid var(--border);
    border-left: 0;
  }
}

@media (max-width: 720px) {
  .detail-head,
  .progress-text,
  .result-item {
    align-items: flex-start;
    flex-direction: column;
  }

  .source-body,
  .task-layout {
    padding: 14px 16px 18px;
  }

  .path-list div {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}
</style>
