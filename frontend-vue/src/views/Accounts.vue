<template>
  <div class="accounts-page p-4">
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
          :columns="tableColumns"
          :data="filteredAccounts"
          :bordered="false"
          :virtual-scroll="true"
          :row-key="(row: Account) => row.id"
          :scroll-x="1400"
          :max-height="600"
          striped
        />
      </div>

      <!-- Empty State -->
      <div v-else class="empty-state">
        <div class="empty-icon">—</div>
        <div class="empty-title">{{ t('channels.emptyTitle') }}</div>
        <div class="empty-desc">{{ t('channels.emptyDesc') }}</div>
        <NButton type="primary" @click="openAddModal">
          {{ t('channels.addFirst') }}
        </NButton>
      </div>
    </div>

    <!-- Add/Edit Account Modal -->
    <NModal
      v-model:show="showAccountModal"
      preset="card"
      :title="editingAccount ? t('account.titleEdit') : t('account.modalTitleAdd')"
      style="width: 680px; max-height: 85vh;"
      :mask-closable="false"
    >
      <NScrollbar style="max-height: 65vh;">
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
                <span class="text-xs text-gray-500">{{ t('account.channelUrlHint') }}</span>
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
                <span class="text-xs text-gray-500">{{ t('account.apiKeyHint') }}</span>
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
                  <span class="text-xs text-gray-500">{{ t('account.webhookHintDefault') }}</span>
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
                  v-model:value="formData.dingtalk_sign_secret"
                  :placeholder="t('account.dingtalkSecretPlaceholder')"
                />
                <template #feedback>
                  <span class="text-xs text-gray-500">{{ t('account.dingtalkSecretHint') }}</span>
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
                  v-model:value="formData.telegram_bot_token"
                  :placeholder="t('account.botTokenPlaceholder')"
                />
                <template #feedback>
                  <span class="text-xs text-gray-500">{{ t('account.webhookHintTelegram') }}</span>
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
                <span class="text-xs text-gray-500 ml-2">{{ t('account.enableProxyHint') }}</span>
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
                <span class="text-xs text-gray-500">{{ t('account.proxyPoolHint') }}</span>
              </template>
            </NFormItem>

            <NFormItem :label="t('account.downloadMode')">
              <NSelect
                v-model:value="formData.download_proxy_mode"
                :options="downloadModeOptions"
              />
              <template #feedback>
                <span class="text-xs text-gray-500 ml-2">{{ t('account.downloadModeHint') }}</span>
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
      </NScrollbar>

      <template #footer>
        <div class="flex justify-end gap-2">
          <NButton @click="showAccountModal = false">
            {{ t('common.cancel') }}
          </NButton>
          <NButton type="primary" @click="saveAccount" :loading="saving">
            {{ t('common.submit') }}
          </NButton>
        </div>
      </template>
    </NModal>

    <!-- Scan Confirm Modal -->
    <NModal
      v-model:show="showScanModal"
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
        <div class="text-xs text-gray-500 mt-1">{{ t('scanConfirm.autoDlHint') }}</div>
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
import { ref, computed, onMounted, h } from 'vue'
import { useI18n } from 'vue-i18n'
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
  NScrollbar,
  NCheckbox,
  useMessage,
} from 'naive-ui'
import type { DataTableColumn } from 'naive-ui'
import accountsApi from '@/api/accounts'

const { t } = useI18n()
const message = useMessage()

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

// ── State ───────────────────────────────────────────────────────────────
const accounts = ref<Account[]>([])
const apiKeys = ref<ApiKey[]>([])
const proxyPools = ref<ProxyPool[]>([])
const schedulerRunning = ref(false)

const searchQuery = ref('')
const showAccountModal = ref(false)
const showScanModal = ref(false)
const showDeleteModal = ref(false)

const editingAccount = ref<Account | null>(null)
const deletingAccountId = ref<number | null>(null)

const saving = ref(false)
const scanning = ref(false)
const deleting = ref(false)
const routingLoading = ref(false)
const scanAutoDownload = ref(true)

const routingResult = ref<RoutingResult | null>(null)
const routingColor = ref('inherit')

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

const apiKeyOptions = computed(() => [
  { label: t('account.apiKeyDefault'), value: null },
  ...apiKeys.value.map(k => ({ label: `${k.name} (${k.key_value})`, value: k.id })),
])

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
    width: 220,
    render: (row) => h('div', { class: 'flex gap-1' }, [
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
  await loadApiKeys()
  await loadProxyPools()
  showAccountModal.value = true
}

const openEditModal = async (account: Account) => {
  editingAccount.value = account
  formData.value = { ...defaultFormData(), ...account }
  await loadApiKeys()
  await loadProxyPools()
  routingResult.value = null
  showAccountModal.value = true
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
    const data = { ...formData.value }
    delete (data as any).status  // remove status from payload
    let res
    if (editingAccount.value) {
      res = await accountsApi.update(formData.value.id, data)
    } else {
      res = await accountsApi.create(data)
    }
    if (res.code === 0) {
      message.error(res.message)
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
    if (res.code === 0) {
      message.error(res.message)
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
    if (res.code === 0) {
      message.error(res.message)
    } else {
      message.success(t('account.scanTriggered') + (scanAutoDownload.value ? ' ' + t('account.autoDownloadIncluded') : ''))
      showScanModal.value = false
    }
  } catch (e) {
    message.error(t('account.networkError'))
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
    if (routingResult.value?.resolved_proxy_source === 'failed') routingColor.value = '#f87171'
    else if (routingResult.value?.resolved_proxy_source === 'direct') routingColor.value = '#fbbf24'
    else routingColor.value = '#34d399'
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
onMounted(async () => {
  await Promise.all([loadAccounts(), loadApiKeys(), loadProxyPools()])
})
</script>

<style scoped>
.accounts-page {
  height: 100%;
  overflow-y: auto;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 0 0 16px;
  gap: 16px;
}
.page-title {
  font-family: var(--font);
  font-size: 20px;
  font-weight: 500;
  color: var(--text);
}
.page-desc {
  font-size: 12px;
  color: var(--text-dim);
  margin-top: 2px;
}
.card {
  background: var(--surface);
  border-radius: var(--r-md);
  padding: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}
.card-title-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: var(--accent-dim);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}
.actions {
  display: flex;
  gap: 8px;
}
.card-account-search {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.account-count {
  font-size: 12px;
  color: var(--text-muted);
  margin-left: auto;
}
.table-wrap {
  overflow-x: auto;
}
.empty-state {
  text-align: center;
  padding: 48px 24px;
}
.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
  color: var(--text-muted);
}
.empty-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 6px;
}
.empty-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 16px;
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
</style>