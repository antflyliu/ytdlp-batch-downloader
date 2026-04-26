<template>
  <div class="accounts-page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('channels.title') }}</div>
        <div class="page-desc">{{ t('channels.desc') }}</div>
      </div>
    </div>

    <!-- Top Operations -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <span class="card-title-icon">户</span>
          <span>{{ t('account.title') }}</span>
        </div>
        <div class="actions">
          <NButton type="primary" @click="openAddModal">
            {{ t('channels.addAccount') }}
          </NButton>
          <NButton :type="schedulerRunning ? 'warning' : 'success'" @click="toggleScheduler">
            {{ schedulerRunning ? t('channels.stopScheduler') : t('channels.toggleScheduler') }}
          </NButton>
          <NButton tertiary @click="reloadJobs">
            {{ t('channels.reloadJobs') }}
          </NButton>
        </div>
      </div>

      <!-- Search Filter -->
      <div class="card-account-search">
        <NInput
          v-model:value="searchQuery"
          :placeholder="t('channels.searchPlaceholder')"
          clearable
          style="max-width: 280px"
        />
        <span class="account-count">
          {{ filteredAccounts.length }} / {{ accounts.length }} {{ t('channels.title') }}
        </span>
      </div>

      <!-- Account Table -->
      <div v-if="accounts.length > 0" class="table-wrap">
        <NDataTable
          class="app-sticky-table"
          :columns="tableColumns"
          :data="filteredAccounts"
          :bordered="false"
          :virtual-scroll="true"
          :row-key="(row: Account) => row.id"
          :scroll-x="1460"
          :max-height="600"
          striped
        />
      </div>

      <!-- Empty State -->
      <div v-else class="empty-state">
        <div class="empty-state__icon">—</div>
        <div class="empty-state__title">{{ t('channels.emptyTitle') }}</div>
        <div class="empty-state__desc">{{ t('channels.emptyDesc') }}</div>
        <NButton type="primary" style="margin-top:12px" @click="openAddModal">
          {{ t('channels.addFirst') }}
        </NButton>
      </div>
    </div>

    <!-- Add/Edit Account Modal -->
    <NModal
      v-model:show="showAccountModal"
      :block-scroll="false"
      preset="card"
      :title="editingAccount ? t('account.titleEdit') : t('account.modalTitleAdd')"
      style="width: 680px"
      :mask-closable="false"
    >
      <NForm
          :model="formData"
          label-placement="left"
          label-width="140"
          require-mark-placement="right-hanging"
        >
          <!-- 基本信息 -->
          <div class="form-section">
            <div class="form-section-title">{{ t('account.title') }}</div>

            <NFormItem :label="t('account.name')" path="name" required>
              <NInput
                v-model:value="formData.name"
                :placeholder="t('account.namePlaceholder')"
              />
            </NFormItem>

            <NFormItem :label="t('account.channelUrl')" path="channel_url" required>
              <NInput
                v-model:value="formData.channel_url"
                :placeholder="t('account.channelUrlPlaceholder')"
              />
              <template #feedback>
                <span class="text-xs text-dim">{{ t('account.channelUrlHint') }}</span>
              </template>
            </NFormItem>

            <!-- API Key 选择 -->
            <NFormItem :label="t('account.apiKey')" path="api_key_id">
              <NSelect
                v-model:value="formData.api_key_id"
                :options="apiKeyOptions"
                :placeholder="t('account.selectApiKey')"
                clearable
              />
              <template #feedback>
                <span class="text-xs text-dim">{{ t('account.apiKeyHint') }}</span>
              </template>
            </NFormItem>

            <!-- 获取模式 -->
            <NFormItem :label="t('account.mode')" path="fetch_mode">
              <NSelect
                v-model:value="formData.fetch_mode"
                :options="modeOptions"
              />
            </NFormItem>

            <!-- 每次获取条数 -->
            <NFormItem :label="t('account.limit')" path="fetch_limit">
              <NInputNumber
                v-model:value="formData.fetch_limit"
                :min="1"
                :max="50"
                style="width: 120px"
              />
            </NFormItem>

            <!-- 扫描间隔 -->
            <NFormItem :label="t('account.interval')" path="scan_interval">
              <NInputNumber
                v-model:value="formData.scan_interval"
                :min="1"
                :max="1440"
                style="width: 120px"
              />
            </NFormItem>

            <!-- 启用监控 -->
            <NFormItem :label="t('account.enableMonitor')">
              <NSwitch v-model:value="formData.enabled" />
            </NFormItem>
          </div>

          <!-- 通知平台 -->
          <div class="form-section">
            <div class="form-section-title">{{ t('account.notifyPlatform') }}</div>

            <!-- 平台选择按钮 -->
            <div class="platform-selector mb-3">
              <button
                v-for="p in platforms"
                :key="p.value"
                :class="['platform-btn', { [`active-${p.value}`]: formData.notify_platform === p.value }]"
                @click="formData.notify_platform = p.value"
                type="button"
              >
                {{ p.label }}
              </button>
            </div>

            <!-- 发送通知开关 -->
            <NFormItem :label="t('account.enableNotify')">
              <NSwitch v-model:value="formData.notify_enabled" />
            </NFormItem>

            <!-- 飞书相关 -->
            <template v-if="formData.notify_platform === 'feishu'">
              <NFormItem :label="t('account.webhookUrl')">
                <NInput
                  v-model:value="formData.webhook_url"
                  :placeholder="t('account.feishuWebhook')"
                />
                <template #feedback>
                  <span class="text-xs text-dim">{{ t('account.webhookHintDefault') }}</span>
                </template>
              </NFormItem>

              <NFormItem :label="t('account.feishuMode')">
                <NSelect
                  v-model:value="formData.feishu_message_mode"
                  :options="feishuModeOptions"
                />
              </NFormItem>

              <template v-if="formData.feishu_message_mode === 'template'">
                <NFormItem :label="t('account.feishuTemplateId')">
                  <NInput
                    v-model:value="formData.feishu_template_id"
                    :placeholder="t('account.feishuTemplateIdPlaceholder')"
                  />
                </NFormItem>
                <NFormItem :label="t('account.feishuScanTemplateId')">
                  <NInput
                    v-model:value="formData.feishu_scan_template_id"
                    :placeholder="t('account.feishuScanTemplateIdPlaceholder')"
                  />
                </NFormItem>
              </template>
            </template>

            <!-- 钉钉相关 -->
            <template v-if="formData.notify_platform === 'dingtalk'">
              <NFormItem :label="t('account.webhookUrl')">
                <NInput
                  v-model:value="formData.webhook_url"
                  placeholder="https://oapi.dingtalk.com/robot/send?access_token=xxx"
                />
              </NFormItem>
              <NFormItem :label="t('account.dingtalkSecret')">
                <NInput
                  v-model:value="dingtalkSignSecretInput"
                  type="password"
                  show-password-on="click"
                  :placeholder="dingtalkSignSecretPlaceholder"
                />
                <template #feedback>
                  <span class="text-xs text-dim">{{ t('account.dingtalkSecretHint') }}</span>
                </template>
              </NFormItem>
            </template>

            <!-- 企业微信 -->
            <template v-if="formData.notify_platform === 'wecom'">
              <NFormItem :label="t('account.webhookUrl')">
                <NInput
                  v-model:value="formData.webhook_url"
                  placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
                />
              </NFormItem>
            </template>

            <!-- Telegram -->
            <template v-if="formData.notify_platform === 'telegram'">
              <NFormItem :label="t('account.botToken')">
                <NInput
                  v-model:value="telegramBotTokenInput"
                  type="password"
                  show-password-on="click"
                  :placeholder="telegramBotTokenPlaceholder"
                />
                <template #feedback>
                  <span class="text-xs text-dim">{{ t('account.webhookHintTelegram') }}</span>
                </template>
              </NFormItem>
            </template>
          </div>

          <!-- 下载网络策略 -->
          <div class="form-section">
            <div class="form-section-title">{{ t('account.downloadPolicy') }}</div>

            <NFormItem :label="t('account.enableProxy')">
              <NSwitch v-model:value="formData.proxy_enabled" />
              <template #feedback>
                <span class="text-xs text-dim" style="margin-left:8px">{{ t('account.enableProxyHint') }}</span>
              </template>
            </NFormItem>

            <NFormItem :label="t('account.proxyPool')" v-if="formData.proxy_enabled">
              <NSelect
                v-model:value="formData.proxy_pool_id"
                :options="proxyPoolOptions"
                :placeholder="t('account.proxyPoolPlaceholder')"
                clearable
              />
              <template #feedback>
                <span class="text-xs text-dim">{{ t('account.proxyPoolHint') }}</span>
              </template>
            </NFormItem>

            <NFormItem :label="t('account.downloadMode')">
              <NSelect
                v-model:value="formData.download_proxy_mode"
                :options="downloadModeOptions"
              />
              <template #feedback>
                <span class="text-xs text-dim" style="margin-left:8px">{{ t('account.downloadModeHint') }}</span>
              </template>
            </NFormItem>

            <!-- 路由预览 -->
            <div v-if="formData.id" class="routing-preview-box">
              <div class="routing-preview-title">{{ t('account.previewRouting') }}</div>
              <div class="routing-preview-main" :style="{ color: routingColor }">
                {{ routingResult?.resolved_proxy_source ? routingLabels[routingResult.resolved_proxy_source] || routingResult.resolved_proxy_source : '—' }}
              </div>
              <div v-if="routingResult?.reason" class="routing-preview-reason">
                {{ routingResult.reason }}
              </div>
              <NButton size="small" tertiary @click="previewRouting" :loading="routingLoading">
                {{ t('account.btnDetail') }}
              </NButton>
            </div>
          </div>
        </NForm>

      <template #footer>
        <div style="display:flex; justify-content:flex-end; gap:8px">
          <NButton @click="showAccountModal = false">
            {{ t('common.cancel') }}
          </NButton>
          <NButton type="primary" @click="saveAccount" :loading="saving">
            {{ t('common.submit') }}
          </NButton>
        </div>
      </template>
    </NModal>

    <!-- Account Video Detail Modal -->
    <NModal
      v-model:show="showDetailModal"
      :block-scroll="false"
      preset="card"
      :title="t('videoDetail.title')"
      class="video-detail-modal"
      style="width: min(1180px, 96vw)"
      :mask-closable="false"
    >
      <div class="video-detail">
        <div class="video-detail__header">
          <div class="video-detail__identity">
            <div class="video-detail__eyebrow">{{ t('videoDetail.monitorAccount') }}</div>
            <div class="video-detail__account">{{ detailAccount?.name || '—' }}</div>
            <div class="video-detail__channel">{{ detailAccount?.channel_url || '—' }}</div>
          </div>
          <div class="video-detail__actions">
            <NTag size="small" :bordered="false">
              {{ t('video.totalVideos', { n: detailTotal }) }}
            </NTag>
            <NCheckbox v-model:checked="detailDownloadSubtitles">
              {{ detailDownloadSubtitles ? t('video.subtitleOn') : t('video.subtitleOff') }}
            </NCheckbox>
            <NButton
              type="primary"
              :disabled="detailSelectedRowKeys.length === 0"
              :loading="detailDownloading"
              @click="batchDownloadSelected"
            >
              {{ t('video.btnDownloadSelected', { n: detailSelectedRowKeys.length }) }}
            </NButton>
          </div>
        </div>

        <div class="video-detail__filters">
          <NInput
            v-model:value="detailFilters.title_kw"
            :placeholder="t('videoDetail.searchTitle')"
            clearable
            @keyup.enter="searchDetailVideos"
          />
          <NInput
            v-model:value="detailFilters.url_kw"
            :placeholder="t('videoDetail.searchUrl')"
            clearable
            @keyup.enter="searchDetailVideos"
          />
          <NSelect
            v-model:value="detailFilters.status"
            :options="detailStatusOptions"
            :placeholder="t('videoDetail.allStatus')"
          />
          <NSelect
            v-model:value="detailFilters.sort_by"
            :options="detailSortOptions"
          />
          <NSelect
            v-model:value="detailFilters.sort_dir"
            :options="detailSortDirOptions"
          />
          <NButton type="primary" tertiary @click="searchDetailVideos">
            {{ t('videoDetail.search') }}
          </NButton>
          <NButton tertiary @click="resetDetailFilters">
            {{ t('videoDetail.reset') }}
          </NButton>
          <NButton
            v-if="detailFilters.status === 'failed'"
            tertiary
            type="warning"
            :loading="detailRetrying"
            :disabled="detailFailedCount === 0"
            @click="retryFailedVideos"
          >
            {{ t('video.retryCount', { n: detailFailedCount }) }}
          </NButton>
        </div>

        <div v-if="detailDownloadTask" class="detail-progress">
          <div class="detail-progress__top">
            <span>{{ detailDownloadStatusText }}</span>
            <span>{{ detailDownloadPercent }}%</span>
          </div>
          <div class="detail-progress__track">
            <div class="detail-progress__fill" :style="{ width: `${detailDownloadPercent}%` }"></div>
          </div>
          <div v-if="detailDownloadTask.current_video" class="detail-progress__current">
            {{ detailDownloadTask.current_video }}
          </div>
        </div>

        <NDataTable
          :columns="detailColumns"
          :data="detailRows"
          :loading="detailLoading"
          :bordered="false"
          :row-key="(row: AccountVideo) => row.id"
          :checked-row-keys="detailSelectedRowKeys"
          :pagination="false"
          :scroll-x="1180"
          :max-height="520"
          striped
          remote
          @update:checked-row-keys="handleDetailCheckedRowKeys"
        />

        <div class="video-detail__footer">
          <span class="video-detail__selected">
            {{ t('videoDetail.selectedCount', { n: detailSelectedRowKeys.length }) }}
          </span>
          <NPagination
            v-if="!detailFilters.status"
            :page="detailPage"
            :page-size="detailPageSize"
            :item-count="detailTotal"
            :page-sizes="[20, 50, 100]"
            show-size-picker
            @update:page="handleDetailPageChange"
            @update:page-size="handleDetailPageSizeChange"
          />
          <span v-else class="video-detail__status-page-hint">
            {{ t('videoDetail.statusFilterPageHint') }}
          </span>
        </div>
      </div>
    </NModal>

    <!-- Scan Confirm Modal -->
    <NModal
      v-model:show="showScanModal"
      :block-scroll="false"
      preset="dialog"
      :title="t('scanConfirm.title')"
      positive-text=""
      negative-text=""
    >
      <div class="scan-confirm-content">
        <p>{{ t('scanConfirm.confirmMsg') }}</p>
        <NCheckbox v-model:checked="scanAutoDownload">
          {{ t('scanConfirm.autoDl') }}
        </NCheckbox>
        <div class="text-xs text-dim" style="margin-top:4px">{{ t('scanConfirm.autoDlHint') }}</div>
      </div>
      <template #action>
        <NButton @click="showScanModal = false">{{ t('common.cancel') }}</NButton>
        <NButton type="primary" @click="confirmScanNow" :loading="scanning">
          {{ t('scanConfirm.startScan') }}
        </NButton>
      </template>
    </NModal>

    <!-- Delete Confirm -->
    <NModal
      v-model:show="showDeleteModal"
      :block-scroll="false"
      preset="dialog"
      :title="t('account.deleteConfirmTitle')"
      positive-text=""
      negative-text=""
    >
      <p>{{ t('account.deleteConfirmMsg') }}</p>
      <template #action>
        <NButton @click="showDeleteModal = false">{{ t('common.cancel') }}</NButton>
        <NButton type="error" @click="confirmDelete" :loading="deleting">
          {{ t('account.btnDelete') }}
        </NButton>
      </template>
    </NModal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, h, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  NButton,
  NDataTable,
  NInput,
  NSelect,
  NInputNumber,
  NSwitch,
  NModal,
  NForm,
  NFormItem,
  NTag,
  NIcon,
  NCheckbox,
  NPagination,
  useMessage,
} from 'naive-ui'
import type { DataTableColumn } from 'naive-ui'
import accountsApi from '@/api/accounts'
import clipsApi from '@/api/clips'

const { t } = useI18n()
const router = useRouter()
const message = useMessage()

const MASKED_SECRET_VALUE = '***'

// ── Types ──────────────────────────────────────────────────────────────
interface Account {
  id: number
  name: string
  channel_url: string
  api_key_id: number | null
  fetch_mode: string
  fetch_limit: number
  scan_interval: number
  enabled: boolean
  notify_enabled: boolean
  notify_platform: string
  proxy_enabled: boolean
  proxy_pool_id: number | null
  download_proxy_mode: string
  webhook_url?: string
  telegram_bot_token?: string
  dingtalk_sign_secret?: string
  feishu_message_mode?: string
  feishu_template_id?: string
  feishu_scan_template_id?: string
  status?: string
}

interface ProxyPool {
  id: number
  name: string
  enabled: boolean
}

interface ApiKey {
  id: number
  name: string
  key_value: string
}

interface RoutingResult {
  resolved_proxy_source: string
  reason?: string
  provider_name?: string
  provider_tier?: string
  session_mode?: string
  masked_proxy_endpoint?: string
  fallback_depth?: number
  warnings?: string[]
}

interface AccountVideo {
  id: number
  video_id?: string
  title?: string
  description?: string
  url?: string
  published_at?: string
  upload_date?: string
  duration_sec?: number | null
  view_count?: number | null
  like_count?: number | null
  comment_count?: number | null
  download_status?: string
  retry_count?: number | null
  failed_reason?: string | null
  failed_at?: string | null
}

interface DownloadTask {
  task_id: string
  status: string
  total: number
  completed: number
  success: number
  failed: number
  current_video?: string
  error?: string | null
}

// ── State ───────────────────────────────────────────────────────────────
const accounts = ref<Account[]>([])
const apiKeys = ref<ApiKey[]>([])
const proxyPools = ref<ProxyPool[]>([])
const schedulerRunning = ref(false)

const searchQuery = ref('')
const showAccountModal = ref(false)
const showScanModal = ref(false)
const showDeleteModal = ref(false)
const showDetailModal = ref(false)

const editingAccount = ref<Account | null>(null)
const deletingAccountId = ref<number | null>(null)
const detailAccount = ref<Account | null>(null)

const saving = ref(false)
const scanning = ref(false)
const deleting = ref(false)
const routingLoading = ref(false)
const detailLoading = ref(false)
const detailDownloading = ref(false)
const detailRetrying = ref(false)
const scanAutoDownload = ref(true)

const routingResult = ref<RoutingResult | null>(null)
const routingColor = ref('inherit')
const detailRows = ref<AccountVideo[]>([])
const detailTotal = ref(0)
const detailPage = ref(1)
const detailPageSize = ref(20)
const detailSelectedRowKeys = ref<number[]>([])
const detailDownloadSubtitles = ref(false)
const detailDownloadTask = ref<DownloadTask | null>(null)
const detailClippingVideoIds = ref<number[]>([])
const detailFilters = ref({
  title_kw: '',
  url_kw: '',
  status: '',
  sort_by: 'published_at',
  sort_dir: 'desc',
})

let detailDownloadPollTimer: number | null = null

// Default form data
const defaultFormData = (): Account => ({
  id: 0,
  name: '',
  channel_url: '',
  api_key_id: null,
  fetch_mode: 'playlist',
  fetch_limit: 5,
  scan_interval: 5,
  enabled: true,
  notify_enabled: true,
  notify_platform: 'feishu',
  proxy_enabled: false,
  proxy_pool_id: null,
  download_proxy_mode: 'auto',
  webhook_url: '',
  telegram_bot_token: '',
  dingtalk_sign_secret: '',
  feishu_message_mode: 'card_json',
  feishu_template_id: '',
  feishu_scan_template_id: '',
})

const formData = ref<Account>(defaultFormData())
const telegramBotTokenInput = ref('')
const dingtalkSignSecretInput = ref('')
const hasSavedTelegramBotToken = ref(false)
const hasSavedDingtalkSignSecret = ref(false)

// ── Options ─────────────────────────────────────────────────────────────
const platforms = computed(() => [
  { value: 'feishu', label: t('account.platFeishu') },
  { value: 'dingtalk', label: t('account.platDingtalk') },
  { value: 'telegram', label: t('account.platTelegram') },
  { value: 'wecom', label: t('account.platWecom') },
])

const modeOptions = computed(() => [
  { value: 'playlist', label: t('account.modePlaylist') },
  { value: 'search', label: t('account.modeSearch') },
])

const feishuModeOptions = computed(() => [
  { value: 'card_json', label: t('account.feishuModeCard') },
  { value: 'template', label: t('account.feishuModeTemplate') },
])

const downloadModeOptions = computed(() => [
  { value: 'auto', label: t('account.downloadModeAuto') },
  { value: 'account_only', label: t('account.downloadModeAccountOnly') },
  { value: 'system_only', label: t('account.downloadModeSystemOnly') },
  { value: 'direct_only', label: t('account.downloadModeDirectOnly') },
])

const detailStatusOptions = computed(() => [
  { value: '', label: t('videoDetail.allStatus') },
  { value: 'downloaded', label: t('video.tagDownloaded') },
  { value: 'downloading', label: t('video.tagDownloading') },
  { value: 'failed', label: t('video.tagFailed') },
  { value: 'pending', label: t('video.tagPending') },
])

const detailSortOptions = computed(() => [
  { value: 'published_at', label: t('videoDetail.pubTime') },
  { value: 'view_count', label: t('videoDetail.viewCount') },
  { value: 'like_count', label: t('videoDetail.likeCount') },
  { value: 'comment_count', label: t('videoDetail.commentCount') },
])

const detailSortDirOptions = computed(() => [
  { value: 'desc', label: t('videoDetail.desc') },
  { value: 'asc', label: t('videoDetail.asc') },
])

const apiKeyOptions = computed(() =>
  apiKeys.value.map(k => ({ label: `${k.name} (${k.key_value})`, value: k.id }))
)

const telegramBotTokenPlaceholder = computed(() => (
  hasSavedTelegramBotToken.value
    ? t('settings.secretSavedPlaceholder')
    : t('account.botTokenPlaceholder')
))

const dingtalkSignSecretPlaceholder = computed(() => (
  hasSavedDingtalkSignSecret.value
    ? t('settings.secretSavedPlaceholder')
    : t('account.dingtalkSecretPlaceholder')
))

const resetSecretInputs = () => {
  telegramBotTokenInput.value = ''
  dingtalkSignSecretInput.value = ''
  hasSavedTelegramBotToken.value = false
  hasSavedDingtalkSignSecret.value = false
}

const syncSecretInputsFromAccount = (account: Account) => {
  const loadedTelegramToken = account.telegram_bot_token || ''
  hasSavedTelegramBotToken.value = loadedTelegramToken === MASKED_SECRET_VALUE
  telegramBotTokenInput.value = hasSavedTelegramBotToken.value ? '' : loadedTelegramToken
  formData.value.telegram_bot_token = hasSavedTelegramBotToken.value
    ? MASKED_SECRET_VALUE
    : loadedTelegramToken

  const loadedDingtalkSecret = account.dingtalk_sign_secret || ''
  hasSavedDingtalkSignSecret.value = loadedDingtalkSecret === MASKED_SECRET_VALUE
  dingtalkSignSecretInput.value = hasSavedDingtalkSignSecret.value ? '' : loadedDingtalkSecret
  formData.value.dingtalk_sign_secret = hasSavedDingtalkSignSecret.value
    ? MASKED_SECRET_VALUE
    : loadedDingtalkSecret
}

const buildAccountPayload = (): Partial<Account> => {
  const data: Partial<Account> = {
    ...formData.value,
  }

  delete data.status
  delete data.webhook_url
  delete data.telegram_bot_token
  delete data.dingtalk_sign_secret
  delete data.feishu_template_id
  delete data.feishu_scan_template_id

  const platform = formData.value.notify_platform

  if (platform === 'telegram') {
    const token = telegramBotTokenInput.value.trim()
    if (token) data.telegram_bot_token = token
  } else if (platform === 'dingtalk') {
    data.webhook_url = formData.value.webhook_url || ''
    const signSecret = dingtalkSignSecretInput.value.trim()
    if (signSecret) data.dingtalk_sign_secret = signSecret
  } else if (platform === 'feishu') {
    data.webhook_url = formData.value.webhook_url || ''
    if (formData.value.feishu_message_mode === 'template') {
      data.feishu_template_id = formData.value.feishu_template_id || ''
      data.feishu_scan_template_id = formData.value.feishu_scan_template_id || ''
    }
  } else if (platform === 'wecom') {
    data.webhook_url = formData.value.webhook_url || ''
  }

  if (!data.proxy_enabled) {
    data.proxy_pool_id = null
  }

  return data
}

const proxyPoolOptions = computed(() =>
  proxyPools.value.map(p => ({
    label: p.enabled ? p.name : `${p.name} (${t('account.proxyDisabledTag')})`,
    value: p.id,
  }))
)

const routingLabels: Record<string, string> = {
  account_static: t('account.routingAccountStatic'),
  system_paid: t('account.routingSystemPaid'),
  system_free: t('account.routingSystemFree'),
  direct: t('account.routingDirect'),
  failed: t('account.routingFailed'),
}

// ── Computed ────────────────────────────────────────────────────────────
const filteredAccounts = computed(() => {
  if (!searchQuery.value) return accounts.value
  const q = searchQuery.value.toLowerCase()
  return accounts.value.filter(a =>
    a.name.toLowerCase().includes(q) || a.channel_url.toLowerCase().includes(q)
  )
})

const detailFailedCount = computed(() =>
  detailRows.value.filter(v => v.download_status === 'failed').length
)

const detailDownloadPercent = computed(() => {
  const task = detailDownloadTask.value
  if (!task || !task.total) return 0
  return Math.min(100, Math.round((task.completed / task.total) * 100))
})

const detailDownloadStatusText = computed(() => {
  const task = detailDownloadTask.value
  if (!task) return ''
  const doneText = `${task.completed}/${task.total}`
  if (task.status === 'done') return `${t('video.downlCompleteStatus')} ${doneText}`
  if (task.status === 'error') return `${t('video.downloadErrorStatus')} ${doneText}`
  return `${t('video.downloadingStatus')} ${doneText}`
})

// ── Table Columns ───────────────────────────────────────────────────────
const statusColor = (status?: string) => {
  switch (status) {
    case 'active': return 'success'
    case 'disabled': return 'default'
    case 'error': return 'error'
    default: return 'default'
  }
}

const statusLabel = (status?: string) => {
  switch (status) {
    case 'active': return t('account.statusActive')
    case 'disabled': return t('account.statusDisabled')
    case 'error': return t('account.statusError')
    default: return t('account.statusInactive')
  }
}

const modeLabel = (mode: string) => mode === 'playlist' ? t('account.modePlaylist') : t('account.modeSearch')

const intervalLabel = (interval: number) => `${interval}m`

const tableColumns: DataTableColumn<Account>[] = [
  { title: t('channels.tableId'), key: 'id', width: 60 },
  { title: t('channels.tableName'), key: 'name', width: 140, ellipsis: true },
  { title: t('channels.tableChannelUrl'), key: 'channel_url', width: 200, ellipsis: true },
  {
    title: t('channels.tableApiKey'),
    key: 'api_key_id',
    width: 120,
    ellipsis: true,
    render: (row) => {
      const key = apiKeys.value.find(k => k.id === row.api_key_id)
      return key ? key.name : t('account.apiKeyDefault')
    }
  },
  {
    title: t('channels.tableMode'),
    key: 'fetch_mode',
    width: 130,
    render: (row) => modeLabel(row.fetch_mode)
  },
  {
    title: t('channels.tableInterval'),
    key: 'scan_interval',
    width: 80,
    render: (row) => intervalLabel(row.scan_interval)
  },
  { title: t('channels.tableFetch'), key: 'fetch_limit', width: 70 },
  {
    title: t('channels.tableStatus'),
    key: 'status',
    width: 90,
    render: (row) => h(NTag, { type: statusColor(row.status), size: 'small' }, () => statusLabel(row.status))
  },
  {
    title: t('channels.tableNotify'),
    key: 'notify_enabled',
    width: 90,
    render: (row) => h(NTag, {
      type: row.notify_enabled ? 'success' : 'default',
      size: 'small',
      bordered: false
    }, () => row.notify_enabled ? t('account.notifyOn') : t('account.notifySilent'))
  },
  {
    title: t('channels.tableProxy'),
    key: 'proxy_pool_id',
    width: 100,
    render: (row) => row.proxy_enabled && row.proxy_pool_id
      ? h(NTag, { type: 'success', size: 'small', bordered: false }, () => t('account.proxyEnabled'))
      : h(NTag, { type: 'default', size: 'small', bordered: false }, () => t('account.proxyNone'))
  },
  {
    title: t('channels.tableActions'),
    key: 'actions',
    width: 292,
    fixed: 'right',
    render: (row) => h('div', { class: 'account-row-actions' }, [
      h(NButton, {
        size: 'small',
        tertiary: true,
        class: 'account-detail-action',
        title: t('account.btnDetail'),
        onClick: () => openDetailModal(row)
      }, () => t('account.btnDetail')),
      h(NButton, {
        size: 'small',
        tertiary: true,
        type: 'info',
        onClick: () => triggerScan(row.id)
      }, () => t('account.scanNow')),
      h(NButton, {
        size: 'small',
        tertiary: true,
        onClick: () => openEditModal(row)
      }, () => t('account.btnEdit')),
      h(NButton, {
        size: 'small',
        tertiary: true,
        type: 'error',
        onClick: () => openDeleteConfirm(row.id)
      }, () => t('account.btnDelete')),
    ])
  },
]

const isHttpUrl = (url?: string) => /^https?:\/\//i.test(url || '')

const formatDate = (value?: string) => value ? value.slice(0, 10) : '—'

const formatNumber = (value?: number | null) => {
  if (value === null || value === undefined) return '—'
  return Number(value).toLocaleString()
}

const formatDuration = (seconds?: number | null) => {
  if (!seconds || seconds <= 0) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

const videoStatusLabel = (status?: string) => {
  switch (status) {
    case 'downloaded': return t('video.tagDownloaded')
    case 'downloading':
    case 'running': return t('video.tagDownloading')
    case 'failed': return t('video.tagFailed')
    default: return t('video.tagPending')
  }
}

const videoStatusType = (status?: string) => {
  switch (status) {
    case 'downloaded': return 'success'
    case 'downloading':
    case 'running': return 'info'
    case 'failed': return 'error'
    default: return 'warning'
  }
}

const routingSourceLabel = (source?: string) => {
  switch (source) {
    case 'account_static': return t('video.routingAccountStatic')
    case 'system_paid': return t('video.routingSystemPaid')
    case 'system_free': return t('video.routingSystemFree')
    case 'direct': return t('video.routingDirect')
    case 'failed': return t('video.routingFailed')
    default: return source || t('video.routingUnknown')
  }
}

const openVideoUrl = (row: AccountVideo) => {
  if (!isHttpUrl(row.url)) {
    message.warning(t('videoDetail.invalidUrl'))
    return
  }
  window.open(row.url, '_blank', 'noopener,noreferrer')
}

const canClipVideo = (row: AccountVideo) => row.download_status === 'downloaded'

const isVideoClipping = (videoId: number) => detailClippingVideoIds.value.includes(videoId)

const setVideoClipping = (videoId: number, clipping: boolean) => {
  detailClippingVideoIds.value = clipping
    ? Array.from(new Set([...detailClippingVideoIds.value, videoId]))
    : detailClippingVideoIds.value.filter(id => id !== videoId)
}

const triggerVideoClip = async (row: AccountVideo) => {
  if (!canClipVideo(row)) {
    message.warning(t('videoDetail.clipRequiresDownloaded'))
    return
  }

  setVideoClipping(row.id, true)
  try {
    const res = await clipsApi.create(row.id)
    const body = res.data || {}
    if (body.error || body.ok === false) {
      message.error(body.error || t('clip.createFailed'))
      return
    }
    message.success(t('clip.taskCreated', { id: body.task_id ?? '' }))
    showDetailModal.value = false
    void router.push('/clip-history')
  } catch (e: any) {
    const errorMsg = e?.response?.data?.error || e?.message || t('clip.createFailed')
    message.error(errorMsg)
  } finally {
    setVideoClipping(row.id, false)
  }
}

const detailColumns = computed<DataTableColumn<AccountVideo>[]>(() => [
  { type: 'selection', width: 52 },
  {
    title: t('videoDetail.titleCol'),
    key: 'title',
    minWidth: 320,
    ellipsis: true,
    render: (row) => h('div', { class: 'video-title-cell' }, [
      h('button', {
        type: 'button',
        class: 'video-title-button',
        title: row.title || '',
        onClick: () => openVideoUrl(row),
      }, row.title || '—'),
      h('div', { class: 'video-url-line', title: row.url || '' }, row.url || '—'),
    ])
  },
  {
    title: t('videoDetail.pubTimeCol'),
    key: 'published_at',
    width: 100,
    render: (row) => formatDate(row.published_at)
  },
  {
    title: t('videoDetail.duration'),
    key: 'duration_sec',
    width: 90,
    render: (row) => formatDuration(row.duration_sec)
  },
  {
    title: t('videoDetail.views'),
    key: 'view_count',
    width: 100,
    align: 'right',
    render: (row) => formatNumber(row.view_count)
  },
  {
    title: t('videoDetail.likes'),
    key: 'like_count',
    width: 90,
    align: 'right',
    render: (row) => formatNumber(row.like_count)
  },
  {
    title: t('videoDetail.comments'),
    key: 'comment_count',
    width: 90,
    align: 'right',
    render: (row) => formatNumber(row.comment_count)
  },
  {
    title: t('videoDetail.dlStatus'),
    key: 'download_status',
    width: 110,
    render: (row) => h(NTag, {
      type: videoStatusType(row.download_status),
      size: 'small',
      bordered: false,
    }, () => videoStatusLabel(row.download_status))
  },
  {
    title: t('videoDetail.actions'),
    key: 'actions',
    width: 148,
    fixed: 'right',
    render: (row) => h('div', { class: 'video-row-actions' }, [
      h(NButton, {
        size: 'small',
        tertiary: true,
        class: 'video-open-action',
        disabled: !isHttpUrl(row.url),
        onClick: () => openVideoUrl(row)
      }, () => t('videoDetail.open')),
      h(NButton, {
        size: 'small',
        tertiary: true,
        type: 'primary',
        class: 'video-clip-action',
        title: canClipVideo(row) ? t('video.clipTrigger') : t('videoDetail.clipRequiresDownloaded'),
        disabled: !canClipVideo(row) || isVideoClipping(row.id),
        loading: isVideoClipping(row.id),
        onClick: () => triggerVideoClip(row)
      }, () => t('videoDetail.clip'))
    ])
  },
])

// ── Methods ─────────────────────────────────────────────────────────────
const loadAccounts = async () => {
  try {
    const res = await accountsApi.list()
    accounts.value = res.data || []
  } catch (e) {
    message.error(t('account.loadFailed'))
  }
}

const loadApiKeys = async () => {
  try {
    const res = await accountsApi.listApiKeys()
    apiKeys.value = res.data || []
  } catch (e) {
    // ignore
  }
}

const loadProxyPools = async () => {
  try {
    const res = await accountsApi.listProxyPools()
    proxyPools.value = res.data || []
  } catch (e) {
    // ignore
  }
}

const openAddModal = async () => {
  editingAccount.value = null
  formData.value = defaultFormData()
  resetSecretInputs()
  await loadApiKeys()
  await loadProxyPools()
  showAccountModal.value = true
}

const openEditModal = async (account: Account) => {
  editingAccount.value = account
  formData.value = { ...defaultFormData(), ...account }
  syncSecretInputsFromAccount(account)
  await loadApiKeys()
  await loadProxyPools()
  routingResult.value = null
  showAccountModal.value = true
}

const loadAccountVideos = async () => {
  if (!detailAccount.value) return
  detailLoading.value = true
  try {
    const params = {
      title_kw: detailFilters.value.title_kw.trim(),
      url_kw: detailFilters.value.url_kw.trim(),
      status: detailFilters.value.status || undefined,
      sort_by: detailFilters.value.sort_by,
      sort_dir: detailFilters.value.sort_dir,
      page: detailPage.value,
      page_size: detailPageSize.value,
    }
    const res = await accountsApi.videos(detailAccount.value.id, params)
    const body = res.data || {}
    detailRows.value = Array.isArray(body.videos) ? body.videos : []
    detailTotal.value = Number(body.total || 0)
    detailPage.value = Number(body.page || detailPage.value || 1)
  } catch (e: any) {
    const errorMsg = e?.response?.data?.error || e?.message || t('video.loadFailed')
    message.error(errorMsg)
    detailRows.value = []
    detailTotal.value = 0
  } finally {
    detailLoading.value = false
  }
}

const openDetailModal = async (account: Account) => {
  detailAccount.value = account
  detailPage.value = 1
  detailPageSize.value = 20
  detailSelectedRowKeys.value = []
  detailDownloadSubtitles.value = false
  detailDownloadTask.value = null
  detailClippingVideoIds.value = []
  detailFilters.value = {
    title_kw: '',
    url_kw: '',
    status: '',
    sort_by: 'published_at',
    sort_dir: 'desc',
  }
  showDetailModal.value = true
  await loadAccountVideos()
}

const searchDetailVideos = async () => {
  detailPage.value = 1
  await loadAccountVideos()
}

const resetDetailFilters = async () => {
  detailFilters.value = {
    title_kw: '',
    url_kw: '',
    status: '',
    sort_by: 'published_at',
    sort_dir: 'desc',
  }
  detailPage.value = 1
  await loadAccountVideos()
}

const handleDetailCheckedRowKeys = (keys: Array<string | number>) => {
  detailSelectedRowKeys.value = keys
    .map(key => Number(key))
    .filter(key => Number.isInteger(key) && key > 0)
}

const handleDetailPageChange = async (page: number) => {
  detailPage.value = page
  await loadAccountVideos()
}

const handleDetailPageSizeChange = async (pageSize: number) => {
  detailPageSize.value = pageSize
  detailPage.value = 1
  await loadAccountVideos()
}

const stopDetailDownloadPolling = () => {
  if (detailDownloadPollTimer !== null) {
    window.clearInterval(detailDownloadPollTimer)
    detailDownloadPollTimer = null
  }
}

const pollDetailDownloadTask = async (taskId: string) => {
  try {
    const res = await accountsApi.downloadTask(taskId)
    const task = res.data as DownloadTask
    if (!task || (task as any).error) {
      if ((task as any)?.error) message.error((task as any).error)
      stopDetailDownloadPolling()
      return
    }
    detailDownloadTask.value = task
    if (task.status === 'done' || task.status === 'error') {
      stopDetailDownloadPolling()
      if (task.status === 'done') {
        message.success(t('video.batchDone'))
      } else {
        message.error(task.error || t('video.downloadError'))
      }
      await loadAccountVideos()
    }
  } catch {
    // Keep polling through transient network errors.
  }
}

const startDetailDownloadPolling = (taskId: string) => {
  stopDetailDownloadPolling()
  void pollDetailDownloadTask(taskId)
  detailDownloadPollTimer = window.setInterval(() => {
    void pollDetailDownloadTask(taskId)
  }, 3000)
}

const showDetailRoutingToast = (routing?: { source?: string; provider?: string; warnings?: string[] }) => {
  if (!routing) return
  let routingMsg = t('video.routingCurrent', { s: routingSourceLabel(routing.source) })
  if (routing.provider) routingMsg += ` | ${routing.provider}`
  if (routing.warnings?.length) routingMsg += ` | ${t('video.routingWarning')} ${routing.warnings.join(', ')}`
  if (routing.source === 'direct' || routing.source === 'failed') message.warning(routingMsg)
  else message.info(routingMsg)
}

const batchDownloadSelected = async () => {
  if (!detailAccount.value) return
  const videoIds = detailSelectedRowKeys.value
    .map(id => Number(id))
    .filter(id => Number.isInteger(id) && id > 0)
  if (!videoIds.length) {
    message.warning(t('videoDetail.noSelection'))
    return
  }

  detailDownloading.value = true
  try {
    const payload: Record<string, unknown> = {
      video_ids: videoIds,
      no_subs: !detailDownloadSubtitles.value,
    }
    if (detailDownloadSubtitles.value) payload.sub_langs = 'zh-Hans,en'
    const res = await accountsApi.batchDownloadVideos(detailAccount.value.id, payload)
    const body = res.data || {}
    if (body.error || body.ok === false) {
      message.error(body.error || t('video.downloadFailed'))
      return
    }
    const queued = Number(body.queued || videoIds.length)
    message.success(t('video.videosQueued', { n: queued }))
    showDetailRoutingToast(body.routing)
    detailSelectedRowKeys.value = []
    if (body.task_id) {
      detailDownloadTask.value = {
        task_id: body.task_id,
        status: 'running',
        total: queued,
        completed: 0,
        success: 0,
        failed: 0,
      }
      startDetailDownloadPolling(body.task_id)
    }
    await loadAccountVideos()
  } catch (e: any) {
    const errorMsg = e?.response?.data?.error || e?.message || t('video.downloadFailed')
    message.error(errorMsg)
  } finally {
    detailDownloading.value = false
  }
}

const retryFailedVideos = async () => {
  if (!detailAccount.value) return
  const failedIds = detailRows.value
    .filter(v => v.download_status === 'failed')
    .map(v => v.id)
  if (!failedIds.length) {
    message.warning(t('video.noRetryable'))
    return
  }

  detailRetrying.value = true
  try {
    const res = await accountsApi.retryVideos(detailAccount.value.id, failedIds)
    const body = res.data || {}
    if (body.error || body.ok === false) {
      message.error(body.error || t('video.retryFailed'))
      return
    }
    message.success(t('video.retryDone', { n: body.retried || failedIds.length }))
    detailSelectedRowKeys.value = []
    detailPage.value = 1
    await loadAccountVideos()
  } catch (e: any) {
    const errorMsg = e?.response?.data?.error || e?.message || t('video.retryRequestFailed', { e: '' })
    message.error(errorMsg)
  } finally {
    detailRetrying.value = false
  }
}

const saveAccount = async () => {
  if (!formData.value.name || !formData.value.channel_url) {
    message.error(t('account.nameAndUrlRequired'))
    return
  }
  if (formData.value.download_proxy_mode === 'account_only' && (!formData.value.proxy_enabled || !formData.value.proxy_pool_id)) {
    message.error(t('account.accountOnlyProxyMustEnable'))
    return
  }
  saving.value = true
  try {
    const data = buildAccountPayload()
    let res
    if (editingAccount.value) {
      res = await accountsApi.update(formData.value.id, data)
    } else {
      res = await accountsApi.create(data)
    }
    const body = res.data as { code?: number; message?: string } | undefined
    if (body?.code === 0) {
      message.error(body.message || t('account.networkError'))
    } else {
      message.success(editingAccount.value ? t('account.editSuccess') : t('account.addSuccess'))
      showAccountModal.value = false
      await loadAccounts()
    }
  } catch (e) {
    message.error(t('account.networkError'))
  } finally {
    saving.value = false
  }
}

const openDeleteConfirm = (id: number) => {
  deletingAccountId.value = id
  showDeleteModal.value = true
}

const confirmDelete = async () => {
  if (!deletingAccountId.value) return
  deleting.value = true
  try {
    const res = await accountsApi.delete(deletingAccountId.value)
    const body = res.data as { code?: number; message?: string } | undefined
    if (body?.code === 0) {
      message.error(body.message || t('account.networkError'))
    } else {
      message.success(t('account.deleteSuccess'))
      showDeleteModal.value = false
      await loadAccounts()
    }
  } catch (e) {
    message.error(t('account.networkError'))
  } finally {
    deleting.value = false
    deletingAccountId.value = null
  }
}

const triggerScan = (id: number) => {
  showScanModal.value = true
  // Store the account id for confirmation
  ;(window as any).__scanTargetAccountId = id
}

const confirmScanNow = async () => {
  const accountId = (window as any).__scanTargetAccountId
  if (!accountId) return
  scanning.value = true
  try {
    const res = await accountsApi.scan(accountId, scanAutoDownload.value)
    // Backend returns {ok: true} on success, {error: "..."} on error
    if (res.data?.error) {
      message.error(res.data.error)
    } else if (res.data?.ok) {
      message.success(t('account.scanTriggered') + (scanAutoDownload.value ? ' ' + t('account.autoDownloadIncluded') : ''))
      showScanModal.value = false
    }
  } catch (e: any) {
    // Axios wraps the response; for 4xx/5xx the backend sends {error: "..."} in res.data
    const errorMsg = e?.response?.data?.error || e?.message || t('account.networkError')
    message.error(errorMsg)
  } finally {
    scanning.value = false
    ;(window as any).__scanTargetAccountId = null
  }
}

const previewRouting = async () => {
  if (!formData.value.id) return
  routingLoading.value = true
  try {
    const res = await accountsApi.routingPreview(formData.value.id)
    routingResult.value = res.data
    if (routingResult.value?.resolved_proxy_source === 'failed') routingColor.value = 'var(--error)'
    else if (routingResult.value?.resolved_proxy_source === 'direct') routingColor.value = 'var(--warning)'
    else routingColor.value = 'var(--success)'
  } catch (e) {
    message.error(t('account.loadFailed'))
  } finally {
    routingLoading.value = false
  }
}

const toggleScheduler = async () => {
  try {
    if (schedulerRunning.value) {
      await accountsApi.schedulerStop()
      message.success(t('scheduler.schedulerStopped'))
    } else {
      await accountsApi.schedulerStart()
      message.success(t('scheduler.schedulerStartedAuto'))
    }
    schedulerRunning.value = !schedulerRunning.value
  } catch (e) {
    message.error(t('scheduler.operationFailed'))
  }
}

const reloadJobs = async () => {
  try {
    await accountsApi.schedulerReload()
    message.success(t('scheduler.reloadDone'))
    await loadAccounts()
  } catch (e) {
    message.error(t('scheduler.reloadFailed'))
  }
}

// ── Lifecycle ──────────────────────────────────────────────────────────
watch(showDetailModal, (visible) => {
  if (!visible) {
    stopDetailDownloadPolling()
    detailClippingVideoIds.value = []
  }
})

onMounted(async () => {
  await Promise.all([loadAccounts(), loadApiKeys(), loadProxyPools()])
})

onUnmounted(() => {
  stopDetailDownloadPolling()
})
</script>

<style scoped>
.accounts-page {
  height: auto !important;
  overflow: visible !important;
}
.card-account-search {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 0 22px;
}
.account-count {
  font-size: 12px;
  color: var(--text-muted);
  margin-left: auto;
}
.account-row-actions,
.video-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.account-row-actions :deep(.n-button),
.video-row-actions :deep(.n-button) {
  flex: 0 0 auto;
}
.account-detail-action {
  min-width: 76px;
}
.video-clip-action {
  min-width: 52px;
}
.video-clip-action:not(.n-button--disabled) {
  color: var(--accent) !important;
  background: rgba(201, 100, 66, 0.12) !important;
  box-shadow: 0 0 0 1px rgba(201, 100, 66, 0.24) !important;
}
.video-clip-action:not(.n-button--disabled):hover {
  color: #b95738 !important;
  background: rgba(201, 100, 66, 0.18) !important;
}
.video-clip-action :deep(.n-button__content) {
  color: inherit !important;
}
.form-section {
  border-bottom: 1px solid var(--border);
  padding-bottom: 16px;
  margin-bottom: 16px;
}
.form-section:last-child {
  border-bottom: none;
  margin-bottom: 0;
}
.form-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 12px;
}
.platform-selector {
  display: flex;
  gap: 4px;
}
.platform-btn {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}
.platform-btn.active-feishu { background: var(--accent); color: #fff; border-color: var(--accent); }
.platform-btn.active-dingtalk { background: #1b9aee; color: #fff; border-color: #1b9aee; }
.platform-btn.active-telegram { background: #26a5e4; color: #fff; border-color: #26a5e4; }
.platform-btn.active-wecom { background: #07c160; color: #fff; border-color: #07c160; }
.routing-preview-box {
  background: var(--surface2);
  border-radius: 8px;
  padding: 12px;
  margin-top: 12px;
}
.routing-preview-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
}
.routing-preview-main {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}
.routing-preview-reason {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.scan-confirm-content {
  padding: 8px 0;
}
.video-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.video-detail__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface2);
}
.video-detail__identity {
  min-width: 0;
}
.video-detail__eyebrow {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.video-detail__account {
  font-size: 18px;
  font-weight: 650;
  color: var(--text);
}
.video-detail__channel {
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.video-detail__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
}
.video-detail__filters {
  display: grid;
  grid-template-columns:
    minmax(180px, 1.2fr)
    minmax(180px, 1.2fr)
    minmax(120px, .7fr)
    minmax(130px, .8fr)
    minmax(90px, .5fr)
    auto
    auto
    auto;
  gap: 8px;
  align-items: center;
}
.video-detail__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 36px;
}
.video-detail__selected,
.video-detail__status-page-hint {
  font-size: 12px;
  color: var(--text-muted);
}
.video-title-cell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}
.video-title-button {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.video-title-button:hover {
  color: var(--accent);
}
.video-url-line {
  color: var(--text-muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-progress {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--surface);
}
.detail-progress__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  color: var(--text);
}
.detail-progress__track {
  height: 6px;
  margin-top: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--surface2);
}
.detail-progress__fill {
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
  transition: width .2s ease;
}
.detail-progress__current {
  margin-top: 6px;
  color: var(--text-muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 900px) {
  .video-detail__header,
  .video-detail__footer {
    align-items: stretch;
    flex-direction: column;
  }
  .video-detail__actions {
    justify-content: flex-start;
  }
  .video-detail__filters {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
