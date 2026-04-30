<template>
  <div class="ai-creation-page">
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('aiCreation.title') }}</div>
        <div class="page-desc">{{ t('aiCreation.desc') }}</div>
      </div>
      <div class="page-actions">
        <NButton tertiary @click="refreshCurrentTab">
          {{ t('aiCreation.refresh') }}
        </NButton>
      </div>
    </div>

    <div class="ai-creation-segment">
      <NRadioGroup v-model:value="currentTab" name="ai-creation-tab" size="large">
        <NRadioButton value="article">
          {{ t('aiCreation.articleTab') }}
        </NRadioButton>
        <NRadioButton value="video">
          {{ t('aiCreation.videoTab') }}
        </NRadioButton>
      </NRadioGroup>
    </div>

    <div class="ai-creation-grid">
      <div ref="formPanelRef" class="ai-form-panel">
        <NCard class="ai-card" :title="tabTitle">
          <template #header-extra>
            <NTag size="small" :bordered="false" type="info">
              {{ taskCountLabel }}
            </NTag>
          </template>

          <div v-if="currentTab === 'article'" class="ai-form-stack">
            <div v-if="articleSourceHint" class="prefill-banner">
              <span>{{ articleSourceHint }}</span>
              <NButton text type="primary" @click="clearArticlePrefill">
                {{ t('aiCreation.clearPrefill') }}
              </NButton>
            </div>

            <NForm :model="articleForm" label-placement="top">
              <div class="ai-form-grid">
                <NFormItem :label="t('aiCreation.article.sourceType')">
                  <NSelect
                    v-model:value="articleForm.source_type"
                    :options="articleSourceTypeOptions"
                  />
                </NFormItem>

                <NFormItem v-if="articleForm.source_type !== 'wechat_article'" :label="t('aiCreation.article.monitorVideoId')">
                  <NInputNumber
                    v-model:value="articleForm.monitor_video_id"
                    :show-button="false"
                    clearable
                    style="width: 100%"
                  />
                </NFormItem>

                <NFormItem v-if="articleForm.source_type !== 'wechat_article'" :label="t('aiCreation.article.videoId')">
                  <NInput v-model:value="articleForm.video_id" />
                </NFormItem>

                <NFormItem v-if="articleForm.source_type !== 'wechat_article'" class="ai-form-grid__wide" :label="t('aiCreation.article.videoTitle')">
                  <NInput v-model:value="articleForm.video_title" />
                </NFormItem>

                <NFormItem v-if="articleForm.source_type !== 'wechat_article'" class="ai-form-grid__wide" :label="t('aiCreation.article.videoUrl')">
                  <NInput v-model:value="articleForm.video_url" />
                </NFormItem>

                <NFormItem v-if="articleForm.source_type === 'wechat_article'" class="ai-form-grid__wide" :label="t('aiCreation.article.sourceTitle')">
                  <NInput v-model:value="articleForm.source_title" />
                </NFormItem>

                <NFormItem v-if="articleForm.source_type === 'wechat_article'" class="ai-form-grid__wide" :label="t('aiCreation.article.articleSourcePath')">
                  <NInput v-model:value="articleForm.article_source_path" />
                </NFormItem>

                <NFormItem v-if="articleForm.source_type === 'wechat_article'" class="ai-form-grid__wide" :label="t('aiCreation.article.sourceUrl')">
                  <NInput v-model:value="articleForm.source_url" />
                </NFormItem>

                <NFormItem v-if="articleForm.source_type === 'wechat_article'" class="ai-form-grid__wide" :label="t('aiCreation.article.articleSourceText')">
                  <NInput
                    v-model:value="articleForm.article_text"
                    type="textarea"
                    :autosize="{ minRows: 4, maxRows: 10 }"
                  />
                </NFormItem>

                <NFormItem :label="t('aiCreation.article.targetLang')">
                  <NInput v-model:value="articleForm.target_lang" :placeholder="t('aiCreation.article.targetLangPlaceholder')" />
                </NFormItem>

                <NFormItem :label="t('aiCreation.article.autoTranslate')">
                  <NSwitch v-model:value="articleForm.auto_translate" />
                </NFormItem>
              </div>
            </NForm>

            <div class="ai-action-row">
              <NButton
                type="primary"
                :loading="submittingArticle"
                :disabled="!canSubmitArticle"
                @click="submitArticleTask"
              >
                {{ t('aiCreation.article.submit') }}
              </NButton>
              <span class="ai-help-text">{{ t('aiCreation.article.submitHint') }}</span>
            </div>
          </div>

          <div v-else class="ai-form-stack">
            <NForm :model="videoForm" label-placement="top">
              <div class="ai-form-grid">
                <NFormItem :label="t('aiCreation.video.mode')">
                  <NSelect
                    v-model:value="videoForm.mode"
                    :options="videoModeOptions"
                  />
                </NFormItem>

                <NFormItem :label="t('aiCreation.video.template')">
                  <NSelect
                    v-model:value="videoForm.template"
                    :options="templateOptions"
                    :loading="templatesLoading"
                    filterable
                    clearable
                  />
                </NFormItem>

                <NFormItem class="ai-form-grid__wide" :label="t('aiCreation.video.topic')">
                  <NInput
                    v-model:value="videoForm.topic"
                    type="textarea"
                    :autosize="{ minRows: 2, maxRows: 4 }"
                    :placeholder="t('aiCreation.video.topicPlaceholder')"
                  />
                </NFormItem>

                <NFormItem
                  v-if="videoForm.mode === 'fixed'"
                  class="ai-form-grid__wide"
                  :label="t('aiCreation.video.script')"
                >
                  <NInput
                    v-model:value="videoForm.script"
                    type="textarea"
                    :autosize="{ minRows: 4, maxRows: 8 }"
                    :placeholder="t('aiCreation.video.scriptPlaceholder')"
                  />
                </NFormItem>

                <NFormItem :label="t('aiCreation.video.scenes')">
                  <NInputNumber v-model:value="videoForm.n_scenes" :min="1" :max="12" :show-button="false" style="width: 100%" />
                </NFormItem>

                <NFormItem :label="t('aiCreation.video.ttsWorkflow')">
                  <NInput v-model:value="videoForm.tts_workflow" :placeholder="t('aiCreation.video.ttsWorkflowPlaceholder')" />
                </NFormItem>

                <NFormItem :label="t('aiCreation.video.imageWorkflow')">
                  <NInput v-model:value="videoForm.image_workflow" :placeholder="t('aiCreation.video.imageWorkflowPlaceholder')" />
                </NFormItem>

                <NFormItem :label="t('aiCreation.video.bgmVolume')">
                  <NInputNumber v-model:value="videoForm.bgm_volume" :min="0" :max="1" :step="0.1" :show-button="false" style="width: 100%" />
                </NFormItem>

                <NFormItem class="ai-form-grid__wide" :label="t('aiCreation.video.promptPrefix')">
                  <NInput v-model:value="videoForm.prompt_prefix" :placeholder="t('aiCreation.video.promptPrefixPlaceholder')" />
                </NFormItem>
              </div>
            </NForm>

            <div class="ai-action-row">
              <NButton
                type="primary"
                :loading="submittingVideo"
                :disabled="!canSubmitVideo"
                @click="submitVideoTask"
              >
                {{ t('aiCreation.video.submit') }}
              </NButton>
              <span class="ai-help-text">{{ t('aiCreation.video.submitHint') }}</span>
            </div>
          </div>
        </NCard>
      </div>

      <NCard
        class="ai-card ai-history-card"
        :style="historyMaxHeight ? { '--ai-history-max-height': historyMaxHeight } : undefined"
        :title="historyTitle"
      >
        <template #header-extra>
          <div class="history-controls">
            <NSelect
              v-model:value="statusFilter"
              :options="statusFilterOptions"
              :placeholder="t('aiCreation.filters.status')"
              clearable
              style="width: 150px"
            />
            <NButton tertiary size="small" :loading="listLoading" @click="refreshCurrentTab">
              {{ t('aiCreation.refresh') }}
            </NButton>
          </div>
        </template>

        <div class="history-scroll-panel">
          <div v-if="listLoading && !filteredTasks.length" class="history-loading">
            <NSpin size="small" />
          </div>

          <div v-else-if="!filteredTasks.length" class="history-empty">
            <NEmpty :description="t('aiCreation.empty')" />
          </div>

          <div v-else class="task-list">
            <button
              v-for="task in filteredTasks"
              :key="taskKey(task)"
              type="button"
              class="task-item"
              :class="{ 'task-item--active': selectedTaskId === taskKey(task) }"
              @click="selectTask(taskKey(task))"
            >
              <div class="task-item__top">
                <div class="task-item__title">{{ taskHeadline(task) }}</div>
                <NTag size="small" :bordered="false" :type="statusType(taskStatus(task))">
                  {{ taskStatusLabel(taskStatus(task)) }}
                </NTag>
              </div>
              <div class="task-item__meta">
                <span>{{ taskSubline(task) }}</span>
                <span>{{ formatDateTime(taskTimestamp(task)) }}</span>
              </div>
              <div class="task-item__bottom">
                <span class="task-item__stage">{{ taskStageLabel(task) }}</span>
                <NButton
                  v-if="canCancelTask(task)"
                  text
                  type="warning"
                  size="small"
                  @click.stop="cancelTask(taskKey(task))"
                >
                  {{ t('aiCreation.cancel') }}
                </NButton>
              </div>
            </button>
          </div>
        </div>
      </NCard>
    </div>

    <NCard class="ai-card ai-detail-card" :title="detailTitle">
      <template #header-extra>
        <div v-if="selectedTaskId" class="detail-actions">
          <NButton tertiary size="small" :loading="detailLoading" @click="() => refreshSelectedTask()">
            {{ t('aiCreation.refresh') }}
          </NButton>
          <NButton
            v-if="selectedTask && canCancelTask(selectedTask)"
            tertiary
            type="warning"
            size="small"
            :loading="cancellingTaskId === selectedTaskId"
            @click="cancelTask(selectedTaskId)"
          >
            {{ t('aiCreation.cancel') }}
          </NButton>
        </div>
      </template>

      <div v-if="!selectedTaskId" class="history-empty">
        <NEmpty :description="t('aiCreation.detailEmpty')" />
      </div>

      <div v-else-if="detailLoading && !selectedTask" class="history-loading">
        <NSpin size="small" />
      </div>

      <div v-else-if="selectedTask" class="task-detail">
        <div v-if="taskStatus(selectedTask) === 'interrupted'" class="detail-interrupted-banner">
          <span>{{ t('aiCreation.interruptedHint') }}</span>
        </div>

        <div class="task-detail__hero">
          <div>
            <div class="task-detail__eyebrow">
              {{ currentTab === 'article' ? t('aiCreation.article.detailLabel') : t('aiCreation.video.detailLabel') }}
            </div>
            <div class="task-detail__title">{{ taskHeadline(selectedTask) }}</div>
            <div class="task-detail__meta">
              <span>{{ t('aiCreation.detail.taskId') }} {{ selectedTaskId }}</span>
              <span>{{ formatDateTime(taskTimestamp(selectedTask)) }}</span>
            </div>
          </div>
          <NTag :bordered="false" :type="statusType(taskStatus(selectedTask))">
            {{ taskStatusLabel(taskStatus(selectedTask)) }}
          </NTag>
        </div>

        <div v-if="progressPercent(selectedTask) > 0" class="task-progress">
          <div class="task-progress__top">
            <span>{{ taskStageLabel(selectedTask) }}</span>
            <span>{{ progressPercent(selectedTask) }}%</span>
          </div>
          <div class="task-progress__track">
            <div class="task-progress__fill" :style="{ width: `${progressPercent(selectedTask)}%` }"></div>
          </div>
        </div>

        <div class="task-facts">
          <div class="task-fact">
            <span>{{ t('aiCreation.detail.stage') }}</span>
            <strong>{{ taskStageLabel(selectedTask) }}</strong>
          </div>
          <div class="task-fact">
            <span>{{ t('aiCreation.detail.updatedAt') }}</span>
            <strong>{{ formatDateTime(taskUpdatedAt(selectedTask)) }}</strong>
          </div>
          <div class="task-fact">
            <span>{{ t('aiCreation.detail.target') }}</span>
            <strong>{{ detailTargetLabel(selectedTask) }}</strong>
          </div>
          <div class="task-fact">
            <span>{{ t('aiCreation.detail.output') }}</span>
            <strong>{{ firstTruthy(selectedTask.output_path, selectedTask.video_path, selectedTask.output_dir, selectedTask.draft_path, selectedTask.video_url) || '—' }}</strong>
          </div>
        </div>

        <div v-if="normalizedStages(selectedTask).length" class="stage-list">
          <div
            v-for="stage in normalizedStages(selectedTask)"
            :key="stage.key"
            class="stage-item"
          >
            <div class="stage-item__row">
              <span class="stage-item__name">{{ stage.name }}</span>
              <NTag size="small" :bordered="false" :type="statusType(stage.status)">
                {{ taskStatusLabel(stage.status) }}
              </NTag>
            </div>
            <div v-if="stage.message" class="stage-item__message">{{ stage.message }}</div>
          </div>
        </div>

        <div v-if="selectedTaskOutputFiles.length" class="output-file-list">
          <div class="output-file-list__title">{{ t('aiCreation.detail.outputFiles') }}</div>
          <div
            v-for="file in selectedTaskOutputFiles"
            :key="file.path || file.name"
            class="output-file"
          >
            <div>
              <div class="output-file__name">{{ file.name || file.path }}</div>
              <div class="output-file__meta">
                <span>{{ formatFileSize(file.size) }}</span>
                <span v-if="file.updated_at">{{ formatDateTime(file.updated_at) }}</span>
              </div>
            </div>
            <NButton
              v-if="taskOutputFileHref(file)"
              text
              type="primary"
              size="small"
              @click="openTaskLink(taskOutputFileHref(file))"
            >
              {{ t('aiCreation.detail.openOutput') }}
            </NButton>
          </div>
        </div>

        <div v-if="selectedTask.error" class="detail-error">
          {{ selectedTask.error }}
        </div>

        <div v-if="canPublishSelectedArticle" class="wechat-publish-panel">
          <div>
            <div class="wechat-publish-panel__title">{{ t('aiCreation.wechatPublishTitle') }}</div>
            <div class="wechat-publish-panel__desc">{{ t('aiCreation.wechatPublishDesc') }}</div>
            <div v-if="wechatPublishTaskId" class="wechat-publish-panel__status">
              {{ wechatPublishStatusLabel }}: {{ wechatPublishStatus || t('aiCreation.status.pending') }}
            </div>
            <div v-if="wechatPublishError" class="wechat-publish-panel__error">
              {{ wechatPublishError }}
            </div>
            <div v-if="wechatPublishHasDiagnostics" class="wechat-publish-panel__diagnostics">
              <div v-if="wechatPublishRenderer" class="wechat-publish-panel__diagnostic">
                <span>{{ t('aiCreation.wechatPublishRenderer') }}</span>
                <strong>{{ wechatPublishRenderer }}</strong>
              </div>
              <div v-if="wechatPublishHtmlPath" class="wechat-publish-panel__diagnostic">
                <span>{{ t('aiCreation.wechatPublishHtmlPath') }}</span>
                <code>{{ wechatPublishHtmlPath }}</code>
                <NButton
                  v-if="wechatPublishHtmlHref"
                  text
                  type="primary"
                  size="small"
                  @click="openTaskLink(wechatPublishHtmlHref)"
                >
                  {{ t('aiCreation.wechatPublishOpenHtml') }}
                </NButton>
              </div>
              <div v-if="wechatPublishWarnings.length" class="wechat-publish-panel__warning">
                <div v-for="warning in wechatPublishWarnings" :key="warning">
                  {{ warning }}
                </div>
              </div>
            </div>
          </div>
          <div class="wechat-publish-panel__actions">
            <NButton
              :loading="isWechatPublishBusy && wechatPublishMode === 'draft'"
              :disabled="isWechatPublishBusy"
              @click="saveSelectedArticleToWechatDraft"
            >
              {{ t('aiCreation.saveToWechatDraft') }}
            </NButton>
            <NButton
              type="warning"
              :loading="isWechatPublishBusy && wechatPublishMode === 'publish'"
              :disabled="isWechatPublishBusy"
              @click="confirmPublishSelectedArticleNow"
            >
              {{ t('aiCreation.publishNow') }}
            </NButton>
          </div>
        </div>

        <div v-if="detailLinks(selectedTask).length" class="detail-links">
          <NButton
            v-for="link in detailLinks(selectedTask)"
            :key="link.label"
            tertiary
            type="primary"
            @click="openTaskLink(link.href)"
          >
            {{ link.label }}
          </NButton>
        </div>

        <pre v-if="detailPreview(selectedTask)" class="detail-preview">{{ detailPreview(selectedTask) }}</pre>
      </div>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
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
  NSpin,
  NSwitch,
  NTag,
  useDialog,
  useMessage,
} from 'naive-ui'
import aiContentApi, { type AiTemplateOption, type ArticleTaskCreatePayload, type VideoTaskCreatePayload } from '@/api/aiContent'
import request from '@/api/request'
import wechatPublishApi from '@/api/wechatPublish'

type AiTab = 'article' | 'video'

interface AiTaskRecord extends Record<string, any> {}

interface StageItem {
  key: string
  name: string
  status: string
  message: string
}

const POLL_INTERVAL_MS = 3000
const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000'
const AI_TASK_TERMINAL_STATUSES = new Set(['done', 'error', 'cancelled', 'interrupted'])
const WECHAT_PUBLISH_TERMINAL_STATUSES = new Set(['done', 'error', 'cancelled', 'interrupted'])

const normalizeTaskStatus = (value: unknown) => {
  const rawStatus = String(value || '').toLowerCase()
  if (!rawStatus) return 'pending'
  if (rawStatus === 'processing') return 'running'
  return rawStatus
}

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()

const currentTab = ref<AiTab>('article')
const statusFilter = ref<string | null>(null)
const articleTasks = ref<AiTaskRecord[]>([])
const videoTasks = ref<AiTaskRecord[]>([])
const selectedTaskId = ref('')
const selectedTask = ref<AiTaskRecord | null>(null)
const formPanelRef = ref<HTMLElement | null>(null)
const historyMaxHeight = ref('')
const listLoading = ref(false)
const detailLoading = ref(false)
const submittingArticle = ref(false)
const submittingVideo = ref(false)
const templatesLoading = ref(false)
const cancellingTaskId = ref('')
const templateOptions = ref<Array<{ label: string; value: string }>>([])
const publishingWechat = ref(false)
const wechatPublishTaskId = ref('')
const wechatPublishStatus = ref('')
const wechatPublishMode = ref<'draft' | 'publish' | ''>('')
const wechatPublishError = ref('')
const wechatPublishRenderer = ref('')
const wechatPublishHtmlPath = ref('')
const wechatPublishWarnings = ref<string[]>([])
const pendingWechatPublishMode = ref<'draft' | 'publish' | ''>('')
const pendingWechatPublishTaskId = ref('')
const pendingWechatPublishAutoSubmit = ref(false)
let detailPollTimer: number | null = null
let wechatPollTimer: number | null = null
let formResizeObserver: ResizeObserver | null = null
let lastPrefillToken = ''

const clearPendingWechatPublishIntent = () => {
  pendingWechatPublishMode.value = ''
  pendingWechatPublishTaskId.value = ''
  pendingWechatPublishAutoSubmit.value = false
}

const clearPendingWechatPublishForTask = (taskId: string) => {
  if (!taskId || pendingWechatPublishTaskId.value === taskId) {
    clearPendingWechatPublishIntent()
  }
}

const articleForm = reactive<ArticleTaskCreatePayload>({
  source_type: 'video',
  monitor_video_id: undefined,
  video_id: '',
  video_url: '',
  video_title: '',
  wechat_artifact_id: '',
  article_source_path: '',
  article_text: '',
  source_url: '',
  source_title: '',
  target_lang: 'zh-Hans',
  auto_translate: true,
})

const videoForm = reactive<VideoTaskCreatePayload>({
  mode: 'generate',
  topic: '',
  script: '',
  template: '',
  n_scenes: 5,
  prompt_prefix: '',
  tts_workflow: 'edge-tts',
  image_workflow: '',
  bgm_volume: 0.3,
})

const videoModeOptions = computed(() => [
  { label: t('aiCreation.video.modeGenerate'), value: 'generate' },
  { label: t('aiCreation.video.modeFixed'), value: 'fixed' },
])

const articleSourceTypeOptions = computed(() => [
  { label: t('aiCreation.article.sourceVideo'), value: 'video' },
  { label: t('aiCreation.article.sourceWechatArticle'), value: 'wechat_article' },
])

const statusFilterOptions = computed(() => [
  { label: t('aiCreation.filters.all'), value: '' },
  { label: t('aiCreation.status.pending'), value: 'pending' },
  { label: t('aiCreation.status.running'), value: 'running' },
  { label: t('aiCreation.status.done'), value: 'done' },
  { label: t('aiCreation.status.error'), value: 'error' },
  { label: t('aiCreation.status.interrupted'), value: 'interrupted' },
  { label: t('aiCreation.status.cancelled'), value: 'cancelled' },
])

const tabTasks = computed(() => currentTab.value === 'article' ? articleTasks.value : videoTasks.value)

const filteredTasks = computed(() => {
  const targetStatus = statusFilter.value || ''
  return tabTasks.value.filter((task) => !targetStatus || taskStatus(task) === targetStatus)
})

const tabTitle = computed(() => currentTab.value === 'article'
  ? t('aiCreation.articlePanelTitle')
  : t('aiCreation.videoPanelTitle'))

const historyTitle = computed(() => currentTab.value === 'article'
  ? t('aiCreation.articleHistoryTitle')
  : t('aiCreation.videoHistoryTitle'))

const detailTitle = computed(() => currentTab.value === 'article'
  ? t('aiCreation.articleDetailTitle')
  : t('aiCreation.videoDetailTitle'))

const taskCountLabel = computed(() => t('aiCreation.count', { n: tabTasks.value.length }))

const articleSourceHint = computed(() => {
  const pieces: string[] = []
  const accountName = getQueryString('accountName')
  if (accountName) pieces.push(accountName)
  if (articleForm.source_type === 'wechat_article') {
    if (articleForm.source_title || articleForm.video_title) {
      pieces.push(articleForm.source_title || articleForm.video_title || '')
    }
    if (!pieces.length) return ''
    return t('aiCreation.article.prefilledFromWechat', { title: pieces.join(' · ') })
  }
  if (articleForm.video_title) pieces.push(articleForm.video_title)
  if (!pieces.length) return ''
  return t('aiCreation.article.prefilledFromVideo', { title: pieces.join(' · ') })
})

const canSubmitArticle = computed(() => {
  if (articleForm.source_type === 'wechat_article') {
    return Boolean(
      articleForm.wechat_artifact_id?.trim()
      || articleForm.article_source_path?.trim()
      || articleForm.article_text?.trim(),
    )
  }
  return Boolean(articleForm.monitor_video_id || articleForm.video_id?.trim() || articleForm.video_url?.trim())
})

function clearVideoArticleFields() {
  articleForm.monitor_video_id = undefined
  articleForm.video_id = ''
  articleForm.video_url = ''
  articleForm.video_title = ''
}

function clearWechatArticleFields() {
  articleForm.wechat_artifact_id = ''
  articleForm.article_source_path = ''
  articleForm.article_text = ''
  articleForm.source_url = ''
  articleForm.source_title = ''
  pendingWechatPublishMode.value = ''
  pendingWechatPublishTaskId.value = ''
  pendingWechatPublishAutoSubmit.value = false
}

const canSubmitVideo = computed(() => {
  if (videoForm.mode === 'fixed') {
    return Boolean(videoForm.script?.trim())
  }
  return Boolean(videoForm.topic?.trim())
})

const selectedTaskCollection = computed(() => currentTab.value === 'article' ? articleTasks : videoTasks)

const articleDraftPath = (task: AiTaskRecord | null | undefined) => {
  const result = parseJsonMaybe(task?.result || task?.outputs || task?.metadata) as Record<string, string> | null
  return firstTruthy(task?.draft_path, result?.draft_path)
}

const canPublishSelectedArticle = computed(() => (
  currentTab.value === 'article'
  && taskStatus(selectedTask.value) === 'done'
  && Boolean(articleDraftPath(selectedTask.value))
))

const wechatPublishStatusLabel = computed(() => (
  wechatPublishMode.value === 'publish'
    ? t('aiCreation.wechatPublishLabelPublish')
    : t('aiCreation.wechatPublishLabelDraft')
))

const isWechatPublishBusy = computed(() => {
  if (publishingWechat.value) return true
  if (!wechatPublishTaskId.value) return false
  return !WECHAT_PUBLISH_TERMINAL_STATUSES.has(normalizeTaskStatus(wechatPublishStatus.value))
})

const wechatPublishHtmlHref = computed(() => (
  wechatPublishHtmlPath.value
    ? `/api/article/file?path=${encodeURIComponent(wechatPublishHtmlPath.value)}`
    : ''
))

const wechatPublishHasDiagnostics = computed(() => Boolean(
  wechatPublishRenderer.value
  || wechatPublishHtmlPath.value
  || wechatPublishWarnings.value.length,
))

const normalizeWechatPublishIntent = (value: string): 'draft' | 'publish' | '' => {
  const normalized = value.trim().toLowerCase()
  if (normalized === 'wechatdraft' || normalized === 'draft') return 'draft'
  if (normalized === 'wechatpublish' || normalized === 'publish' || normalized === 'publishnow') return 'publish'
  return ''
}

const normalizeArray = (value: unknown): any[] => {
  if (Array.isArray(value)) return value
  if (!value || typeof value !== 'object') return []
  const objectValue = value as Record<string, unknown>
  for (const key of ['tasks', 'items', 'list', 'rows', 'records', 'data']) {
    if (Array.isArray(objectValue[key])) {
      return objectValue[key] as any[]
    }
  }
  return []
}

const taskOutputFiles = (task: AiTaskRecord | null | undefined) => (
  normalizeArray(task?.output_files)
    .map((file) => file as Record<string, any>)
    .filter((file) => file.name || file.path)
)

const selectedTaskOutputFiles = computed(() => taskOutputFiles(selectedTask.value))

const taskOutputFileHref = (file: Record<string, any>) => {
  const path = String(file?.path || '').trim()
  if (!path || currentTab.value !== 'article') return ''
  return `/api/article/file?path=${encodeURIComponent(path)}`
}

const formatFileSize = (value: unknown) => {
  const size = Number(value || 0)
  if (!Number.isFinite(size) || size <= 0) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

const taskKey = (task: AiTaskRecord) => String(task?.task_id || task?.id || '')

const taskStatus = (task: AiTaskRecord | null | undefined) => (
  normalizeTaskStatus(task?.status || task?.state || task?.task_status || '')
)

const isTerminalTaskStatus = (status: string) => AI_TASK_TERMINAL_STATUSES.has(normalizeTaskStatus(status))

const taskTimestamp = (task: AiTaskRecord | null | undefined) => (
  task?.created_at || task?.createdAt || task?.started_at || task?.updated_at || task?.updatedAt || ''
)

const taskUpdatedAt = (task: AiTaskRecord | null | undefined) => (
  task?.updated_at || task?.updatedAt || task?.finished_at || task?.completed_at || ''
)

const taskHeadline = (task: AiTaskRecord) => {
  if (currentTab.value === 'article') {
    return firstTruthy(task.source_title, task.video_title, task.title, task.video_id, task.source_url, task.video_url, taskKey(task)) || taskKey(task)
  }
  return firstTruthy(task.topic, task.title, task.template, taskKey(task)) || taskKey(task)
}

const taskSubline = (task: AiTaskRecord) => {
  if (currentTab.value === 'article') {
    return firstTruthy(task.target_lang, task.source_type, task.article_source_path, task.video_id, task.video_url, task.monitor_video_id) || '—'
  }
  return firstTruthy(task.template, task.mode, task.n_scenes ? `${task.n_scenes} scenes` : '', task.image_workflow) || '—'
}

const parseJsonMaybe = (value: unknown) => {
  if (!value) return null
  if (typeof value === 'string') {
    try {
      return JSON.parse(value)
    } catch {
      return null
    }
  }
  return value
}

const normalizedStages = (task: AiTaskRecord): StageItem[] => {
  const rawStages = parseJsonMaybe(task?.stages || task?.stage_summary || task?.stage_details || task?.progress)
  if (Array.isArray(rawStages)) {
    return rawStages.map((stage, index) => ({
      key: String(stage?.key || stage?.stage || index),
      name: String(stage?.name || stage?.stage || t('aiCreation.detail.stageFallback', { n: index + 1 })),
      status: taskStatus(stage),
      message: String(stage?.message || stage?.error || ''),
    }))
  }
  if (rawStages && typeof rawStages === 'object') {
    return Object.entries(rawStages as Record<string, any>).map(([key, stage]) => ({
      key,
      name: String(stage?.name || key),
      status: taskStatus(stage),
      message: String(stage?.message || stage?.error || ''),
    }))
  }
  return []
}

const taskStageLabel = (task: AiTaskRecord) => {
  const rawStage = String(task?.stage || task?.current_stage || task?.stage_name || '')
  if (rawStage) return rawStage
  const stages = normalizedStages(task)
  const activeStage = stages.find((stage) => ['running', 'pending', 'cancelling'].includes(stage.status))
  if (activeStage) return activeStage.name
  return t('aiCreation.detail.noStage')
}

const progressPercent = (task: AiTaskRecord | null | undefined) => {
  if (!task) return 0
  const direct = Number(task.progress_percent ?? task.progress ?? task.percent ?? 0)
  if (Number.isFinite(direct) && direct > 0) {
    return Math.max(0, Math.min(100, Math.round(direct)))
  }
  const stages = normalizedStages(task)
  if (!stages.length) return 0
  const finished = stages.filter((stage) => taskStatus(stage) === 'done').length
  return Math.round((finished / stages.length) * 100)
}

const firstTruthy = (...values: Array<string | number | null | undefined>) => {
  for (const value of values) {
    if (value === null || value === undefined) continue
    const text = String(value).trim()
    if (text) return text
  }
  return ''
}

const detailTargetLabel = (task: AiTaskRecord) => {
  if (currentTab.value === 'article') {
    return firstTruthy(task.target_lang, task.source_type, task.video_id, task.monitor_video_id) || '—'
  }
  return firstTruthy(task.template, task.mode, task.n_scenes ? `${task.n_scenes}` : '') || '—'
}

const statusType = (status: string) => {
  switch (status) {
    case 'done':
      return 'success'
    case 'error':
      return 'error'
    case 'cancelled':
    case 'interrupted':
      return 'default'
    case 'cancelling':
      return 'warning'
    case 'running':
      return 'info'
    default:
      return 'warning'
  }
}

const taskStatusLabel = (status: string) => t(`aiCreation.status.${status}`, status)

const canCancelTask = (task: AiTaskRecord | null | undefined) => {
  const status = taskStatus(task)
  return ['pending', 'running', 'processing', 'queued', 'cancelling'].includes(status)
}

const formatDateTime = (value?: string) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

const resolveApiHref = (value: string) => {
  if (/^https?:\/\//i.test(value)) return value
  if (value.startsWith('/')) return new URL(value, API_BASE).toString()
  return value
}

const isInternalApiHref = (href: string) => {
  try {
    const url = new URL(href, API_BASE)
    const base = new URL(API_BASE)
    return url.origin === base.origin && url.pathname.startsWith('/api/')
  } catch {
    return false
  }
}

const detailLinks = (task: AiTaskRecord) => {
  const links: Array<{ label: string; href: string }> = []
  const pushLink = (label: string, value?: string) => {
    if (!value) return
    links.push({ label, href: resolveApiHref(value) })
  }
  const result = parseJsonMaybe(task.result || task.outputs || task.metadata) as Record<string, string> | null

  if (currentTab.value === 'article') {
    pushLink(t('aiCreation.detail.openDraft'), firstTruthy(task.draft_url, result?.draft_url, task.draft_path))
    pushLink(t('aiCreation.detail.openOutput'), firstTruthy(task.output_url, result?.output_url, result?.draft_url, task.output_path, task.output_dir))
    const tools = parseJsonMaybe(task.article_tools_links)
    if (tools && typeof tools === 'object') {
      Object.entries(tools as Record<string, string>).forEach(([label, href]) => pushLink(label, href))
    }
  } else {
    pushLink(t('aiCreation.detail.previewVideo'), firstTruthy(task.video_url, result?.video_url, task.output_url, result?.output_url, task.download_url, task.video_path))
    pushLink(t('aiCreation.detail.openOutput'), firstTruthy(task.output_url, result?.output_url, task.output_path, task.video_path, task.output_dir))
  }

  return links
}

const detailPreview = (task: AiTaskRecord) => {
  const preview = parseJsonMaybe(task.metadata || task.result || task.outputs)
  if (!preview) return ''
  try {
    return JSON.stringify(preview, null, 2)
  } catch {
    return ''
  }
}

const getQueryString = (key: string) => {
  const value = route.query[key]
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

const stopDetailPolling = () => {
  if (detailPollTimer !== null) {
    window.clearInterval(detailPollTimer)
    detailPollTimer = null
  }
}

const stopWechatPolling = () => {
  if (wechatPollTimer !== null) {
    window.clearTimeout(wechatPollTimer)
    wechatPollTimer = null
  }
}

const ensureDetailPolling = () => {
  stopDetailPolling()
  if (!selectedTaskId.value || !selectedTask.value) {
    return
  }
  const status = taskStatus(selectedTask.value)
  if (!canCancelTask(selectedTask.value) || status === 'interrupted') {
    return
  }
  detailPollTimer = window.setInterval(() => {
    void refreshSelectedTask(true)
  }, POLL_INTERVAL_MS)
}

const syncRouteTab = async () => {
  const targetTab = currentTab.value
  const nextQuery = { ...route.query, tab: targetTab }
  if (route.query.tab === targetTab) return
  await router.replace({ query: nextQuery })
}

const applyRouteState = () => {
  const requestedTab = getQueryString('tab')
  if (requestedTab === 'article' || requestedTab === 'video') {
    currentTab.value = requestedTab
  }

  const prefillParts = [
    getQueryString('sourceType'),
    getQueryString('monitorVideoId'),
    getQueryString('videoId'),
    getQueryString('videoUrl'),
    getQueryString('videoTitle'),
    getQueryString('articleArtifact'),
    getQueryString('articlePath'),
    getQueryString('articleUrl'),
    getQueryString('articleTitle'),
    getQueryString('publishIntent'),
  ]
  const prefillToken = prefillParts.join('|')
  if (!prefillParts.some(Boolean)) return
  if (!prefillToken || prefillToken === lastPrefillToken) return

  const sourceType = getQueryString('sourceType')
  if (sourceType === 'wechatArticle') {
    articleForm.source_type = 'wechat_article'
    articleForm.monitor_video_id = undefined
    articleForm.video_id = ''
    articleForm.video_url = ''
    articleForm.wechat_artifact_id = getQueryString('articleArtifact')
    articleForm.article_source_path = getQueryString('articlePath')
    articleForm.article_text = ''
    articleForm.source_url = getQueryString('articleUrl')
    articleForm.source_title = getQueryString('articleTitle')
    articleForm.video_title = getQueryString('articleTitle')
    pendingWechatPublishMode.value = normalizeWechatPublishIntent(getQueryString('publishIntent'))
    pendingWechatPublishTaskId.value = ''
    pendingWechatPublishAutoSubmit.value = Boolean(pendingWechatPublishMode.value)
    currentTab.value = 'article'
    lastPrefillToken = prefillToken
    return
  }

  const monitorVideoId = Number(getQueryString('monitorVideoId'))
  articleForm.source_type = 'video'
  articleForm.monitor_video_id = Number.isFinite(monitorVideoId) && monitorVideoId > 0 ? monitorVideoId : undefined
  articleForm.video_id = getQueryString('videoId')
  articleForm.video_url = getQueryString('videoUrl')
  articleForm.video_title = getQueryString('videoTitle')
  articleForm.wechat_artifact_id = ''
  articleForm.article_source_path = ''
  articleForm.article_text = ''
  articleForm.source_url = ''
  articleForm.source_title = ''
  pendingWechatPublishAutoSubmit.value = false
  currentTab.value = 'article'
  lastPrefillToken = prefillToken
}

const loadArticleTasks = async () => {
  const res = await aiContentApi.listArticleTasks()
  articleTasks.value = normalizeArray(res.data)
}

const loadVideoTasks = async () => {
  const res = await aiContentApi.listVideoTasks()
  videoTasks.value = normalizeArray(res.data)
}

const refreshCurrentTab = async () => {
  listLoading.value = true
  try {
    if (currentTab.value === 'article') {
      await loadArticleTasks()
    } else {
      await loadVideoTasks()
    }
    if (selectedTaskId.value) {
      const found = tabTasks.value.find((task) => taskKey(task) === selectedTaskId.value)
      if (!found) {
        selectedTaskId.value = ''
        selectedTask.value = null
        stopDetailPolling()
      }
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('aiCreation.loadFailed'))
  } finally {
    listLoading.value = false
  }
}

const refreshSelectedTask = async (silent = false) => {
  if (!selectedTaskId.value) return
  if (!silent) detailLoading.value = true
  try {
    const res = currentTab.value === 'article'
      ? await aiContentApi.getArticleTask(selectedTaskId.value)
      : await aiContentApi.getVideoTask(selectedTaskId.value)
    if (res.status !== 200 || !res.data) {
      clearPendingWechatPublishForTask(selectedTaskId.value)
      selectedTask.value = null
      stopDetailPolling()
      if (!silent) {
        message.error(t('aiCreation.detailLoadFailed'))
      }
      return
    }
    selectedTask.value = res.data as AiTaskRecord
    ensureDetailPolling()
    await maybeSubmitPendingWechatPublish()
  } catch (error: any) {
    if (!silent) {
      message.error(error?.response?.data?.error || error?.message || t('aiCreation.detailLoadFailed'))
    }
  } finally {
    if (!silent) detailLoading.value = false
  }
}

const selectTask = async (taskId: string) => {
  selectedTaskId.value = taskId
  await refreshSelectedTask()
}

const pickNewestTask = async () => {
  const firstTask = filteredTasks.value[0] || tabTasks.value[0]
  if (firstTask) {
    await selectTask(taskKey(firstTask))
  } else {
    selectedTaskId.value = ''
    selectedTask.value = null
    stopDetailPolling()
  }
}

const submitArticleTask = async () => {
  submittingArticle.value = true
  try {
    const sourceType = articleForm.source_type || 'video'
    const payload: ArticleTaskCreatePayload = {
      source_type: sourceType,
      target_lang: articleForm.target_lang?.trim() || undefined,
      auto_translate: articleForm.auto_translate ?? true,
    }
    if (sourceType === 'wechat_article') {
      payload.wechat_artifact_id = articleForm.wechat_artifact_id?.trim() || undefined
      payload.article_source_path = articleForm.article_source_path?.trim() || undefined
      payload.article_text = articleForm.article_text?.trim() || undefined
      payload.source_url = articleForm.source_url?.trim() || undefined
      payload.source_title = articleForm.source_title?.trim() || undefined
    } else {
      payload.monitor_video_id = articleForm.monitor_video_id
      payload.video_id = articleForm.video_id?.trim() || undefined
      payload.video_url = articleForm.video_url?.trim() || undefined
      payload.video_title = articleForm.video_title?.trim() || undefined
    }
    const res = await aiContentApi.createArticleTask(payload)
    const taskId = String((res.data || {}).task_id || (res.data || {}).id || '')
    if (pendingWechatPublishMode.value && taskId) {
      pendingWechatPublishTaskId.value = taskId
    } else if (pendingWechatPublishMode.value && !taskId) {
      clearPendingWechatPublishIntent()
    }
    message.success(t('aiCreation.article.created'))
    await refreshCurrentTab()
    if (taskId) {
      await selectTask(taskId)
    } else {
      await pickNewestTask()
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('aiCreation.article.createFailed'))
  } finally {
    submittingArticle.value = false
  }
}

const submitVideoTask = async () => {
  submittingVideo.value = true
  try {
    const payload: VideoTaskCreatePayload = {
      mode: videoForm.mode || 'generate',
      topic: videoForm.topic?.trim() || undefined,
      script: videoForm.script?.trim() || undefined,
      template: videoForm.template?.trim() || undefined,
      n_scenes: videoForm.n_scenes || undefined,
      prompt_prefix: videoForm.prompt_prefix?.trim() || undefined,
      tts_workflow: videoForm.tts_workflow?.trim() || undefined,
      image_workflow: videoForm.image_workflow?.trim() || undefined,
      bgm_volume: videoForm.bgm_volume ?? undefined,
    }
    const res = await aiContentApi.createVideoTask(payload)
    const taskId = String((res.data || {}).task_id || (res.data || {}).id || '')
    message.success(t('aiCreation.video.created'))
    await refreshCurrentTab()
    if (taskId) {
      await selectTask(taskId)
    } else {
      await pickNewestTask()
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('aiCreation.video.createFailed'))
  } finally {
    submittingVideo.value = false
  }
}

const cancelTask = async (taskId: string) => {
  cancellingTaskId.value = taskId
  try {
    if (currentTab.value === 'article') {
      await aiContentApi.cancelArticleTask(taskId)
    } else {
      await aiContentApi.cancelVideoTask(taskId)
    }
    message.success(t('aiCreation.cancelRequested'))
    await Promise.all([refreshCurrentTab(), refreshSelectedTask()])
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('aiCreation.cancelFailed'))
  } finally {
    cancellingTaskId.value = ''
  }
}

const pollWechatStatus = async (taskId: string) => {
  stopWechatPolling()
  try {
    const res = await wechatPublishApi.getTaskStatus(taskId)
    const task = res.data || {}
    wechatPublishStatus.value = String(task.status || '')
    wechatPublishError.value = String(task.error || '')
    const status = normalizeTaskStatus(wechatPublishStatus.value)
    if (status === 'done') {
      publishingWechat.value = false
      wechatPublishError.value = ''
      message.success(t('aiCreation.wechatPublishSuccess'))
      return
    }
    if (status === 'error' || status === 'interrupted') {
      publishingWechat.value = false
      message.error(`${t('aiCreation.wechatPublishFailed')}: ${task.error || ''}`.trim())
      return
    }
    if (status === 'cancelled') {
      publishingWechat.value = false
      return
    }
    publishingWechat.value = true
    wechatPollTimer = window.setTimeout(() => {
      void pollWechatStatus(taskId)
    }, POLL_INTERVAL_MS)
  } catch (error: any) {
    publishingWechat.value = false
    message.error(error?.response?.data?.error || error?.message || t('aiCreation.wechatPublishFailed'))
  }
}

const submitWechatPublish = async (mode: 'draft' | 'publish') => {
  if (!selectedTask.value) return
  if (isWechatPublishBusy.value) return
  const draftPath = articleDraftPath(selectedTask.value)
  if (!draftPath) {
    message.error(t('aiCreation.wechatDraftMissing'))
    return
  }
  publishingWechat.value = true
  wechatPublishMode.value = mode
  wechatPublishTaskId.value = ''
  wechatPublishStatus.value = ''
  wechatPublishError.value = ''
  wechatPublishRenderer.value = ''
  wechatPublishHtmlPath.value = ''
  wechatPublishWarnings.value = []
  try {
    const payload = {
      article_task_id: taskKey(selectedTask.value),
      draft_path: draftPath,
    }
    const res = mode === 'publish'
      ? await wechatPublishApi.publishNow(payload)
      : await wechatPublishApi.saveToDraft(payload)
    const taskId = String((res.data || {}).task_id || '')
    wechatPublishTaskId.value = taskId
    wechatPublishStatus.value = String((res.data || {}).status || 'pending')
    wechatPublishRenderer.value = String(res.data?.renderer || '')
    wechatPublishHtmlPath.value = String(res.data?.html_path || '')
    const warnings = Array.isArray(res.data?.warnings) ? res.data.warnings.filter(Boolean) : []
    wechatPublishWarnings.value = warnings
    if (warnings.length) {
      message.warning(warnings.join('；'))
    }
    if (taskId) {
      await pollWechatStatus(taskId)
    } else {
      publishingWechat.value = false
    }
  } catch (error: any) {
    publishingWechat.value = false
    message.error(error?.response?.data?.error || error?.message || t('aiCreation.wechatPublishFailed'))
  }
}

const saveSelectedArticleToWechatDraft = async () => {
  await submitWechatPublish('draft')
}

async function maybeAutoSubmitPendingWechatPublish() {
  if (
    !pendingWechatPublishAutoSubmit.value
    || !pendingWechatPublishMode.value
    || pendingWechatPublishTaskId.value
    || submittingArticle.value
    || currentTab.value !== 'article'
    || articleForm.source_type !== 'wechat_article'
    || !canSubmitArticle.value
  ) {
    return false
  }
  pendingWechatPublishAutoSubmit.value = false
  await submitArticleTask()
  return true
}

async function maybeSubmitPendingWechatPublish() {
  if (!pendingWechatPublishMode.value || publishingWechat.value || !selectedTask.value) return
  const selectedId = taskKey(selectedTask.value)
  if (!pendingWechatPublishTaskId.value || pendingWechatPublishTaskId.value !== selectedId) return
  const selectedStatus = taskStatus(selectedTask.value)
  if (isTerminalTaskStatus(selectedStatus) && selectedStatus !== 'done') {
    clearPendingWechatPublishIntent()
    return
  }
  if (!canPublishSelectedArticle.value) return
  const mode = pendingWechatPublishMode.value
  clearPendingWechatPublishIntent()
  if (mode === 'publish') {
    confirmPublishSelectedArticleNow()
    return
  }
  await submitWechatPublish(mode)
}

const confirmPublishSelectedArticleNow = () => {
  dialog.warning({
    title: t('aiCreation.publishNowConfirmTitle'),
    content: t('aiCreation.publishNowConfirmContent'),
    positiveText: t('aiCreation.publishNowConfirmOk'),
    negativeText: t('aiCreation.publishNowConfirmCancel'),
    onPositiveClick: () => {
      void submitWechatPublish('publish')
    },
  })
}

const loadTemplates = async () => {
  templatesLoading.value = true
  try {
    const res = await aiContentApi.listVideoTemplates()
    const templates = normalizeArray(res.data as Record<string, unknown>) as AiTemplateOption[]
    templateOptions.value = templates.map((item) => ({
      label: String(item.label || item.name || item.value || item.path || ''),
      value: String(item.value || item.path || item.name || item.label || ''),
    })).filter((item) => item.label && item.value)
  } catch {
    templateOptions.value = []
  } finally {
    templatesLoading.value = false
  }
}

const clearArticlePrefill = async () => {
  articleForm.source_type = 'video'
  articleForm.monitor_video_id = undefined
  articleForm.video_id = ''
  articleForm.video_url = ''
  articleForm.video_title = ''
  articleForm.wechat_artifact_id = ''
  articleForm.article_source_path = ''
  articleForm.article_text = ''
  articleForm.source_url = ''
  articleForm.source_title = ''
  lastPrefillToken = ''
  const nextQuery = { ...route.query }
  delete nextQuery.sourceType
  delete nextQuery.monitorVideoId
  delete nextQuery.videoId
  delete nextQuery.videoUrl
  delete nextQuery.videoTitle
  delete nextQuery.accountName
  delete nextQuery.articleArtifact
  delete nextQuery.articlePath
  delete nextQuery.articleUrl
  delete nextQuery.articleTitle
  delete nextQuery.publishIntent
  pendingWechatPublishMode.value = ''
  pendingWechatPublishTaskId.value = ''
  pendingWechatPublishAutoSubmit.value = false
  await router.replace({ query: nextQuery })
}

const openTaskLink = async (href: string) => {
  const target = resolveApiHref(href)
  if (!isInternalApiHref(target)) {
    window.open(target, '_blank', 'noopener,noreferrer')
    return
  }
  try {
    const res = await request.get<Blob>(target, { responseType: 'blob' })
    const blobUrl = URL.createObjectURL(res.data)
    window.open(blobUrl, '_blank', 'noopener,noreferrer')
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60000)
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('aiCreation.detailLoadFailed'))
  }
}

const updateHistoryMaxHeight = () => {
  const formPanel = formPanelRef.value
  if (!formPanel) {
    historyMaxHeight.value = ''
    return
  }
  const height = Math.ceil(formPanel.getBoundingClientRect().height)
  historyMaxHeight.value = height > 0 ? `${height}px` : ''
}

const initHistoryHeightSync = () => {
  updateHistoryMaxHeight()
  if (!formPanelRef.value || !window.ResizeObserver) return
  formResizeObserver = new ResizeObserver(() => {
    updateHistoryMaxHeight()
  })
  formResizeObserver.observe(formPanelRef.value)
}

watch(currentTab, async () => {
  statusFilter.value = null
  selectedTaskId.value = ''
  selectedTask.value = null
  stopDetailPolling()
  await syncRouteTab()
  await refreshCurrentTab()
  await pickNewestTask()
  await nextTick()
  updateHistoryMaxHeight()
})

watch(
  () => route.fullPath,
  () => {
    applyRouteState()
    void maybeAutoSubmitPendingWechatPublish()
  },
)

watch(
  () => articleForm.source_type,
  (sourceType, previousSourceType) => {
    if (sourceType === previousSourceType) return
    if (sourceType === 'wechat_article') {
      clearVideoArticleFields()
    } else {
      clearWechatArticleFields()
    }
  },
)

onMounted(async () => {
  applyRouteState()
  await nextTick()
  initHistoryHeightSync()
  await loadTemplates()
  await refreshCurrentTab()
  const autoSubmitted = await maybeAutoSubmitPendingWechatPublish()
  if (!autoSubmitted) {
    const requestedTaskId = getQueryString('taskId')
    if (requestedTaskId) {
      selectedTaskId.value = requestedTaskId
      await refreshSelectedTask()
    } else {
      await pickNewestTask()
    }
  }
  await nextTick()
  updateHistoryMaxHeight()
})

onUnmounted(() => {
  stopDetailPolling()
  stopWechatPolling()
  formResizeObserver?.disconnect()
  formResizeObserver = null
})
</script>

<style scoped>
.ai-creation-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ai-creation-segment {
  display: flex;
  justify-content: flex-start;
}

.ai-creation-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.95fr);
  gap: 16px;
  align-items: start;
}

.ai-card {
  border-radius: 20px;
}

.ai-form-panel {
  min-width: 0;
}

.ai-history-card {
  display: flex;
  flex-direction: column;
  max-height: var(--ai-history-max-height, none);
  overflow: hidden;
}

.ai-history-card :deep(> .n-card__content) {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.ai-form-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ai-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
}

.ai-form-grid__wide {
  grid-column: 1 / -1;
}

.ai-action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.ai-help-text {
  color: var(--text-muted);
  font-size: 12px;
}

.prefill-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid rgba(201, 100, 66, 0.18);
  border-radius: 14px;
  background: rgba(201, 100, 66, 0.08);
  color: var(--text);
}

.history-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.history-scroll-panel {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.history-loading,
.history-empty {
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-item {
  width: 100%;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 253, 248, 0.96) 0%, rgba(250, 249, 245, 0.98) 100%);
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.task-item:hover {
  border-color: rgba(201, 100, 66, 0.28);
  box-shadow: var(--shadow-whisper);
  transform: translateY(-1px);
}

.task-item--active {
  border-color: rgba(201, 100, 66, 0.42);
  box-shadow: 0 0 0 1px rgba(201, 100, 66, 0.14), var(--shadow-whisper);
}

.task-item__top,
.task-item__bottom,
.task-item__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.task-item__title {
  min-width: 0;
  font-family: var(--font);
  font-size: 18px;
  font-weight: 500;
  line-height: 1.2;
  color: var(--text);
}

.task-item__meta,
.task-item__stage {
  margin-top: 6px;
  color: var(--text-muted);
  font-size: 12px;
}

.task-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-detail__hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(255, 253, 248, 0.96) 0%, rgba(240, 238, 230, 0.72) 100%);
}

.task-detail__eyebrow {
  color: var(--text-muted);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.task-detail__title {
  margin-top: 6px;
  font-family: var(--font);
  font-size: 24px;
  line-height: 1.2;
  color: var(--text);
}

.task-detail__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.task-progress {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
}

.task-progress__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--text);
  font-size: 13px;
}

.task-progress__track {
  height: 8px;
  margin-top: 10px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(201, 100, 66, 0.1);
}

.task-progress__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent) 0%, var(--accent-hover) 100%);
  transition: width 180ms ease;
}

.task-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.task-fact {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
}

.task-fact span {
  display: block;
  margin-bottom: 6px;
  color: var(--text-muted);
  font-size: 12px;
}

.task-fact strong {
  display: block;
  color: var(--text);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.stage-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.stage-item {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: rgba(250, 249, 245, 0.92);
}

.stage-item__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.stage-item__name {
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
}

.stage-item__message {
  margin-top: 8px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.output-file-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid rgba(201, 100, 66, 0.16);
  border-radius: 14px;
  background: rgba(250, 249, 245, 0.92);
}

.output-file-list__title {
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
}

.output-file {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.output-file__name {
  color: var(--text);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.output-file__meta {
  display: flex;
  gap: 10px;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 12px;
}

.detail-actions,
.detail-links {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.detail-error {
  padding: 12px 14px;
  border: 1px solid rgba(181, 51, 51, 0.22);
  border-radius: 14px;
  background: rgba(181, 51, 51, 0.08);
  color: var(--error);
  line-height: 1.5;
}

.detail-interrupted-banner {
  padding: 12px 14px;
  border: 1px solid rgba(173, 122, 0, 0.22);
  border-radius: 14px;
  background: rgba(173, 122, 0, 0.08);
  color: #7a5400;
  line-height: 1.5;
  font-size: 13px;
}

.wechat-publish-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px;
  border: 1px solid rgba(201, 100, 66, 0.18);
  border-radius: 14px;
  background: rgba(201, 100, 66, 0.07);
}

.wechat-publish-panel__title {
  color: var(--text);
  font-size: 14px;
  font-weight: 600;
}

.wechat-publish-panel__desc,
.wechat-publish-panel__status {
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 12px;
}

.wechat-publish-panel__error {
  margin-top: 8px;
  max-width: 760px;
  color: var(--error);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.wechat-publish-panel__diagnostics {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
  max-width: 760px;
  font-size: 12px;
}

.wechat-publish-panel__diagnostic {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: var(--text-muted);
  flex-wrap: wrap;
}

.wechat-publish-panel__diagnostic strong,
.wechat-publish-panel__diagnostic code {
  color: var(--text);
}

.wechat-publish-panel__diagnostic code {
  max-width: 100%;
  padding: 2px 5px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.58);
  overflow-wrap: anywhere;
}

.wechat-publish-panel__warning {
  padding: 8px 10px;
  border: 1px solid rgba(173, 122, 0, 0.22);
  border-radius: 10px;
  background: rgba(173, 122, 0, 0.08);
  color: #7a5400;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.wechat-publish-panel__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.detail-preview {
  margin: 0;
  padding: 14px;
  overflow: auto;
  border-radius: 16px;
  background: #f1eee5;
  color: var(--text);
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 1100px) {
  .ai-creation-grid {
    grid-template-columns: 1fr;
  }

  .task-facts,
  .stage-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .ai-form-grid,
  .task-facts,
  .stage-list {
    grid-template-columns: 1fr;
  }

  .prefill-banner,
  .task-item__top,
  .task-item__bottom,
  .task-detail__hero,
  .output-file,
  .wechat-publish-panel {
    align-items: flex-start;
    flex-direction: column;
  }

  .history-controls {
    width: 100%;
    justify-content: stretch;
  }
}
</style>
