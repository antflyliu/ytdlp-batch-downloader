<template>
  <div class="wechat-collect-page">
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('wechatCollect.title') }}</div>
        <div class="page-desc">{{ t('wechatCollect.desc') }}</div>
      </div>
      <div class="page-actions">
        <NButton tertiary :loading="loadingConfig" @click="loadAll">
          {{ t('wechatCollect.refresh') }}
        </NButton>
      </div>
    </div>

    <NAlert type="info" :bordered="false">
      {{ t('wechatCollect.exporterNotice') }}
    </NAlert>

    <div class="wechat-collect-grid">
      <div ref="sourcePanelRef" class="collect-source-panel">
        <NCard class="collect-card" :title="t('wechatCollect.sourceTitle')">
          <div class="form-stack">
            <NAlert v-if="config && !config.configured" type="warning" :bordered="false">
              {{ t('wechatCollect.authMissing') }}
            </NAlert>

            <NRadioGroup v-model:value="sourceMode" name="wechat-source-mode" size="large">
              <NRadioButton value="url">{{ t('wechatCollect.modeUrl') }}</NRadioButton>
              <NRadioButton value="fakeid">{{ t('wechatCollect.modeFakeid') }}</NRadioButton>
              <NRadioButton value="urls">{{ t('wechatCollect.modeUrls') }}</NRadioButton>
            </NRadioGroup>

            <NForm :model="form" label-placement="top">
              <div class="form-grid">
                <NFormItem v-if="sourceMode === 'url'" class="wide" :label="t('wechatCollect.articleUrl')">
                  <NInput v-model:value="form.article_url" clearable />
                </NFormItem>

                <template v-if="sourceMode === 'fakeid'">
                  <NFormItem :label="t('wechatCollect.fakeid')">
                    <NInput v-model:value="form.fakeid" clearable />
                  </NFormItem>
                  <NFormItem :label="t('wechatCollect.accountName')">
                    <NInput v-model:value="form.account_name" clearable />
                  </NFormItem>
                </template>

                <NFormItem v-if="sourceMode === 'urls'" class="wide" :label="t('wechatCollect.urls')">
                  <NInput
                    v-model:value="form.urlsText"
                    type="textarea"
                    :autosize="{ minRows: 5, maxRows: 10 }"
                  />
                </NFormItem>

                <NFormItem :label="t('wechatCollect.keyword')">
                  <NInput v-model:value="form.keyword" clearable />
                </NFormItem>

                <NFormItem :label="t('wechatCollect.format')">
                  <NSelect v-model:value="form.format" :options="formatOptions" />
                </NFormItem>

                <NFormItem :label="t('wechatCollect.maxArticles')">
                  <NInputNumber v-model:value="form.max_articles" :min="1" :max="1000" :show-button="false" style="width: 100%" />
                </NFormItem>

                <NFormItem :label="t('wechatCollect.delaySeconds')">
                  <NInputNumber v-model:value="form.delay_seconds" :min="0" :max="30" :step="0.5" :show-button="false" style="width: 100%" />
                </NFormItem>

                <NFormItem class="wide" :label="t('wechatCollect.outputDir')">
                  <NInput v-model:value="form.output_dir" clearable />
                </NFormItem>
              </div>
            </NForm>

            <div class="action-row">
              <NButton :loading="checkingAuth" @click="checkAuth">
                {{ t('wechatCollect.checkAuth') }}
              </NButton>
              <NButton :loading="previewing" :disabled="!canPreview" @click="preview">
                {{ t('wechatCollect.preview') }}
              </NButton>
              <NButton type="primary" :loading="starting" :disabled="!canStart" @click="startCollect">
                {{ t('wechatCollect.start') }}
              </NButton>
            </div>
          </div>
        </NCard>
      </div>

      <NCard
        class="collect-card preview-card"
        :style="previewMaxHeight ? { '--preview-max-height': previewMaxHeight } : undefined"
        :title="t('wechatCollect.previewTitle')"
      >
        <div class="preview-scroll-panel">
          <div v-if="previewError" class="error-box">{{ previewError }}</div>
          <div v-if="previewAccount.fakeid" class="account-strip">
            <div>
              <div class="account-name">{{ previewAccount.nickname || previewAccount.fakeid }}</div>
              <div class="account-meta">{{ previewAccount.fakeid }}</div>
            </div>
            <NTag v-if="previewArticles.length" :bordered="false" type="success">
              {{ t('wechatCollect.articleCount', { n: previewArticles.length }) }}
            </NTag>
          </div>

          <div v-if="previewArticles.length" class="article-list">
            <div v-for="article in previewArticles" :key="article.link" class="article-item">
              <div class="article-title">{{ article.title || t('wechatCollect.untitled') }}</div>
              <div class="article-meta">
                <span>{{ formatUnixTime(article.update_time) }}</span>
                <span>{{ article.author_name || '—' }}</span>
              </div>
            </div>
          </div>
          <div v-else-if="!previewError" class="preview-empty">
            <NEmpty :description="t('wechatCollect.previewEmpty')" />
          </div>
        </div>
      </NCard>
    </div>

    <NCard class="collect-card" :title="t('wechatCollect.tasksTitle')">
      <template #header-extra>
        <NButton tertiary size="small" :loading="loadingTasks" @click="loadTasks">
          {{ t('wechatCollect.refresh') }}
        </NButton>
      </template>

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
              <strong>{{ task.account?.nickname || task.account?.fakeid || t('wechatCollect.collectTask') }}</strong>
              <NTag size="small" :bordered="false" :type="statusType(task.status)">
                {{ statusLabel(task.status) }}
              </NTag>
            </div>
            <div class="task-progress">
              <span>{{ task.completed || 0 }} / {{ task.total || 0 }}</span>
              <span>{{ formatDateTime(task.created_at) }}</span>
            </div>
          </button>
          <NEmpty v-if="!tasks.length" :description="t('wechatCollect.tasksEmpty')" />
        </div>

        <div class="task-detail">
          <NEmpty v-if="!selectedTask" :description="t('wechatCollect.selectTask')" />
          <template v-else>
            <div class="detail-head">
              <div>
                <div class="detail-title">{{ selectedTask.account?.nickname || t('wechatCollect.collectTask') }}</div>
                <div class="detail-sub">{{ selectedTask.output_dir }}</div>
              </div>
              <NButton
                v-if="selectedTask.status === 'running'"
                tertiary
                type="warning"
                :loading="cancelling"
                @click="cancelSelected"
              >
                {{ t('wechatCollect.cancel') }}
              </NButton>
            </div>

            <div class="detail-progress-card">
              <div class="progress-text">
                <span>{{ selectedTask.current || '—' }}</span>
                <span>{{ progressPercent }}%</span>
              </div>
              <div class="progress-track">
                <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
              </div>
            </div>

            <div v-if="selectedTask.error" class="error-box">{{ selectedTask.error }}</div>

            <div class="result-scroll-panel">
              <div class="result-list">
                <div v-for="item in selectedTask.results || []" :key="item.url || item.path" class="result-item">
                  <NTag size="small" :bordered="false" :type="item.status === 'success' ? 'success' : 'error'">
                    {{ item.status === 'success' ? t('wechatCollect.success') : t('wechatCollect.failed') }}
                  </NTag>
                  <div class="result-body">
                    <div class="result-title">{{ item.title || item.url }}</div>
                    <div class="result-path">{{ item.path || item.error || item.url }}</div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
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
  NRadioButton,
  NRadioGroup,
  NSelect,
  NTag,
  useMessage,
} from 'naive-ui'
import wechatCollectApi, { type WechatCollectConfig, type WechatCollectTask } from '@/api/wechatCollect'

type SourceMode = 'url' | 'fakeid' | 'urls'

const POLL_INTERVAL_MS = 2500

const { t } = useI18n()
const message = useMessage()

const sourceMode = ref<SourceMode>('url')
const config = ref<WechatCollectConfig | null>(null)
const loadingConfig = ref(false)
const loadingTasks = ref(false)
const checkingAuth = ref(false)
const previewing = ref(false)
const starting = ref(false)
const cancelling = ref(false)
const previewError = ref('')
const previewAccount = ref<Record<string, any>>({})
const previewArticles = ref<Array<Record<string, any>>>([])
const sourcePanelRef = ref<HTMLElement | null>(null)
const previewMaxHeight = ref('')
const tasks = ref<WechatCollectTask[]>([])
const selectedTaskId = ref('')
const selectedTask = ref<WechatCollectTask | null>(null)
let pollTimer: number | null = null
let sourceResizeObserver: ResizeObserver | null = null

const form = reactive({
  article_url: '',
  fakeid: '',
  account_name: '',
  urlsText: '',
  keyword: '',
  format: 'markdown',
  output_dir: '',
  max_articles: 50,
  delay_seconds: 1,
})

const formatOptions = computed(() => [
  { label: 'Markdown', value: 'markdown' },
  { label: 'HTML', value: 'html' },
  { label: 'Text', value: 'text' },
  { label: 'JSON', value: 'json' },
])

const parsedUrls = computed(() => form.urlsText
  .split(/\r?\n/)
  .map((item) => item.trim())
  .filter(Boolean))

const canPreview = computed(() => sourceMode.value !== 'urls' && Boolean(form.article_url.trim() || form.fakeid.trim()))
const canStart = computed(() => {
  if (sourceMode.value === 'urls') return parsedUrls.value.length > 0
  if (sourceMode.value === 'fakeid') return Boolean(form.fakeid.trim())
  return Boolean(form.article_url.trim())
})

const progressPercent = computed(() => {
  const total = Number(selectedTask.value?.total || 0)
  if (!total) return selectedTask.value?.status === 'done' ? 100 : 0
  return Math.min(100, Math.round((Number(selectedTask.value?.completed || 0) / total) * 100))
})

function basePayload() {
  return {
    article_url: sourceMode.value === 'url' ? form.article_url.trim() : undefined,
    fakeid: sourceMode.value === 'fakeid' ? form.fakeid.trim() : undefined,
    account_name: sourceMode.value === 'fakeid' ? form.account_name.trim() : undefined,
    urls: sourceMode.value === 'urls' ? parsedUrls.value : undefined,
    keyword: form.keyword.trim() || undefined,
    format: form.format as any,
    output_dir: form.output_dir.trim() || undefined,
    max_articles: form.max_articles || undefined,
    delay_seconds: form.delay_seconds ?? undefined,
  }
}

async function loadConfig() {
  loadingConfig.value = true
  try {
    const res = await wechatCollectApi.getConfig()
    config.value = res.data
    form.output_dir = form.output_dir || res.data.wechat_collection_output_dir || ''
    form.format = res.data.wechat_collection_default_format || 'markdown'
    form.max_articles = Number(res.data.wechat_collection_max_articles || 50)
    form.delay_seconds = Number(res.data.wechat_collection_delay_seconds ?? 1)
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatCollect.configLoadFailed'))
  } finally {
    loadingConfig.value = false
  }
}

async function loadTasks() {
  loadingTasks.value = true
  try {
    const res = await wechatCollectApi.listTasks()
    tasks.value = Array.isArray(res.data?.tasks) ? res.data.tasks : []
    if (selectedTaskId.value) {
      const found = tasks.value.find((task) => task.task_id === selectedTaskId.value)
      if (found) selectedTask.value = { ...selectedTask.value, ...found } as WechatCollectTask
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatCollect.tasksLoadFailed'))
  } finally {
    loadingTasks.value = false
  }
}

async function loadAll() {
  await Promise.all([loadConfig(), loadTasks()])
}

async function checkAuth() {
  checkingAuth.value = true
  try {
    await wechatCollectApi.checkAuth()
    message.success(t('wechatCollect.authOk'))
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatCollect.authFailed'))
  } finally {
    checkingAuth.value = false
  }
}

async function preview() {
  previewing.value = true
  previewError.value = ''
  previewArticles.value = []
  previewAccount.value = {}
  try {
    const res = await wechatCollectApi.preview({
      ...basePayload(),
      limit: Math.min(form.max_articles || 10, 20),
    })
    previewAccount.value = res.data?.account || {}
    previewArticles.value = Array.isArray(res.data?.articles) ? res.data.articles : []
  } catch (error: any) {
    previewError.value = error?.response?.data?.error || error?.message || t('wechatCollect.previewFailed')
  } finally {
    previewing.value = false
  }
}

async function startCollect() {
  starting.value = true
  try {
    const res = await wechatCollectApi.start(basePayload())
    const taskId = String(res.data?.task_id || '')
    message.success(t('wechatCollect.started'))
    await loadTasks()
    if (taskId) {
      await selectTask(taskId)
      ensurePolling()
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatCollect.startFailed'))
  } finally {
    starting.value = false
  }
}

async function selectTask(taskId: string) {
  selectedTaskId.value = taskId
  try {
    const res = await wechatCollectApi.getTask(taskId)
    selectedTask.value = res.data
    ensurePolling()
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatCollect.taskLoadFailed'))
  }
}

async function pollSelectedTask() {
  if (!selectedTaskId.value) return
  try {
    const res = await wechatCollectApi.getTask(selectedTaskId.value)
    selectedTask.value = res.data
    if (!['running'].includes(res.data.status)) {
      stopPolling()
      await loadTasks()
    }
  } catch {
    stopPolling()
  }
}

function ensurePolling() {
  stopPolling()
  if (selectedTask.value?.status !== 'running') return
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
    await wechatCollectApi.cancelTask(selectedTaskId.value)
    await pollSelectedTask()
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatCollect.cancelFailed'))
  } finally {
    cancelling.value = false
  }
}

function statusType(status: string) {
  if (status === 'done') return 'success'
  if (status === 'error') return 'error'
  if (status === 'cancelled') return 'warning'
  return 'info'
}

function statusLabel(status: string) {
  return t(`wechatCollect.status.${status}`) || status
}

function formatUnixTime(value: number) {
  const n = Number(value || 0)
  if (!n) return '—'
  return new Date(n * 1000).toLocaleString()
}

function formatDateTime(value?: string) {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 16)
}

function updatePreviewMaxHeight() {
  const sourcePanel = sourcePanelRef.value
  if (!sourcePanel) {
    previewMaxHeight.value = ''
    return
  }
  const height = Math.ceil(sourcePanel.getBoundingClientRect().height)
  previewMaxHeight.value = height > 0 ? `${height}px` : ''
}

function initPreviewHeightSync() {
  updatePreviewMaxHeight()
  if (!sourcePanelRef.value || !window.ResizeObserver) return
  sourceResizeObserver = new ResizeObserver(() => {
    updatePreviewMaxHeight()
  })
  sourceResizeObserver.observe(sourcePanelRef.value)
}

onMounted(async () => {
  await nextTick()
  initPreviewHeightSync()
  await loadAll()
  await nextTick()
  updatePreviewMaxHeight()
})

onUnmounted(() => {
  stopPolling()
  sourceResizeObserver?.disconnect()
  sourceResizeObserver = null
})
</script>

<style scoped>
.wechat-collect-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.wechat-collect-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
  gap: 16px;
  align-items: start;
}

.collect-source-panel {
  min-width: 0;
}

.collect-card {
  border-radius: 20px;
}

.preview-card {
  display: flex;
  flex-direction: column;
  max-height: var(--preview-max-height, none);
  overflow: hidden;
}

.preview-card :deep(> .n-card__content) {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.preview-scroll-panel {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.form-stack,
.task-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
}

.wide {
  grid-column: 1 / -1;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.account-strip,
.task-row,
.task-progress,
.detail-head,
.progress-text,
.result-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.account-strip {
  padding: 12px 14px;
  border: 1px solid rgba(201, 100, 66, 0.18);
  border-radius: 14px;
  background: rgba(201, 100, 66, 0.07);
}

.account-name,
.detail-title {
  color: var(--text);
  font-size: 16px;
  font-weight: 600;
}

.account-meta,
.article-meta,
.detail-sub,
.task-progress,
.result-path {
  color: var(--text-muted);
  font-size: 12px;
}

.article-list,
.task-list,
.result-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.preview-scroll-panel > .article-list,
.preview-scroll-panel > .preview-empty {
  margin-top: 10px;
}

.article-item,
.task-item,
.result-item {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.article-item {
  padding: 14px;
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 253, 248, 0.96) 0%, rgba(250, 249, 245, 0.98) 100%);
}

.task-item {
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease;
}

.task-item:hover,
.task-item.active {
  border-color: var(--accent);
  background: var(--surface2);
}

.article-title,
.result-title {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: 14px;
  font-weight: 500;
}

.article-title {
  font-family: var(--font);
  font-size: 18px;
  line-height: 1.2;
}

.article-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 10px;
  margin-top: 6px;
}

.preview-empty {
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.task-layout {
  display: grid;
  grid-template-columns: minmax(260px, 0.75fr) minmax(0, 1.25fr);
  gap: 16px;
  align-items: stretch;
  min-height: 360px;
  max-height: min(640px, calc(100vh - 260px));
  overflow: hidden;
}

.task-list {
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.task-detail {
  min-height: 0;
  overflow: hidden;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: rgba(250, 249, 245, 0.72);
}

.detail-head {
  align-items: flex-start;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(255, 253, 248, 0.96) 0%, rgba(240, 238, 230, 0.72) 100%);
}

.detail-title {
  font-family: var(--font);
  font-size: 22px;
  font-weight: 500;
  line-height: 1.2;
}

.detail-sub {
  margin-top: 6px;
  overflow-wrap: anywhere;
}

.detail-progress-card {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
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
  background: linear-gradient(90deg, var(--accent) 0%, var(--accent-hover) 100%);
  transition: width 180ms ease;
}

.progress-text {
  color: var(--text);
  font-size: 13px;
}

.error-box {
  padding: 10px 12px;
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.08);
  color: var(--error);
  overflow-wrap: anywhere;
}

.result-item {
  align-items: flex-start;
  justify-content: flex-start;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(250, 249, 245, 0.92);
}

.result-body {
  flex: 1 1 auto;
  min-width: 0;
}

.result-title {
  font-size: 13px;
  font-weight: 600;
}

.result-path {
  margin-top: 4px;
  line-height: 1.5;
}

.result-scroll-panel {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

@media (max-width: 1080px) {
  .wechat-collect-grid,
  .task-layout {
    grid-template-columns: 1fr;
  }

  .task-layout {
    max-height: none;
    overflow: visible;
  }

  .task-list {
    max-height: min(320px, 44vh);
  }

  .task-detail {
    overflow: visible;
  }

  .result-scroll-panel {
    max-height: min(420px, 56vh);
  }

  .preview-card {
    max-height: none;
    overflow: visible;
  }

  .preview-card :deep(> .n-card__content),
  .preview-scroll-panel {
    overflow: visible;
  }

  .preview-scroll-panel {
    padding-right: 0;
  }
}

@media (max-width: 720px) {
  .form-grid {
    grid-template-columns: 1fr;
  }

  .account-strip,
  .detail-head,
  .progress-text {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
