<template>
  <div class="wechat-native-page">
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('wechatNativeCollect.title') }}</div>
        <div class="page-desc">{{ t('wechatNativeCollect.desc') }}</div>
      </div>
      <div class="page-actions">
        <NButton tertiary :loading="loadingAll" @click="loadAll">
          {{ t('wechatNativeCollect.refresh') }}
        </NButton>
      </div>
    </div>

    <div class="native-grid">
      <NCard class="native-card" :title="t('wechatNativeCollect.sessionTitle')">
        <div class="stack">
          <NAlert type="info" :bordered="false">
            {{ t('wechatNativeCollect.sessionHint') }}
          </NAlert>

          <NForm label-placement="top">
            <NFormItem :label="t('wechatNativeCollect.activeSession')">
              <NSelect
                v-model:value="selectedSessionId"
                :options="sessionOptions"
                :placeholder="t('wechatNativeCollect.selectSession')"
                filterable
                clearable
              />
            </NFormItem>
          </NForm>

          <div v-if="selectedSession" class="session-card">
            <div>
              <div class="session-name">{{ selectedSession.nickname || selectedSession.session_id }}</div>
              <div class="muted">{{ selectedSession.expires_at || '—' }}</div>
            </div>
            <NTag size="small" :bordered="false" :type="statusType(selectedSession.status)">
              {{ statusLabel(selectedSession.status) }}
            </NTag>
          </div>

          <div class="action-row">
            <NButton :loading="startingLogin" @click="startLogin">
              {{ t('wechatNativeCollect.startLogin') }}
            </NButton>
            <NButton :disabled="!selectedSessionId" :loading="checkingSession" @click="checkSelectedSession">
              {{ t('wechatNativeCollect.checkSession') }}
            </NButton>
            <NButton :disabled="!selectedSessionId" tertiary type="warning" @click="logoutSelectedSession">
              {{ t('wechatNativeCollect.logout') }}
            </NButton>
          </div>

          <div v-if="loginId" class="login-box">
            <img v-if="loginQrObjectUrl" class="qr-image" :src="loginQrObjectUrl" :alt="t('wechatNativeCollect.qrAlt')" />
            <div class="login-side">
              <div class="session-name">{{ t('wechatNativeCollect.scanQr') }}</div>
              <div class="muted">{{ loginStatus || t('wechatNativeCollect.waitingScan') }}</div>
              <div class="action-row">
                <NButton size="small" :loading="pollingLogin" @click="pollLogin">
                  {{ t('wechatNativeCollect.pollScan') }}
                </NButton>
                <NButton size="small" type="primary" :loading="confirmingLogin" @click="confirmLogin">
                  {{ t('wechatNativeCollect.confirmLogin') }}
                </NButton>
              </div>
            </div>
          </div>
        </div>
      </NCard>

      <NCard class="native-card native-source-card" :title="t('wechatNativeCollect.sourceTitle')">
        <template #header-extra>
          <NTag v-if="accounts.length" size="small" :bordered="false">
            {{ t('wechatNativeCollect.accountCount', { n: accounts.length }) }}
          </NTag>
        </template>

        <div class="stack">
          <NRadioGroup v-model:value="sourceMode" name="wechat-native-source-mode" size="large">
            <NRadioButton value="url">{{ t('wechatNativeCollect.modeUrl') }}</NRadioButton>
            <NRadioButton value="fakeid">{{ t('wechatNativeCollect.modeFakeid') }}</NRadioButton>
            <NRadioButton value="urls">{{ t('wechatNativeCollect.modeUrls') }}</NRadioButton>
          </NRadioGroup>

          <NForm :model="form" label-placement="top">
            <div class="form-grid">
              <NFormItem v-if="sourceMode === 'url'" class="wide" :label="t('wechatNativeCollect.articleUrl')">
                <NInput v-model:value="form.article_url" clearable />
              </NFormItem>

              <template v-if="sourceMode === 'fakeid'">
                <NFormItem :label="t('wechatNativeCollect.fakeid')">
                  <NInput v-model:value="form.fakeid" clearable />
                </NFormItem>
                <NFormItem :label="t('wechatNativeCollect.accountName')">
                  <NInput v-model:value="form.account_name" clearable />
                </NFormItem>
              </template>

              <NFormItem v-if="sourceMode === 'urls'" class="wide" :label="t('wechatNativeCollect.urls')">
                <NInput
                  v-model:value="form.urlsText"
                  type="textarea"
                  :autosize="{ minRows: 4, maxRows: 8 }"
                />
              </NFormItem>

              <NFormItem :label="t('wechatNativeCollect.keyword')">
                <NInput v-model:value="form.keyword" clearable />
              </NFormItem>

              <NFormItem :label="t('wechatNativeCollect.format')">
                <NSelect v-model:value="form.format" :options="formatOptions" />
              </NFormItem>

              <NFormItem :label="t('wechatNativeCollect.maxArticles')">
                <NInputNumber v-model:value="form.max_articles" :min="1" :max="1000" :show-button="false" style="width: 100%" />
              </NFormItem>

              <NFormItem :label="t('wechatNativeCollect.delaySeconds')">
                <NInputNumber v-model:value="form.delay_seconds" :min="0" :max="30" :step="0.5" :show-button="false" style="width: 100%" />
              </NFormItem>

              <NFormItem class="wide" :label="t('wechatNativeCollect.outputDir')">
                <NInput v-model:value="form.output_dir" clearable />
              </NFormItem>
            </div>
          </NForm>

          <div class="action-row">
            <NButton :loading="resolvingUrl" :disabled="!canResolveUrl" @click="resolveAccountByUrl">
              {{ t('wechatNativeCollect.resolveAccount') }}
            </NButton>
            <NButton :loading="searching" :disabled="!canSearch" @click="searchAccounts">
              {{ t('wechatNativeCollect.searchAccount') }}
            </NButton>
            <NButton :loading="previewing" :disabled="!canPreview" @click="() => previewArticles(0)">
              {{ t('wechatNativeCollect.preview') }}
            </NButton>
            <NButton type="primary" :loading="startingTask" :disabled="!canStart" @click="startCollect">
              {{ t('wechatNativeCollect.start') }}
            </NButton>
          </div>

          <div v-if="accounts.length" class="account-list account-list--bounded">
            <button
              v-for="account in accounts"
              :key="account.fakeid"
              type="button"
              class="account-item"
              @click="selectAccount(account)"
            >
              <div class="account-item__body">
                <div class="article-title">{{ account.nickname || account.fakeid }}</div>
                <div class="muted">{{ account.alias || account.fakeid }}</div>
              </div>
              <NTag class="account-item__tag" size="small" :bordered="false">fakeid</NTag>
            </button>
          </div>
        </div>
      </NCard>
    </div>

    <div class="native-workbench-grid">
      <NCard class="native-card native-preview-card" :title="t('wechatNativeCollect.previewTitle')">
        <template #header-extra>
          <div class="preview-controls">
            <NTag v-if="previewList.length" size="small" :bordered="false" type="success">
              {{ t('wechatNativeCollect.articleCount', { n: previewList.length }) }}
            </NTag>
            <div class="preview-size-control">
              <span>{{ t('wechatNativeCollect.pageSize') }}</span>
              <NSelect
                v-model:value="previewPageSize"
                class="preview-size-select"
                size="small"
                :options="previewPageSizeOptions"
                :disabled="previewing"
                @update:value="handlePreviewPageSizeChange"
              />
            </div>
          </div>
        </template>

        <div class="preview-panel">
          <div v-if="previewError" class="error-box">{{ previewError }}</div>
          <div v-if="previewAccount.fakeid" class="account-strip">
            <div>
              <div class="session-name">{{ previewAccount.nickname || previewAccount.fakeid }}</div>
              <div class="muted">{{ previewAccount.fakeid }}</div>
            </div>
          </div>

          <div class="preview-list-frame">
            <div v-if="previewList.length" class="article-list article-list--preview">
              <div
                v-for="article in previewList"
                :key="article.link || article.aid"
                class="article-item"
              >
                <div class="article-title">{{ article.title || t('wechatNativeCollect.untitled') }}</div>
                <div class="muted">
                  <span>{{ formatUnixTime(article.update_time) }}</span>
                  <span>{{ article.author_name || '—' }}</span>
                </div>
              </div>
            </div>
            <div v-else-if="!previewError" class="preview-empty-state">
              <NEmpty :description="t('wechatNativeCollect.previewEmpty')" />
            </div>
          </div>

          <div class="preview-pager">
            <NButton size="small" :disabled="previewBegin <= 0 || previewing" @click="previewPreviousPage">
              {{ t('wechatNativeCollect.prevPage') }}
            </NButton>
            <span class="muted">
              {{ t('wechatNativeCollect.pageInfo', { begin: previewRangeStart, end: previewRangeEnd, count: previewList.length }) }}
            </span>
            <NButton size="small" :disabled="!previewHasMore || previewing" @click="previewNextPage">
              {{ t('wechatNativeCollect.nextPage') }}
            </NButton>
          </div>
        </div>
      </NCard>

      <NCard class="native-card native-tasks-card" :title="t('wechatNativeCollect.tasksTitle')">
        <template #header-extra>
          <NButton tertiary size="small" :loading="loadingTasks" @click="loadTasks">
            {{ t('wechatNativeCollect.refresh') }}
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
                <strong>{{ task.account_name || task.fakeid || t('wechatNativeCollect.collectTask') }}</strong>
                <NTag size="small" :bordered="false" :type="statusType(task.status)">
                  {{ statusLabel(task.status) }}
                </NTag>
              </div>
              <div class="task-progress">
                <span>{{ task.completed || 0 }} / {{ task.total || 0 }}</span>
                <span>{{ formatDateTime(task.created_at) }}</span>
              </div>
            </button>
            <NEmpty v-if="!tasks.length" :description="t('wechatNativeCollect.tasksEmpty')" />
          </div>

          <div class="task-detail">
            <NEmpty v-if="!selectedTask" :description="t('wechatNativeCollect.selectTask')" />
            <template v-else>
              <div class="detail-head">
                <div>
                  <div class="session-name">{{ selectedTask.account_name || selectedTask.fakeid || selectedTask.task_id }}</div>
                  <div class="muted">{{ selectedTask.current || formatDateTime(selectedTask.created_at) }}</div>
                </div>
                <NButton
                  v-if="selectedTask.status === 'running'"
                  tertiary
                  type="warning"
                  :loading="cancelling"
                  @click="cancelSelected"
                >
                  {{ t('wechatNativeCollect.cancel') }}
                </NButton>
              </div>

              <div class="progress-card">
                <div class="task-progress">
                  <span>{{ selectedTask.current || '—' }}</span>
                  <span>{{ progressPercent }}%</span>
                </div>
                <div class="progress-track">
                  <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
                </div>
              </div>

              <div v-if="selectedTask.error" class="error-box">{{ selectedTask.error }}</div>

              <div class="result-list">
                <div v-for="item in selectedTask.results || []" :key="item.artifact_id || item.url" class="result-item">
                  <NTag size="small" :bordered="false" :type="item.status === 'success' ? 'success' : 'error'">
                    {{ item.status === 'success' ? t('wechatNativeCollect.success') : t('wechatNativeCollect.failed') }}
                  </NTag>
                  <div class="result-body">
                    <div class="article-title">{{ item.title || item.url }}</div>
                    <div class="muted">{{ item.artifact_name || item.error || item.url }}</div>
                  </div>
                  <NButton
                    v-if="item.status === 'success'"
                    text
                    type="primary"
                    size="small"
                    @click="openAiCreation(item)"
                  >
                    {{ t('aiCreation.articleTab') }}
                  </NButton>
                  <NButton
                    v-if="item.status === 'success'"
                    text
                    type="warning"
                    size="small"
                    @click="openWechatPublish(item)"
                  >
                    {{ t('wechatNativeCollect.publishWorkflow') }}
                  </NButton>
                </div>
              </div>
            </template>
          </div>
        </div>
      </NCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
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
import wechatNativeApi, {
  type WechatNativeConfig,
  type WechatNativeSession,
  type WechatNativeTask,
} from '@/api/wechatNativeCollect'

type SourceMode = 'url' | 'fakeid' | 'urls'

const POLL_INTERVAL_MS = 2500

const { t } = useI18n()
const router = useRouter()
const message = useMessage()

const loadingAll = ref(false)
const loadingTasks = ref(false)
const startingLogin = ref(false)
const pollingLogin = ref(false)
const confirmingLogin = ref(false)
const checkingSession = ref(false)
const resolvingUrl = ref(false)
const searching = ref(false)
const previewing = ref(false)
const startingTask = ref(false)
const cancelling = ref(false)

const config = ref<WechatNativeConfig | null>(null)
const sessions = ref<WechatNativeSession[]>([])
const selectedSessionId = ref('')
const loginId = ref('')
const loginQrObjectUrl = ref('')
const loginStatus = ref('')
const sourceMode = ref<SourceMode>('url')
const accounts = ref<Array<Record<string, any>>>([])
const previewAccount = ref<Record<string, any>>({})
const previewList = ref<Array<Record<string, any>>>([])
const previewError = ref('')
const previewBegin = ref(0)
const previewPageSize = ref(8)
const previewNextBegin = ref<number | null>(null)
const previewHasMore = ref(false)
const tasks = ref<WechatNativeTask[]>([])
const selectedTaskId = ref('')
const selectedTask = ref<WechatNativeTask | null>(null)
let taskPollTimer: number | null = null

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

const sessionOptions = computed(() => sessions.value.map((session) => ({
  label: session.nickname || session.session_id,
  value: session.session_id,
})))

const selectedSession = computed(() => (
  sessions.value.find((session) => session.session_id === selectedSessionId.value) || null
))

const formatOptions = computed(() => [
  { label: 'Markdown', value: 'markdown' },
  { label: 'HTML', value: 'html' },
  { label: 'Text', value: 'text' },
  { label: 'JSON', value: 'json' },
])

const previewPageSizeOptions = computed(() => [5, 8, 10, 15].map((value) => ({
  label: t('wechatNativeCollect.pageSizeValue', { n: value }),
  value,
})))

const parsedUrls = computed(() => form.urlsText
  .split(/\r?\n/)
  .map((item) => item.trim())
  .filter(Boolean))

const canResolveUrl = computed(() => Boolean(selectedSessionId.value && form.article_url.trim()))
const canSearch = computed(() => Boolean(selectedSessionId.value && form.keyword.trim()))
const canPreview = computed(() => (
  Boolean(selectedSessionId.value) && sourceMode.value !== 'urls' && Boolean(form.article_url.trim() || form.fakeid.trim())
))
const canStart = computed(() => {
  if (!selectedSessionId.value) return false
  if (sourceMode.value === 'urls') return parsedUrls.value.length > 0
  if (sourceMode.value === 'fakeid') return Boolean(form.fakeid.trim())
  return Boolean(form.article_url.trim())
})

const progressPercent = computed(() => {
  const total = Number(selectedTask.value?.total || 0)
  if (!total) return selectedTask.value?.status === 'done' ? 100 : 0
  return Math.min(100, Math.round((Number(selectedTask.value?.completed || 0) / total) * 100))
})

const previewRangeStart = computed(() => (previewList.value.length ? previewBegin.value + 1 : 0))
const previewRangeEnd = computed(() => previewBegin.value + previewList.value.length)

function basePayload() {
  return {
    session_id: selectedSessionId.value,
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
  const res = await wechatNativeApi.getConfig()
  config.value = res.data
  form.output_dir = form.output_dir || res.data.wechat_collection_output_dir || ''
  form.format = res.data.wechat_collection_default_format || 'markdown'
  form.max_articles = Number(res.data.wechat_collection_max_articles || 50)
  form.delay_seconds = Number(res.data.wechat_collection_delay_seconds ?? 1)
}

async function loadSessions() {
  const res = await wechatNativeApi.listSessions()
  sessions.value = Array.isArray(res.data?.sessions) ? res.data.sessions : []
  if (!selectedSessionId.value && sessions.value.length) {
    selectedSessionId.value = sessions.value[0].session_id
  }
}

async function loadTasks() {
  loadingTasks.value = true
  try {
    const res = await wechatNativeApi.listTasks()
    tasks.value = Array.isArray(res.data?.tasks) ? res.data.tasks : []
    if (selectedTaskId.value) {
      const found = tasks.value.find((task) => task.task_id === selectedTaskId.value)
      if (found) selectedTask.value = { ...selectedTask.value, ...found } as WechatNativeTask
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.tasksLoadFailed'))
  } finally {
    loadingTasks.value = false
  }
}

async function loadAll() {
  loadingAll.value = true
  try {
    await Promise.all([loadConfig(), loadSessions(), loadTasks()])
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.loadFailed'))
  } finally {
    loadingAll.value = false
  }
}

function revokeLoginQrObjectUrl() {
  if (loginQrObjectUrl.value) {
    URL.revokeObjectURL(loginQrObjectUrl.value)
    loginQrObjectUrl.value = ''
  }
}

async function loadLoginQrcode(loginIdValue: string) {
  revokeLoginQrObjectUrl()
  const res = await wechatNativeApi.getQrcodeBlob(loginIdValue)
  loginQrObjectUrl.value = URL.createObjectURL(res.data)
}

async function startLogin() {
  startingLogin.value = true
  loginStatus.value = ''
  try {
    const res = await wechatNativeApi.startLogin()
    loginId.value = String(res.data?.login_id || '')
    if (loginId.value) {
      await loadLoginQrcode(loginId.value)
    }
    message.success(t('wechatNativeCollect.loginStarted'))
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.loginFailed'))
  } finally {
    startingLogin.value = false
  }
}

async function pollLogin() {
  if (!loginId.value) return
  pollingLogin.value = true
  try {
    const res = await wechatNativeApi.scanLogin(loginId.value)
    const data = res.data || {}
    loginStatus.value = String(data.status || data.code || data.message || t('wechatNativeCollect.waitingConfirm'))
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.scanFailed'))
  } finally {
    pollingLogin.value = false
  }
}

async function confirmLogin() {
  if (!loginId.value) return
  confirmingLogin.value = true
  try {
    const res = await wechatNativeApi.confirmLogin(loginId.value)
    const sessionId = String(res.data?.session_id || res.data?.session?.session_id || '')
    if (sessionId) selectedSessionId.value = sessionId
    loginId.value = ''
    loginStatus.value = ''
    revokeLoginQrObjectUrl()
    await loadSessions()
    message.success(t('wechatNativeCollect.loginConfirmed'))
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.confirmFailed'))
  } finally {
    confirmingLogin.value = false
  }
}

async function checkSelectedSession() {
  if (!selectedSessionId.value) return
  checkingSession.value = true
  try {
    await wechatNativeApi.checkSession(selectedSessionId.value)
    await loadSessions()
    message.success(t('wechatNativeCollect.sessionOk'))
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.sessionFailed'))
  } finally {
    checkingSession.value = false
  }
}

async function logoutSelectedSession() {
  if (!selectedSessionId.value) return
  await wechatNativeApi.logoutSession(selectedSessionId.value)
  await loadSessions()
  message.success(t('wechatNativeCollect.logoutOk'))
}

async function resolveAccountByUrl() {
  if (!canResolveUrl.value) return
  resolvingUrl.value = true
  try {
    const res = await wechatNativeApi.accountByUrl({
      session_id: selectedSessionId.value,
      article_url: form.article_url.trim(),
    })
    selectAccount(res.data?.account || {})
    message.success(t('wechatNativeCollect.accountResolved'))
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.resolveFailed'))
  } finally {
    resolvingUrl.value = false
  }
}

async function searchAccounts() {
  if (!canSearch.value) return
  searching.value = true
  try {
    const res = await wechatNativeApi.searchAccounts({
      session_id: selectedSessionId.value,
      keyword: form.keyword.trim(),
      size: 10,
    })
    accounts.value = Array.isArray(res.data?.accounts) ? res.data.accounts : []
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.searchFailed'))
  } finally {
    searching.value = false
  }
}

function selectAccount(account: Record<string, any>) {
  form.fakeid = String(account.fakeid || '')
  form.account_name = String(account.nickname || account.alias || '')
  if (form.fakeid) {
    sourceMode.value = 'fakeid'
  }
}

async function previewArticles(begin = 0) {
  previewing.value = true
  previewError.value = ''
  previewAccount.value = {}
  previewList.value = []
  try {
    const maxArticles = Math.max(1, Math.min(Number(form.max_articles || 50), 1000))
    const pageSize = Math.min(normalizePreviewPageSize(previewPageSize.value), maxArticles)
    const res = await wechatNativeApi.preview({
      ...basePayload(),
      begin,
      page_size: pageSize,
      limit: pageSize,
    })
    previewAccount.value = res.data?.account || {}
    previewList.value = Array.isArray(res.data?.articles) ? res.data.articles : []
    previewBegin.value = Number(res.data?.begin ?? begin)
    previewPageSize.value = normalizePreviewPageSize(res.data?.page_size ?? pageSize)
    previewNextBegin.value = res.data?.next_begin == null ? null : Number(res.data.next_begin)
    previewHasMore.value = Boolean(res.data?.has_more)
  } catch (error: any) {
    previewBegin.value = 0
    previewNextBegin.value = null
    previewHasMore.value = false
    previewError.value = error?.response?.data?.error || error?.message || t('wechatNativeCollect.previewFailed')
  } finally {
    previewing.value = false
  }
}

function normalizePreviewPageSize(value: unknown) {
  const size = Number(value || 8)
  if (!Number.isFinite(size)) return 8
  return Math.max(1, Math.min(size, 20))
}

function handlePreviewPageSizeChange(value: number) {
  previewPageSize.value = normalizePreviewPageSize(value)
  if (previewList.value.length || previewAccount.value.fakeid) {
    void previewArticles(0)
  }
}

function previewPreviousPage() {
  const previousBegin = Math.max(0, previewBegin.value - previewPageSize.value)
  void previewArticles(previousBegin)
}

function previewNextPage() {
  if (previewNextBegin.value == null) return
  void previewArticles(previewNextBegin.value)
}

async function startCollect() {
  startingTask.value = true
  try {
    const res = await wechatNativeApi.start(basePayload())
    const taskId = String(res.data?.task_id || '')
    message.success(t('wechatNativeCollect.started'))
    await loadTasks()
    if (taskId) {
      await selectTask(taskId)
      ensureTaskPolling()
    }
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.startFailed'))
  } finally {
    startingTask.value = false
  }
}

async function selectTask(taskId: string) {
  selectedTaskId.value = taskId
  try {
    const res = await wechatNativeApi.getTask(taskId)
    selectedTask.value = res.data
    ensureTaskPolling()
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.taskLoadFailed'))
  }
}

async function pollSelectedTask() {
  if (!selectedTaskId.value) return
  try {
    const res = await wechatNativeApi.getTask(selectedTaskId.value)
    selectedTask.value = res.data
    if (!['pending', 'running'].includes(res.data.status)) {
      stopTaskPolling()
      await loadTasks()
    }
  } catch {
    stopTaskPolling()
  }
}

function ensureTaskPolling() {
  stopTaskPolling()
  if (!['pending', 'running'].includes(selectedTask.value?.status || '')) return
  taskPollTimer = window.setInterval(() => {
    void pollSelectedTask()
  }, POLL_INTERVAL_MS)
}

function stopTaskPolling() {
  if (taskPollTimer !== null) {
    window.clearInterval(taskPollTimer)
    taskPollTimer = null
  }
}

async function cancelSelected() {
  if (!selectedTaskId.value) return
  cancelling.value = true
  try {
    await wechatNativeApi.cancelTask(selectedTaskId.value)
    await pollSelectedTask()
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('wechatNativeCollect.cancelFailed'))
  } finally {
    cancelling.value = false
  }
}

function openAiCreation(item: Record<string, any>) {
  router.push({
    path: '/ai-creation',
    query: {
      tab: 'article',
      sourceType: 'wechatArticle',
      articleArtifact: String(item.artifact_id || ''),
      articlePath: String(item.path || item.artifact_url || ''),
      articleUrl: String(item.url || ''),
      articleTitle: String(item.title || ''),
    },
  })
}

function openWechatPublish(item: Record<string, any>) {
  router.push({
    path: '/ai-creation',
    query: {
      tab: 'article',
      sourceType: 'wechatArticle',
      articleArtifact: String(item.artifact_id || ''),
      articlePath: String(item.path || item.artifact_url || ''),
      articleUrl: String(item.url || ''),
      articleTitle: String(item.title || ''),
      publishIntent: 'wechatDraft',
    },
  })
}

function statusType(status: string) {
  if (status === 'active' || status === 'done') return 'success'
  if (status === 'error' || status === 'expired') return 'error'
  if (status === 'cancelled' || status === 'logged_out') return 'warning'
  return 'info'
}

function statusLabel(status: string) {
  return t(`wechatNativeCollect.status.${status}`) || status
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

onMounted(() => {
  void loadAll()
})

onUnmounted(() => {
  stopTaskPolling()
  revokeLoginQrObjectUrl()
})
</script>

<style scoped>
.wechat-native-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.native-grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.85fr) minmax(0, 1.15fr);
  gap: 16px;
  align-items: start;
}

.native-workbench-grid {
  display: grid;
  grid-template-columns: minmax(480px, 1.35fr) minmax(320px, 0.85fr);
  gap: 16px;
  align-items: stretch;
}

.native-card {
  border-radius: 20px;
}

.native-source-card {
  overflow: hidden;
}

.native-source-card :deep(.n-card__content) {
  min-height: 0;
}

.native-preview-card,
.native-tasks-card {
  min-height: clamp(540px, 68vh, 720px);
}

.native-preview-card :deep(.n-card__content),
.native-tasks-card :deep(.n-card__content) {
  height: calc(clamp(540px, 68vh, 720px) - 64px);
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: visible;
}

.stack,
.task-detail,
.login-side {
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

.preview-controls,
.preview-size-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-controls {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.preview-size-control {
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.preview-size-select {
  width: 106px;
}

.session-card,
.login-box,
.account-strip,
.task-row,
.task-progress,
.detail-head,
.result-item,
.account-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.session-card,
.account-strip,
.login-box {
  padding: 12px 14px;
  border: 1px solid rgba(201, 100, 66, 0.18);
  border-radius: 14px;
  background: rgba(201, 100, 66, 0.07);
}

.qr-image {
  width: 160px;
  height: 160px;
  flex: 0 0 auto;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface);
  object-fit: contain;
}

.session-name,
.article-title {
  color: var(--text);
  font-weight: 600;
}

.muted,
.task-progress {
  color: var(--text-muted);
  font-size: 12px;
}

.muted {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  overflow-wrap: anywhere;
}

.account-list,
.article-list,
.task-list,
.result-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.account-list--bounded {
  max-height: clamp(220px, 34vh, 390px);
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.preview-pager {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.preview-panel {
  display: flex;
  min-height: 0;
  height: 100%;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}

.preview-list-frame {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 6px;
  scrollbar-gutter: stable;
}

.article-list--preview {
  gap: 8px;
}

.article-list--preview .article-item {
  min-height: 72px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.article-list--preview .article-title {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.preview-empty-state {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.account-item,
.article-item,
.task-item,
.result-item {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.account-item,
.task-item {
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.account-item {
  min-height: 70px;
  padding: 14px;
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 253, 248, 0.96) 0%, rgba(250, 249, 245, 0.98) 100%);
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.account-item:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.account-item__body {
  min-width: 0;
}

.account-item__body .article-title,
.account-item__body .muted {
  overflow-wrap: anywhere;
}

.account-item__body .article-title {
  font-size: 16px;
  line-height: 1.2;
}

.account-item__tag {
  flex: 0 0 auto;
}

.task-item.active,
.task-item:hover,
.account-item:hover {
  border-color: rgba(201, 100, 66, 0.36);
  background: rgba(201, 100, 66, 0.07);
}

.account-item:hover {
  box-shadow: var(--shadow-whisper);
  transform: translateY(-1px);
}

.task-layout {
  display: grid;
  grid-template-columns: 1fr;
  grid-template-rows: minmax(150px, 0.78fr) minmax(0, 1.22fr);
  gap: 14px;
  min-height: 0;
  height: 100%;
}

.task-list,
.result-list {
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.task-detail {
  overflow: hidden;
}

.progress-card {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-alt);
}

.progress-track {
  height: 8px;
  margin-top: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.08);
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
  transition: width 0.2s ease;
}

.result-body {
  min-width: 0;
  flex: 1 1 auto;
}

.error-box {
  padding: 10px 12px;
  border: 1px solid rgba(208, 48, 80, 0.24);
  border-radius: 8px;
  color: #d03050;
  background: rgba(208, 48, 80, 0.08);
}

@media (max-width: 960px) {
  .native-grid,
  .native-workbench-grid,
  .task-layout {
    grid-template-columns: 1fr;
  }

  .native-preview-card,
  .native-tasks-card {
    min-height: 520px;
  }

  .native-preview-card :deep(.n-card__content),
  .native-tasks-card :deep(.n-card__content) {
    height: 456px;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .login-box,
  .account-item,
  .result-item {
    align-items: flex-start;
    flex-direction: column;
  }

  .account-list--bounded {
    max-height: 280px;
  }

  .preview-pager {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
