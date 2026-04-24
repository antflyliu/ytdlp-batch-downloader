<template>
  <div class="page-header">
    <div>
      <div class="page-title">{{ t('nav.downloads') }}</div>
    </div>
    <div class="page-actions">
      <NButton
        type="primary"
        :disabled="startBtnDisabled"
        :loading="isSubmitting"
        @click="handleStart"
      >
        <template #icon>
          <NIcon><Play /></NIcon>
        </template>
        {{ isRunning ? t('batchDownload.downloading') + '...' : t('batchDownload.start') }}
      </NButton>
    </div>
  </div>

  <!-- 上传区卡片 -->
  <div class="card">
    <div class="card-header">
      <div class="card-title">
        <div class="card-title-icon" style="background:var(--accent-dim);color:var(--accent)">
          <NIcon><FolderOpen /></NIcon>
        </div>
        <span>{{ t('batchDownload.uploadSection') }}</span>
      </div>
    </div>
    <div class="card-body">
      <!-- 格式选择器 -->
      <div class="bd-pills">
        <button
          v-for="fmt in formatOptions"
          :key="fmt.value"
          class="bd-pill"
          :class="{ active: selectedFormat === fmt.value }"
          @click="switchFormat(fmt.value)"
        >
          {{ t(fmt.labelKey) }}
        </button>
      </div>

      <!-- 拖放上传区 -->
      <div
        class="bd-dropzone"
        :class="{ selected: !!uploadId, error: !!fileError }"
        @click="triggerFileInput"
        @dragover.prevent="onDragOver"
        @dragleave="onDragLeave"
        @drop.prevent="onDrop"
      >
        <div v-if="!uploadId">
          <div class="bd-drop-icon">
            <NIcon :size="28"><CloudUpload /></NIcon>
          </div>
          <div class="bd-drop-text">{{ t('batchDownload.dropzoneClick') }}</div>
          <div class="bd-drop-sub">{{ t('batchDownload.dropzoneHint') }}</div>
        </div>
        <div v-else>
          <div class="bd-drop-icon" style="color:var(--success)">
            <NIcon :size="28"><Checkmark /></NIcon>
          </div>
          <div class="bd-drop-text">{{ fileName }}</div>
          <div class="bd-drop-sub">{{ urlCount + ' ' + t('batch.urlCount').replace('{n}', '') }}{{ previewCount > 0 ? ' ' + t('batch.previewCount').replace('{n}', String(previewCount)) : '' }}</div>
        </div>
      </div>
      <input
        ref="fileInputRef"
        type="file"
        style="display:none"
        accept=".xlsx,.xls,.csv,.txt"
        @change="handleFileChange"
      />
      <div v-if="fileError" class="bd-file-error">
        {{ fileError }}
      </div>
    </div>
  </div>

  <!-- 下载配置卡片 -->
  <div class="card" :style="{ opacity: isRunning ? 0.5 : 1, pointerEvents: isRunning ? 'none' : 'auto' }">
    <div class="card-header">
      <div class="card-title">
        <div class="card-title-icon" style="background:var(--accent-dim);color:var(--accent)">
          <NIcon><Settings /></NIcon>
        </div>
        <span>{{ t('batchDownload.configSection') }}</span>
      </div>
    </div>
    <div class="card-body">
      <div class="bd-config-grid">
        <!-- 保存路径 -->
        <div class="bd-form-row">
          <label class="bd-label">{{ t('batchDownload.outputPath') }}</label>
          <div class="bd-input-row">
            <NInput
              v-model:value="config.outputPath"
              :placeholder="t('batchDownload.outputPathPlaceholder')"
              clearable
            />
            <NButton size="small" quaternary @click="browseOutputPath">
              {{ t('settings.browse') }}
            </NButton>
          </div>
        </div>

        <!-- 视频画质 -->
        <div class="bd-form-row">
          <label class="bd-label">{{ t('batchDownload.resolution') }}</label>
          <NSelect
            v-model:value="config.resolution"
            :options="resolutionOptions"
            style="min-width:160px"
          />
        </div>

        <!-- 字幕 -->
        <div class="bd-form-row">
          <label class="bd-label">{{ t('batchDownload.subLang') }}</label>
          <NInput
            v-model:value="config.subLang"
            style="width:120px"
            placeholder="zh-Hans,en"
          />
          <label class="bd-checkbox-label">
            <NSwitch v-model:value="config.subEnabled" />
            <span>{{ t('batchDownload.subEnabled') }}</span>
          </label>
        </div>

        <!-- 代理池 -->
        <div class="bd-form-row">
          <label class="bd-label">{{ t('batchDownload.proxyPool') }}</label>
          <NSelect
            v-model:value="config.proxyPoolId"
            :options="proxyPoolOptions"
            clearable
            style="min-width:200px"
          />
        </div>

        <!-- Cookie -->
        <div class="bd-form-row">
          <label class="bd-label">{{ t('batchDownload.cookie') }}</label>
          <div class="bd-input-row">
            <NInput
              v-model:value="config.cookieFile"
              :placeholder="t('batchDownload.cookiePlaceholder')"
              clearable
            />
            <NButton size="small" quaternary @click="browseCookie">
              {{ t('batchDownload.fillCookie') }}
            </NButton>
          </div>
        </div>
        <div class="bd-field-hint">{{ t('batchDownload.cookieHint') }}</div>
      </div>
    </div>
  </div>

  <!-- 最近任务卡片 -->
  <div class="card">
    <div class="card-header">
      <div class="card-title">
        <div class="card-title-icon" style="background:var(--accent-dim);color:var(--accent)">
          <NIcon><Folder /></NIcon>
        </div>
        <span>{{ t('batchDownload.recentSection') }}</span>
      </div>
      <div class="actions">
        <NButton size="small" quaternary @click="() => loadTasks()">
          <template #icon><NIcon><Refresh /></NIcon></template>
          {{ t('batchDownload.recentRefresh') }}
        </NButton>
      </div>
    </div>
    <div class="card-body">
      <!-- 任务选择下拉 -->
      <div class="bd-input-row" style="margin-bottom:10px">
        <NSelect
          v-model:value="selectedTaskId"
          :options="taskSelectOptions"
          :placeholder="t('batchDownload.recentNone')"
          clearable
          style="flex:1"
          @update:value="onTaskSelect"
        />
        <NButton size="small" quaternary @click="viewSelectedTask">
          {{ t('batchDownload.view') }}
        </NButton>
      </div>

      <!-- 过滤标签 -->
      <div class="bd-filter-row">
        <button
          v-for="f in filterOptions"
          :key="f.value"
          class="bd-filter-chip"
          :class="{ active: recentFilter === f.value }"
          @click="setFilter(f.value)"
        >
          {{ t(f.labelKey) }}
        </button>
      </div>

      <div class="bd-field-hint">{{ t('batchDownload.recentHint') }}</div>
      <div class="bd-recent-summary">{{ recentSummaryText }}</div>

      <!-- 最近任务列表 -->
      <div class="bd-recent-grid">
        <template v-if="filteredTasks.length">
          <div
            v-for="task in filteredTasks"
            :key="task.task_id"
            class="bd-recent-card"
            :class="{ active: selectedTaskId === task.task_id }"
            @click="attachTask(task.task_id)"
          >
            <div class="bd-recent-top">
              <span class="bd-recent-status" :class="task.status">{{ taskStatusText(task.status) }}</span>
              <span class="bd-recent-time">{{ formatTime(task.created_at) }}</span>
            </div>
            <div class="bd-recent-meta">
              {{ t('batch.totalCount', { n: task.total || 0 }) }}
              &nbsp;·&nbsp;
              {{ t('batch.success') }} {{ task.success || 0 }}
              &nbsp;·&nbsp;
              {{ t('batch.failure') }} {{ task.failed || 0 }}
              &nbsp;·&nbsp;
              {{ t('batch.pending') }} {{ Math.max(0, (task.total || 0) - (task.completed || 0)) }}
            </div>
            <div class="bd-recent-sub">
              {{ task.source_name || t('batch.sourceName') }}
              &nbsp;·&nbsp;
              {{ task.current_video || task.cancel_message || t('batch.view') }}
            </div>
            <div class="bd-recent-actions">
              <NButton size="tiny" quaternary @click.stop="restartTask(task.task_id)">
                {{ t('batch.btnReopen') }}
              </NButton>
              <NButton
                v-if="task.status === 'running' || task.status === 'cancelling'"
                size="tiny"
                quaternary
                :disabled="task.status === 'cancelling'"
                @click.stop="cancelTask(task.task_id)"
              >
                {{ task.status === 'cancelling' ? t('batch.cancelling') + '...' : t('batchDownload.cancel') }}
              </NButton>
            </div>
          </div>
        </template>
        <div v-else class="bd-recent-empty">
          {{ t('batchDownload.recentNone') }}
        </div>
      </div>
    </div>
  </div>

  <!-- 进度卡片（下载时显示） -->
  <div v-if="showProgress" class="card">
    <div class="card-header">
      <div class="card-title">
        <div class="card-title-icon" style="background:var(--accent-dim);color:var(--accent)">
          <NIcon><CloudDownload /></NIcon>
        </div>
        <span>{{ t('batchDownload.progressSection') }}</span>
      </div>
      <div class="actions">
        <NButton size="small" quaternary :disabled="isCancelling" @click="handleCancel">
          {{ isCancelling ? t('batch.cancelling') + '...' : t('batchDownload.cancel') }}
        </NButton>
      </div>
    </div>
    <div class="card-body">
      <!-- 进度条 -->
      <div class="bd-track-wrap">
        <div class="bd-track">
          <div class="bd-track-fill" :style="{ width: progressPct + '%' }"></div>
          <div class="bd-track-pulse" :class="{ active: isRunning }"></div>
        </div>
        <span class="bd-pct">{{ progressPct }}%</span>
      </div>
      <div class="bd-current">{{ currentVideo }}</div>
      <div class="bd-counter">
        {{ t('batch.success') }} {{ successCount }} / {{ totalCount }}
        &nbsp;·&nbsp;
        {{ t('batch.failure') }} {{ failedCount }}
        &nbsp;·&nbsp;
        {{ t('batch.pending') }} {{ pendingCount }}
      </div>

      <!-- 日志展开 -->
      <div class="bd-log-toggle" @click="logExpanded = !logExpanded">
        {{ logExpanded ? '▴ ' + t('batch.collapseLog') : '▾ ' + t('batchDownload.expandLog') }}
      </div>
      <div v-if="logExpanded" class="bd-log">
        <div id="bdLogText">
          <div
            v-for="(item, idx) in logEntries"
            :key="idx"
            :class="item.cls"
          >[{{ item.time }}] {{ item.status }} {{ item.info }}</div>
        </div>
      </div>
    </div>
  </div>

  <!-- 完成状态 -->
  <div v-if="showComplete" class="bd-complete" :class="completeClass">
    {{ completeText }}
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  NButton, NInput, NSelect, NSwitch, NIcon,
  useMessage, useDialog,
} from 'naive-ui'
import {
  Play, CloudUpload, Checkmark, Settings,
  Folder, FolderOpen, Refresh, CloudDownload,
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import axios from 'axios'
import request from '@/api/request'
import { useEventStore } from '@/stores/eventStore'

const { t } = useI18n()
const $message = useMessage()
const $dialog = useDialog()

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000'

// ── State ──────────────────────────────────────────────────────────
const fileInputRef = ref<HTMLInputElement | null>(null)

const selectedFormat = ref('excel')
const uploadId = ref<string | null>(null)
const fileName = ref('')
const urlCount = ref(0)
const previewCount = ref(0)
const fileError = ref('')

const config = ref({
  outputPath: '',
  resolution: 'best',
  subEnabled: true,
  subLang: 'zh-Hans,en',
  proxyPoolId: null as string | null,
  cookieFile: '',
})

const selectedTaskId = ref<string | null>(null)
const recentFilter = ref('all')
const recentTasks = ref<any[]>([])

const isSubmitting = ref(false)
const isRunning = ref(false)
const isCancelling = ref(false)

const progressPct = ref(0)
const currentVideo = ref('')
const successCount = ref(0)
const failedCount = ref(0)
const totalCount = ref(0)
const completedCount = ref(0)
const pendingCount = computed(() => Math.max(0, totalCount.value - completedCount.value))

const logExpanded = ref(false)
const logEntries = ref<{ time: string; status: string; info: string; cls: string }[]>([])

const currentTaskId = ref<string | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

// ── Format options ─────────────────────────────────────────────────
const formatOptions = [
  { value: 'excel', labelKey: 'batchDownload.formatExcel' },
  { value: 'csv', labelKey: 'batchDownload.formatCsv' },
  { value: 'txt', labelKey: 'batchDownload.formatTxt' },
]

// ── Resolution options ─────────────────────────────────────────────
const resolutionOptions = [
  { label: t('batchDownload.resolutionBest'), value: 'best' },
  { label: t('batchDownload.resolution720p'), value: '720p' },
  { label: t('batchDownload.resolution1080p'), value: '1080p' },
  { label: t('batchDownload.resolution1440p'), value: '1440p' },
]

// ── Proxy pool options ────────────────────────────────────────────
const proxyPoolOptions = ref<{ label: string; value: string }[]>([
  { label: t('batchDownload.proxyPoolDefault'), value: '' },
])

// ── Filter options ────────────────────────────────────────────────
const filterOptions = [
  { value: 'all', labelKey: 'batchDownload.recentFilterAll' },
  { value: 'active', labelKey: 'batchDownload.recentFilterActive' },
  { value: 'finished', labelKey: 'batchDownload.recentFilterFinished' },
  { value: 'cancelled', labelKey: 'batchDownload.recentFilterCancelled' },
]

// ── Computed ──────────────────────────────────────────────────────
const startBtnDisabled = computed(() =>
  isSubmitting.value || isRunning.value || isCancelling.value
)

const showProgress = computed(() =>
  isRunning.value || isCancelling.value || !!currentTaskId.value
)

const showComplete = computed(() => {
  if (!currentTaskId.value) return false
  const task = recentTasks.value.find(t => t.task_id === currentTaskId.value)
  if (!task) return false
  return ['done', 'error', 'cancelled'].includes(task.status)
})

const completeClass = computed(() => {
  const task = recentTasks.value.find(t => t.task_id === currentTaskId.value)
  if (!task) return ''
  if (task.status === 'cancelled') return 'warning'
  if (task.status === 'done' && task.failed === 0 && task.success > 0) return 'success'
  if (task.status === 'error' && task.success > 0 && task.failed > 0) return 'warning'
  return 'error'
})

const completeText = computed(() => {
  const task = recentTasks.value.find(t => t.task_id === currentTaskId.value)
  if (!task) return ''
  const s = task.success || 0
  const f = task.failed || 0
  const c = task.completed || 0
  const n = task.total || 0
  if (task.status === 'cancelled') {
    return t('batch.taskSnapshotCancelled').replace('{s}', s).replace('{f}', f).replace('{c}', c).replace('{t}', n)
  }
  if (task.status === 'done' && f === 0 && s > 0) {
    return t('batch.taskSnapshotSuccess').replace('{s}', s).replace('{f}', f)
  }
  if (s > 0 && f > 0) {
    return t('batch.taskSnapshotPartial').replace('{s}', s).replace('{f}', f)
  }
  return t('batch.taskSnapshotFailed').replace('{s}', s).replace('{f}', f)
})

const filteredTasks = computed(() => {
  if (recentFilter.value === 'active') {
    return recentTasks.value.filter(t => t.status === 'running' || t.status === 'cancelling')
  }
  if (recentFilter.value === 'finished') {
    return recentTasks.value.filter(t => t.status === 'done' || t.status === 'error')
  }
  if (recentFilter.value === 'cancelled') {
    return recentTasks.value.filter(t => t.status === 'cancelled')
  }
  return recentTasks.value
})

const recentSummaryText = computed(() => {
  const all = recentTasks.value.length
  const active = recentTasks.value.filter(t => t.status === 'running' || t.status === 'cancelling').length
  const finished = recentTasks.value.filter(t => t.status === 'done' || t.status === 'error').length
  const cancelled = recentTasks.value.filter(t => t.status === 'cancelled').length
  return t('batch.recentSummary')
    .replace('{total}', String(all))
    .replace('{active}', String(active))
    .replace('{finished}', String(finished))
    .replace('{cancelled}', String(cancelled))
})

const taskSelectOptions = computed(() => {
  if (!recentTasks.value.length) return []
  return recentTasks.value.map(task => ({
    label: taskLabel(task),
    value: task.task_id,
  }))
})

// ── Helpers ────────────────────────────────────────────────────────
function taskLabel(task: any): string {
  const statusMap: Record<string, string> = {
    running: t('batchDownload.downloading'),
    cancelling: t('batch.cancelling'),
    cancelled: t('batch.cancelled'),
    done: t('batch.completed'),
    error: t('batch.failed'),
  }
  const status = statusMap[task.status] || task.status || t('batch.unknown')
  const total = Number(task.total || 0)
  const success = Number(task.success || 0)
  const failed = Number(task.failed || 0)
  const createdAt = (task.created_at || '').replace('T', ' ').slice(5, 16)
  const source = task.source_name ? ' · ' + task.source_name : ''
  return `[${status}] ${total} ${t('batch.total')} · ${t('batch.success')} ${success} / ${t('batch.failure')} ${failed}${createdAt ? ' · ' + createdAt : ''}${source}`
}

function taskStatusText(status: string): string {
  const map: Record<string, string> = {
    running: t('batchDownload.downloading'),
    cancelling: t('batch.cancelling'),
    cancelled: t('batch.cancelled'),
    done: t('batch.completed'),
    error: t('batch.failed'),
  }
  return map[status] || status
}

function formatTime(ts: string): string {
  if (!ts) return t('batch.timeUnknown')
  return ts.replace('T', ' ').slice(5, 16)
}

// ── Format switcher ────────────────────────────────────────────────
function switchFormat(fmt: string) {
  selectedFormat.value = fmt
  resetUploadState()
}

// ── File upload ────────────────────────────────────────────────────
function triggerFileInput() {
  fileInputRef.value?.click()
}

function onDragOver() {}
function onDragLeave() {}

function onDrop(e: DragEvent) {
  const file = e.dataTransfer?.files?.[0]
  if (file) processFile(file)
}

function handleFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) processFile(file)
}

async function processFile(file: File) {
  fileError.value = ''
  const formData = new FormData()
  formData.append('file', file)
  try {
    const resp = await request.post('/api/batch/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const data = resp.data || resp
    if (data && (data.ok || data.upload_id)) {
      uploadId.value = data.upload_id || null
      fileName.value = data.filename || file.name
      urlCount.value = data.url_count || 0
      previewCount.value = Array.isArray(data.preview_urls) ? data.preview_urls.length : 0
    } else {
      resetUploadState()
      fileError.value = t('batch.parseFailed')
    }
  } catch {
    resetUploadState()
    fileError.value = t('batch.networkError')
  }
}

function resetUploadState() {
  uploadId.value = null
  fileName.value = ''
  urlCount.value = 0
  previewCount.value = 0
  fileError.value = ''
  if (fileInputRef.value) fileInputRef.value.value = ''
}

// ── Browse dialogs ────────────────────────────────────────────────
function browseOutputPath() {
  request.post('/api/open-directory').then(() => {
    $message.info(t('batch.browsePathHint'))
  }).catch(() => {
    $message.info(t('batch.browsePathHint'))
  })
}

function browseCookie() {
  request.post('/api/open-file').then(() => {
    $message.info(t('batch.browseCookieHint'))
  }).catch(() => {
    $message.info(t('batch.browseCookieHint'))
  })
}

// ── Tasks ─────────────────────────────────────────────────────────
async function loadTasks(taskId?: string) {
  try {
    const resp = await request.get('/api/batch/tasks')
    const data = resp.data || resp
    const tasks: any[] = Array.isArray(data?.tasks) ? data.tasks : Array.isArray(data) ? data : []
    recentTasks.value = tasks
    updateSummary(tasks)
    if (taskId) {
      selectedTaskId.value = taskId
    }
    const runningCount = tasks.filter(t => t.status === 'running' || t.status === 'cancelling').length
    if (runningCount === 0 && currentTaskId.value) {
      // keep current task shown
    }
  } catch {
    $message.error(t('batch.batchQueryFailed'))
  }
}

function updateSummary(_tasks: any[]) {
  // summary is computed, auto-updates
}

function setFilter(filter: string) {
  recentFilter.value = filter
}

function onTaskSelect(val: string | null) {
  if (val) selectedTaskId.value = val
}

function viewSelectedTask() {
  if (!selectedTaskId.value) {
    $message.warning(t('batch.noTasksToView'))
    return
  }
  attachTask(selectedTaskId.value)
}

async function attachTask(taskId: string) {
  selectedTaskId.value = taskId
  try {
    const resp = await request.get(`/api/batch/tasks/${taskId}`)
    const task = resp.data || resp
    if (!task || task.error) {
      $message.error((task && task.error) || t('batch.loadTaskFailed'))
      return
    }
    applyTaskSnapshot(task)
  } catch {
    $message.error(t('batch.loadTaskFailed'))
  }
}

function applyTaskSnapshot(task: any) {
  currentTaskId.value = task.task_id || selectedTaskId.value
  const pct = task.total > 0 ? Math.round((task.completed / task.total) * 100) : 0
  progressPct.value = pct
  currentVideo.value = task.current_video || ''
  successCount.value = Number(task.success || 0)
  failedCount.value = Number(task.failed || 0)
  totalCount.value = Number(task.total || 0)
  completedCount.value = Number(task.completed || 0)

  // Update log entries
  const results = Array.isArray(task.results) ? task.results : []
  const lastCount = logEntries.value.length
  if (results.length > lastCount) {
    results.slice(lastCount).forEach((item: any) => {
      const cls = item.status === t('batch.success') ? 'log-success'
        : item.status === t('batch.failure') ? 'log-error' : ''
      const time = new Date().toLocaleTimeString()
      logEntries.value.push({ time, status: item.status || '', info: item.info || '', cls })
    })
  }

  // Sync task status to recentTasks list
  const idx = recentTasks.value.findIndex(t => t.task_id === task.task_id)
  if (idx >= 0) {
    recentTasks.value[idx] = { ...recentTasks.value[idx], ...task }
  }

  if (task.status === 'running' || task.status === 'cancelling') {
    isRunning.value = task.status === 'running'
    isCancelling.value = task.status === 'cancelling'
    if (!pollTimer) {
      pollTimer = setInterval(pollTask, 2000)
    }
    return
  }

  // Task finished
  isRunning.value = false
  isCancelling.value = false
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollTask() {
  if (!currentTaskId.value) return
  try {
    const resp = await request.get(`/api/batch/tasks/${currentTaskId.value}`)
    const task = resp.data || resp
    if (!task || task.error) return
    applyTaskSnapshot(task)
    if (['done', 'error', 'cancelled'].includes(task.status)) {
      loadTasks(currentTaskId.value)
    }
  } catch {
    // ignore
  }
}

async function restartTask(taskId: string) {
  if (isRunning.value || isCancelling.value) return
  isSubmitting.value = true
  try {
    const resp = await request.post(`/api/batch/tasks/${taskId}/restart`, {})
    const task = resp.data || resp
    if (task && task.task_id) {
      applyRunningAfterStart(task.task_id)
    } else {
      $message.error((task && task.error) || t('batch.restartFailed'))
    }
  } catch {
    $message.error(t('batch.networkError'))
  } finally {
    isSubmitting.value = false
  }
}

async function cancelTask(taskId: string) {
  try {
    const resp = await request.post(`/api/batch/tasks/${taskId}/cancel`, {})
    const r = resp.data || resp
    if (r && r.error) {
      $message.error(r.error || t('batch.cancelFailed'))
      return
    }
    if (currentTaskId.value === taskId) {
      isCancelling.value = true
      currentVideo.value = (r && r.message) || t('batch.cancellingTask')
    }
    loadTasks(taskId)
    if (currentTaskId.value === taskId) {
      attachTask(taskId)
    }
  } catch {
    if (currentTaskId.value === taskId) {
      isCancelling.value = false
    }
    $message.error(t('batch.cancelFailed'))
  }
}

function applyRunningAfterStart(taskId: string) {
  currentTaskId.value = taskId
  isRunning.value = true
  isCancelling.value = false
  isSubmitting.value = false
  logEntries.value = []
  progressPct.value = 0
  currentVideo.value = ''
  successCount.value = 0
  failedCount.value = 0
  totalCount.value = 0
  completedCount.value = 0
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  pollTimer = setInterval(pollTask, 2000)
  loadTasks(taskId)
}

// ── Start download ────────────────────────────────────────────────
async function handleStart() {
  if (isRunning.value || isCancelling.value) return
  if (!uploadId.value) {
    // No new upload, try restart with selected task
    const restartId = selectedTaskId.value || currentTaskId.value
    if (!restartId) {
      $message.error(t('batch.taskEmpty'))
      return
    }
    await restartTask(restartId)
    return
  }

  isSubmitting.value = true
  logEntries.value = []
  try {
    const body: Record<string, any> = {
      upload_id: uploadId.value,
      output_path: config.value.outputPath || '',
      resolution: config.value.resolution,
      sub_langs: config.value.subEnabled ? config.value.subLang : '',
      no_subs: !config.value.subEnabled,
      proxy_pool_id: config.value.proxyPoolId || null,
      cookies_file: config.value.cookieFile || null,
    }
    const resp = await request.post('/api/batch/start', body)
    const r = resp.data || resp
    if (r && r.task_id) {
      applyRunningAfterStart(r.task_id)
    } else {
      $message.error((r && r.error) || t('batch.downloadFailed'))
    }
  } catch {
    $message.error(t('batch.networkError'))
  } finally {
    isSubmitting.value = false
  }
}

// ── Cancel ─────────────────────────────────────────────────────────
function handleCancel() {
  if (isRunning.value) {
    isCancelling.value = true
    currentVideo.value = t('batch.requestingCancel')
    cancelTask(currentTaskId.value!)
    return
  }
  if (isCancelling.value) return
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  currentTaskId.value = null
  isRunning.value = false
  isCancelling.value = false
}

// ── SSE events ────────────────────────────────────────────────────
const eventStore = useEventStore()

function onBatchProgress(data: any) {
  if (!currentTaskId.value || data.task_id !== currentTaskId.value) return
  progressPct.value = data.pct || 0
  currentVideo.value = data.current_video || ''
  successCount.value = Number(data.success || 0)
  failedCount.value = Number(data.failed || 0)
  totalCount.value = Number(data.total || 0)
  completedCount.value = Number(data.completed || 0)

  if (data.log) {
    const cls = data.status === t('batch.success') ? 'log-success'
      : data.status === t('batch.failure') ? 'log-error' : ''
    const time = new Date().toLocaleTimeString()
    logEntries.value.push({ time, status: data.status || '', info: data.log || '', cls })
  }
}

function onBatchComplete(data: any) {
  if (!currentTaskId.value || data.task_id !== currentTaskId.value) return
  applyTaskSnapshot(data)
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  loadTasks(currentTaskId.value)
}

// ── Lifecycle ─────────────────────────────────────────────────────
onMounted(async () => {
  // Load proxy pools
  try {
    const resp = await request.get('/api/proxy-pools')
    const pools = resp.data || resp
    if (Array.isArray(pools)) {
      proxyPoolOptions.value = [
        { label: t('batchDownload.proxyPoolDefault'), value: '' },
        ...pools.filter((p: any) => p && p.enabled).map((p: any) => ({
          label: (p.name || '') + (p.proxy_url ? ' (' + p.proxy_url + ')' : ''),
          value: String(p.id),
        })),
      ]
    }
  } catch {
    // use defaults
  }

  // Load recent tasks
  await loadTasks()

  // Register SSE handlers
  eventStore.addHandle('batchProgress', onBatchProgress)
  eventStore.addHandle('batchComplete', onBatchComplete)
})

onUnmounted(() => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  eventStore.removeHandle('batchProgress')
  eventStore.removeHandle('batchComplete')
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 0 0 16px;
  gap: 16px;
  flex-shrink: 0;
}
.page-title {
  font-family: var(--font);
  font-size: 20px;
  font-weight: 500;
  color: var(--text);
}
.page-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* Pills */
.bd-pills { display: flex; gap: 6px; margin-bottom: 12px; }
.bd-pill {
  padding: 4px 12px; border-radius: var(--r-full); font-size: 12px;
  border: 1px solid var(--border); background: var(--surface2); color: var(--text-muted);
  cursor: pointer; transition: all 150ms;
}
.bd-pill:hover { border-color: var(--accent); color: var(--accent); }
.bd-pill.active { background: var(--accent); border-color: var(--accent); color: #fff; }

/* Dropzone */
.bd-dropzone {
  border: 2px dashed var(--border); border-radius: var(--r-md);
  padding: 28px 20px; text-align: center; cursor: pointer;
  transition: border-color 200ms, background 200ms;
  margin-bottom: 8px;
}
.bd-dropzone:hover { border-color: var(--accent); background: var(--accent-dim); }
.bd-dropzone.selected { border-color: var(--success); border-style: solid; }
.bd-dropzone.error { border-color: var(--error); }
.bd-drop-icon { font-size: 28px; color: var(--text-dim); margin-bottom: 8px; display: flex; justify-content: center; }
.bd-drop-text { font-size: 13px; color: var(--text-muted); font-weight: 500; }
.bd-drop-sub { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
.bd-file-error { font-size: 11px; color: var(--error); padding: 4px 0; }

/* Config form */
.bd-config-grid { display: flex; flex-direction: column; gap: 12px; }
.bd-form-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.bd-label { font-size: 12px; color: var(--text-muted); min-width: 60px; }
.bd-input-row { display: flex; gap: 8px; flex: 1; min-width: 200px; align-items: center; }
.bd-checkbox-label { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted); cursor: pointer; }
.bd-field-hint { font-size: 11px; color: var(--text-dim); margin-top: 4px; }

/* Filter row */
.bd-filter-row { display: flex; gap: 6px; margin: 10px 0 6px; flex-wrap: wrap; }
.bd-filter-chip {
  padding: 3px 10px; border-radius: var(--r-full); font-size: 11px;
  border: 1px solid var(--border); background: var(--surface2); color: var(--text-muted);
  cursor: pointer; transition: all 150ms;
}
.bd-filter-chip:hover { border-color: var(--accent); color: var(--accent); }
.bd-filter-chip.active { background: var(--accent); border-color: var(--accent); color: #fff; }

/* Recent tasks */
.bd-recent-grid { display: grid; gap: 8px; margin-top: 10px; }
.bd-recent-empty {
  padding: 10px 12px; border: 1px dashed var(--border); border-radius: var(--r-sm);
  color: var(--text-dim); font-size: 12px; text-align: center;
}
.bd-recent-card {
  border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--surface2);
  padding: 10px 12px; cursor: pointer; transition: border-color 0.15s, background 0.15s, transform 0.15s;
}
.bd-recent-card:hover { border-color: var(--accent); background: var(--surface3); transform: translateY(-1px); }
.bd-recent-card.active { border-color: var(--accent); box-shadow: 0 0 0 1px rgba(99,102,241,0.2) inset; }
.bd-recent-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px; }
.bd-recent-status {
  padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600;
  background: var(--surface3); color: var(--text-muted); border: 1px solid var(--border);
}
.bd-recent-status.running { color: var(--accent); border-color: rgba(99,102,241,0.25); background: var(--accent-dim); }
.bd-recent-status.cancelling,
.bd-recent-status.cancelled { color: var(--warning); border-color: rgba(245,158,11,0.22); background: rgba(245,158,11,0.10); }
.bd-recent-status.done { color: var(--success); border-color: rgba(34,197,94,0.22); background: rgba(34,197,94,0.10); }
.bd-recent-status.error { color: var(--error); border-color: rgba(239,68,68,0.22); background: rgba(239,68,68,0.10); }
.bd-recent-time { font-size: 11px; color: var(--text-dim); font-family: var(--mono); }
.bd-recent-meta { font-size: 12px; color: var(--text-muted); line-height: 1.6; }
.bd-recent-sub { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
.bd-recent-actions { display: flex; gap: 6px; margin-top: 8px; }
.bd-recent-summary { font-size: 11px; color: var(--text-dim); margin-top: 8px; }

/* Progress */
.bd-track-wrap { display: flex; align-items: center; gap: 10px; margin: 8px 0 6px; }
.bd-track { flex: 1; height: 6px; background: var(--surface3); border-radius: 3px; overflow: hidden; position: relative; }
.bd-track-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s ease; width: 0%; }
.bd-track-pulse { position: absolute; right: 0; top: 50%; transform: translateY(-50%); width: 8px; height: 8px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 8px var(--accent); animation: bd-pulse 1.5s ease-in-out infinite; opacity: 0; }
.bd-track-pulse.active { opacity: 1; }
@keyframes bd-pulse { 0%, 100% { transform: translateY(-50%) scale(1); opacity: 1; } 50% { transform: translateY(-50%) scale(1.5); opacity: 0.6; } }
.bd-pct { font-size: 11px; color: var(--text-muted); font-family: var(--mono); flex-shrink: 0; width: 32px; text-align: right; }
.bd-current { font-size: 12px; color: var(--text-muted); margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bd-counter { font-size: 12px; color: var(--text-dim); margin-bottom: 8px; }

/* Log */
.bd-log-toggle { font-size: 11px; color: var(--text-dim); cursor: pointer; user-select: none; margin-bottom: 4px; }
.bd-log-toggle:hover { color: var(--text-muted); }
.bd-log { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--r-sm); padding: 8px 10px; max-height: 120px; overflow-y: auto; }
.bd-log:empty::before { content: '暂无日志'; color: var(--text-dim); font-size: 11px; }
#bdLogText { font-family: var(--mono); font-size: 11px; color: var(--text-muted); line-height: 1.7; }
#bdLogText :deep(.log-success) { color: var(--success); }
#bdLogText :deep(.log-error) { color: var(--error); }

/* Complete */
.bd-complete {
  margin-top: 8px; padding: 10px; border-radius: var(--r-sm); font-size: 12px; text-align: center;
}
.bd-complete.success { background: var(--success-dim); border: 1px solid rgba(34,197,94,0.3); color: var(--success); }
.bd-complete.warning { background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.28); color: var(--warning); }
.bd-complete.error { background: var(--error-dim); border: 1px solid rgba(239,68,68,0.3); color: var(--error); }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
</style>
