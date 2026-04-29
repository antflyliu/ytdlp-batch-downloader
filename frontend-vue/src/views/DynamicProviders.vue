<template>
  <div class="dynamic-providers-page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('dynProviders.title') }}</div>
        <div class="text-sm text-dim">{{ t('dynProviders.desc') }}</div>
      </div>
      <NButton type="primary" @click="openAddProvider">
        {{ t('dynProviders.addProvider') }}
      </NButton>
    </div>

    <!-- Scheduler Status Card -->
    <div class="card">
      <div class="card-body">
        <div style="display:flex; gap:16px; flex-wrap:wrap">
          <div style="flex:1 1 280px">
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px">
              <span class="text-xs text-dim">Provider Scheduler</span>
              <NTag :type="schedulerRunning ? 'success' : 'warning'" size="small" round>
                {{ schedulerRunning ? t('provider.schedulerRunning') : t('provider.schedulerNotStarted') }}
              </NTag>
            </div>
            <div class="text-sm text-dim" style="margin-bottom:4px">
              {{ schedulerRunning ? t('provider.schedulerRunningHint') : t('provider.schedulerHint') }}
            </div>
            <div class="text-xs text-dim">
              {{ schedulerRunning ? nextRunText : '' }}
            </div>
          </div>
          <div style="display:flex; flex-direction:column; gap:8px; justify-content:center; flex-shrink:0">
            <div style="display:flex; gap:8px; flex-wrap:wrap">
              <NButton size="small" @click="toggleScheduler" :type="schedulerRunning ? 'warning' : 'success'" ghost>
                {{ schedulerRunning ? t('provider.btnStopDynScheduler') : t('provider.btnStartDynScheduler') }}
              </NButton>
              <NButton size="small" ghost @click="reloadJobs" :loading="reloading">
                {{ t('dynProviders.reloadDynamicProxyJobs') }}
              </NButton>
              <NButton size="small" ghost @click="refreshAll" :loading="refreshingAll">
                {{ t('dynProviders.refreshAllListApisNow') }}
              </NButton>
            </div>
            <NButton size="small" ghost @click="healthCheckAll" :loading="checkingAll">
              {{ t('dynProviders.healthCheckAll') }}
            </NButton>
          </div>
        </div>
      </div>
    </div>

    <!-- Collapsible: Logs + Help -->
    <NSpace vertical size="medium" class="mb-4">
      <!-- Recent Scheduler Logs -->
      <NCollapse>
        <NCollapseItem :title="t('dynProviders.recentExec')" name="logs">
          <template #header-extra>
            <span class="text-xs text-dim">{{ t('dynProviders.execHint') }}</span>
          </template>
          <div class="flex items-center gap-2 mb-3">
            <span class="text-sm text-dim">{{ t('dynProviders.logTypeLabel') }}</span>
            <NSelect v-model:value="logFilter" :options="logFilterOptions" size="small" style="width:180px" />
          </div>
          <div v-if="filteredLogs.length === 0" class="text-sm text-dim py-4 text-center">
            {{ t('provider.noLogsYet') }}
          </div>
          <div v-else class="dyn-log-list" style="max-height:240px;overflow-y:auto">
            <div
              v-for="(log, idx) in filteredLogs"
              :key="idx"
              class="dyn-log-row"
              :class="`dyn-log-row--${log.status === 'success' ? 'ok' : 'err'}`"
            >
              <div class="flex items-center justify-between">
                <span class="text-sm">{{ log.provider_name || 'system' }} · {{ log.job_type }}</span>
                <NTag size="tiny" :type="log.status === 'success' ? 'success' : 'error'" round>
                  {{ log.status }}
                </NTag>
              </div>
              <div class="text-xs text-dim mt-1">
                {{ log.job_type === 'refresh' ? `raw ${log.raw_count || 0} / valid ${log.valid_count || 0}` : (log.message || 'completed') }}
              </div>
              <div class="text-xs text-dim mt-1">{{ log.started_at }}</div>
            </div>
          </div>
        </NCollapseItem>
      </NCollapse>

      <!-- Scheduler Help -->
      <NCollapse>
        <NCollapseItem :title="t('dynProviders.schedulerDesc')" name="help">
          <div class="dyn-scheduler-help-body">
            <p v-html="t('dynProviders.helpText1')"></p>
            <p v-html="t('dynProviders.helpText2')"></p>
            <p v-html="t('dynProviders.helpText3')"></p>
            <p v-html="t('dynProviders.helpText4')"></p>
            <p v-html="t('dynProviders.helpText5')"></p>
          </div>
        </NCollapseItem>
      </NCollapse>
    </NSpace>

    <!-- Provider Table -->
    <NCard>
      <div class="mb-3">
        <div class="text-sm font-medium mb-1">{{ t('dynProviders.listTitle') }}</div>
        <div class="flex items-center gap-2">
          <NInput
            v-model:value="searchQuery"
            :placeholder="t('dynProviders.searchPlaceholder')"
            clearable
            size="small"
            style="max-width:300px"
          />
          <span class="text-xs text-dim">{{ summaryText }}</span>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="!loading && providers.length === 0 && !searchQuery" class="empty-state">
        <div class="empty-state__icon" aria-hidden="true">+</div>
        <div class="empty-state__title">{{ t('dynProviders.emptyTitle') }}</div>
        <div class="empty-state__desc">{{ t('dynProviders.emptyDesc') }}</div>
        <div class="empty-state__desc">{{ t('dynProviders.addFirstNote') }}</div>
        <NButton type="primary" size="small" class="mt-3" @click="openAddProvider">
          {{ t('dynProviders.addFirst') }}
        </NButton>
      </div>

      <!-- No Match -->
      <div v-else-if="!loading && filteredProviders.length === 0 && searchQuery" class="empty-state">
        <div class="empty-state__title">{{ t('provider.noMatchProviders') }}</div>
      </div>

      <!-- Table -->
      <div v-else class="table-wrap">
        <NDataTable
          class="app-sticky-table"
          :columns="columns"
          :data="filteredProviders"
          :pagination="{ pageSize: PAGE_SIZE }"
          :row-key="(row: DynamicProvider) => row.id"
          :loading="loading"
          :scroll-x="1040"
          :max-height="600"
          striped
          size="small"
        />
      </div>
    </NCard>

    <!-- Add/Edit Provider Modal -->
    <NModal
      v-model:show="showProviderModal"
      :block-scroll="false"
      :title="editingProvider ? t('dynProviders.addProviderTitle') : t('dynProviders.addProviderTitle')"
      preset="card"
      style="width:720px;max-width:95vw"
      :mask-closable="false"
    >
      <NSpace vertical size="medium">
        <!-- Basic Info -->
        <NSpace vertical size="small">
          <NFormItem :label="t('dynProviders.providerName')" required>
            <NInput v-model:value="form.name" :placeholder="t('dynProviders.providerNamePlaceholder')" />
          </NFormItem>
          <NGrid :cols="2" :x-gap="12">
            <NFormItemGi :label="t('dynProviders.billingTier')">
              <NSelect v-model:value="form.billing_tier" :options="billingTierOptions" />
            </NFormItemGi>
            <NFormItemGi :label="t('dynProviders.adapterType')">
              <NSelect v-model:value="form.adapter_type" :options="adapterTypeOptions" />
            </NFormItemGi>
          </NGrid>
          <NGrid :cols="2" :x-gap="12">
            <NFormItemGi :label="t('dynProviders.priority')">
              <NInputNumber v-model:value="form.priority" :min="1" :max="9999" size="small" style="width:100%" />
            </NFormItemGi>
            <NFormItemGi :label="t('dynProviders.riskLevel')">
              <NSelect v-model:value="form.risk_level" :options="riskLevelOptions" />
            </NFormItemGi>
          </NGrid>
          <NGrid :cols="2" :x-gap="12">
            <NFormItemGi :label="t('dynProviders.refreshInterval')">
              <NInputNumber v-model:value="form.refresh_interval_minutes" :min="0" size="small" style="width:100%" />
            </NFormItemGi>
            <NFormItemGi :label="t('dynProviders.enableNow')">
              <NSwitch v-model:value="form.enabled" />
            </NFormItemGi>
          </NGrid>
        </NSpace>

        <!-- Adapter Config Sections -->
        <NDivider>{{ t('dynProviders.gatewayConfig') }}</NDivider>

        <!-- Rotating Gateway Config -->
        <NCollapse
          v-if="form.adapter_type === 'rotating_gateway'"
          :key="form.adapter_type"
          :default-expanded-names="['rotating']"
        >
          <NCollapseItem :title="t('dynProviders.rotatingGateway')" name="rotating">
            <div class="config-section config-section--rotating">
              <NGrid :cols="2" :x-gap="12">
                <NFormItemGi :label="t('dynProviders.gatewayHost')" required>
                  <NInput v-model:value="form.config.gateway_host" :placeholder="t('dynProviders.gatewayHost')" />
                </NFormItemGi>
                <NFormItemGi :label="t('dynProviders.port')" required>
                  <NInputNumber v-model:value="form.config.gateway_port" :min="1" :max="65535" size="small" style="width:100%" />
                </NFormItemGi>
              </NGrid>
              <NGrid :cols="2" :x-gap="12">
                <NFormItemGi :label="t('dynProviders.protocol')">
                  <NSelect v-model:value="form.config.protocol" :options="protocolOptions" />
                </NFormItemGi>
                <NFormItemGi :label="t('dynProviders.username')">
                  <NInput v-model:value="form.config.username" />
                </NFormItemGi>
              </NGrid>
              <NFormItem :label="t('dynProviders.password')">
                <NInput
                  v-model:value="form.config.password"
                  type="password"
                  show-password-on="mousedown"
                  :placeholder="rotatingPasswordPlaceholder"
                />
              </NFormItem>
            </div>
          </NCollapseItem>
        </NCollapse>

        <!-- Local Gateway Config -->
        <NCollapse
          v-else-if="form.adapter_type === 'local_gateway'"
          :key="form.adapter_type"
          :default-expanded-names="['local']"
        >
              <NCollapseItem :title="t('dynProviders.localGateway')" name="local">
            <div class="config-section config-section--local">
              <NFormItem :label="t('dynProviders.localProxyUrl')" required>
                <NInput v-model:value="form.config.local_proxy_url" :placeholder="localProxyUrlPlaceholder" />
              </NFormItem>
            </div>
          </NCollapseItem>
        </NCollapse>

        <!-- List API / Public Feed Config -->
        <NCollapse
          v-else-if="form.adapter_type === 'list_api' || form.adapter_type === 'public_feed'"
          :key="form.adapter_type"
          :default-expanded-names="['listapi']"
        >
          <NCollapseItem
            :title="form.adapter_type === 'public_feed' ? t('dynProviders.publicFeed') : t('dynProviders.listApi')"
            name="listapi"
          >
            <div
              class="config-section"
              :class="form.adapter_type === 'public_feed' ? 'config-section--public-feed' : 'config-section--list-api'"
            >
              <NGrid :cols="2" :x-gap="12">
                <NFormItemGi :label="t('dynProviders.apiUrl')" required>
                  <NInput v-model:value="form.config.base_url" :placeholder="t('dynProviders.apiUrl')" />
                </NFormItemGi>
                <NFormItemGi :label="t('dynProviders.listAdapter')">
                  <NSelect
                    v-model:value="form.config.adapter_name"
                    :options="listAdapterOptions"
                    :placeholder="t('dynProviders.listAdapterHint')"
                    clearable
                  />
                </NFormItemGi>
              </NGrid>
              <NGrid :cols="2" :x-gap="12">
                <NFormItemGi :label="t('dynProviders.pageSize')">
                  <NInputNumber v-model:value="form.config.limit" :min="1" :max="1000" size="small" style="width:100%" />
                </NFormItemGi>
                <NFormItemGi :label="t('dynProviders.countryFilter')">
                  <NInput v-model:value="form.config.country" />
                </NFormItemGi>
              </NGrid>
              <NGrid :cols="2" :x-gap="12">
                <NFormItemGi :label="t('dynProviders.itemsPath')">
                  <NInput v-model:value="form.config.items_path" />
                </NFormItemGi>
                <NFormItemGi :label="t('dynProviders.protocolFilter')">
                  <NInput v-model:value="form.config.protocol" />
                </NFormItemGi>
              </NGrid>
              <!-- API Auth -->
              <NFormItem :label="t('dynProviders.apiAuth')">
                <NSwitch v-model:value="form.config.has_auth" />
              </NFormItem>
              <div v-if="form.config.has_auth">
                <NGrid :cols="2" :x-gap="12">
                  <NFormItemGi :label="t('dynProviders.authUsername')">
                    <NInput v-model:value="form.config.auth_username" />
                  </NFormItemGi>
                  <NFormItemGi :label="t('dynProviders.authPassword')">
                    <NInput
                      v-model:value="form.config.auth_password"
                      type="password"
                      show-password-on="mousedown"
                      :placeholder="listAuthPasswordPlaceholder"
                    />
                  </NFormItemGi>
                </NGrid>
              </div>
              <!-- Advanced Field Mapping -->
              <NCollapse>
                <NCollapseItem :title="t('dynProviders.advMapping')" name="adv">
                  <NGrid :cols="2" :x-gap="12">
                    <NFormItemGi :label="t('dynProviders.hostField')">
                      <NInput v-model:value="form.config.field_mapping.host" placeholder="ip" />
                    </NFormItemGi>
                    <NFormItemGi :label="t('dynProviders.portField')">
                      <NInput v-model:value="form.config.field_mapping.port" placeholder="port" />
                    </NFormItemGi>
                  </NGrid>
                  <NFormItem :label="t('dynProviders.protocolField')">
                    <NInput v-model:value="form.config.field_mapping.protocol" placeholder="protocols" />
                  </NFormItem>
                </NCollapseItem>
              </NCollapse>
            </div>
          </NCollapseItem>
        </NCollapse>

        <!-- Feature Support -->
        <NDivider>{{ t('dynProviders.featureSupport') }}</NDivider>
        <NCollapse>
          <NCollapseItem :title="t('dynProviders.featureSupport')" name="features">
            <NGrid :cols="2" :x-gap="12">
              <NFormItemGi>
                <NSpace align="center">
                  <NSwitch v-model:value="form.supports_auto_download" />
                  <span class="text-sm">{{ t('dynProviders.supportsAutoDl') }}</span>
                </NSpace>
              </NFormItemGi>
              <NFormItemGi>
                <NSpace align="center">
                  <NSwitch v-model:value="form.supports_cookies" />
                  <span class="text-sm">{{ t('dynProviders.supportsCookie') }}</span>
                </NSpace>
              </NFormItemGi>
              <NFormItemGi>
                <NSpace align="center">
                  <NSwitch v-model:value="form.supports_country_filter" />
                  <span class="text-sm">{{ t('dynProviders.supportsCountry') }}</span>
                </NSpace>
              </NFormItemGi>
              <NFormItemGi>
                <NSpace align="center">
                  <NSwitch v-model:value="form.supports_sticky_session" />
                  <span class="text-sm">{{ t('dynProviders.supportsSticky') }}</span>
                </NSpace>
              </NFormItemGi>
            </NGrid>
          </NCollapseItem>
        </NCollapse>

        <!-- Notes -->
        <NFormItem :label="t('dynProviders.notes')">
          <NInput v-model:value="form.notes" type="textarea" :rows="2" :placeholder="t('dynProviders.notesPlaceholder')" />
        </NFormItem>
      </NSpace>

      <template #footer>
        <NSpace justify="end">
          <NButton @click="showProviderModal = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="saving" @click="saveProvider">
            {{ t('dynProviders.saveProvider') }}
          </NButton>
        </NSpace>
      </template>
    </NModal>

    <!-- Provider Detail Drawer -->
    <NDrawer v-model:show="showDetailDrawer" :block-scroll="false" :width="420" placement="right">
      <NDrawerContent :title="detailProvider?.name || ''" closable>
        <template v-if="detailLoading">
          <div style="display:flex; justify-content:center; padding:32px 0">
            <NSpin size="medium" />
          </div>
        </template>
        <template v-else-if="detailProvider">
          <NSpace vertical size="medium">
            <!-- Summary Card -->
            <NCard size="small">
              <div class="text-sm text-dim mb-1">
                {{ detailProvider.adapter_type }} · Priority {{ detailProvider.priority }} · Refresh {{ detailProvider.refresh_interval_minutes || 0 }} min
              </div>
              <NTag v-if="detailProvider.billing_tier === 'paid'" type="warning" size="small">{{ t('provider.paidChip') }}</NTag>
              <NTag v-else type="info" size="small">{{ t('provider.freeChip') }}</NTag>
              <NTag v-if="detailProvider.is_in_cooldown" type="error" size="small" class="ml-2">{{ t('provider.cooldownBadge') }}</NTag>
            </NCard>

            <!-- Metrics -->
            <NGrid :cols="3" :x-gap="8">
              <NCard size="small">
                <div class="text-xs text-dim">{{ t('provider.latestRaw') }}</div>
                <div class="text-lg font-semibold">{{ detailMetrics?.raw_count ?? '—' }}</div>
              </NCard>
              <NCard size="small">
                <div class="text-xs text-dim">{{ t('provider.latestValid') }}</div>
                <div class="text-lg font-semibold">{{ detailMetrics?.valid_count ?? '—' }}</div>
              </NCard>
              <NCard size="small">
                <div class="text-xs text-dim">{{ t('provider.latestStatus') }}</div>
                <NTag :type="healthType(detailProvider.last_health_status)" size="tiny">{{ detailProvider.last_health_status || 'unknown' }}</NTag>
              </NCard>
            </NGrid>

            <!-- Candidate Preview -->
            <NCard v-if="candidatePreview" size="small">
              <div class="text-xs text-dim mb-1">{{ t('provider.candidatePreview') }}</div>
              <div class="text-sm">
                Total {{ candidatePreview.total_count || 0 }} ·
                healthy {{ candidatePreview.status_counts?.healthy || 0 }} ·
                degraded {{ candidatePreview.status_counts?.degraded || 0 }} ·
                down {{ candidatePreview.status_counts?.down || 0 }}
              </div>
              <div v-if="candidatePreview.top_candidate" class="text-xs text-dim mt-1">
                {{ t('provider.topCandidate') }}: {{ candidatePreview.top_candidate.masked_proxy_endpoint || '—' }}
              </div>
            </NCard>

            <!-- Error -->
            <NCard v-if="detailProvider.last_error_message" size="small">
              <div class="text-xs" style="color:var(--error)">{{ t('provider.recentError') }}</div>
              <div class="text-sm mt-1">{{ detailProvider.last_error_message }}</div>
            </NCard>

            <!-- Action Buttons -->
            <NSpace>
              <NButton size="small" @click="refreshProviderDetail">{{ t('provider.btnRefreshCurrent') }}</NButton>
              <NButton size="small" @click="healthCheckProviderDetail">{{ t('provider.btnHealthCheck') }}</NButton>
              <NButton v-if="detailProvider.is_in_cooldown" size="small" @click="clearCooldownProviderDetail">{{ t('provider.btnClearCooldown') }}</NButton>
            </NSpace>

            <!-- Recent Exec History -->
            <NCard size="small" :title="t('provider.recentExecHistory')">
              <div v-if="detailLogs.length === 0" class="text-sm text-dim">{{ t('provider.noExecHistory') }}</div>
              <NSpace v-else vertical size="small">
                <div
                  v-for="(log, idx) in detailLogs"
                  :key="idx"
                  class="p-2 rounded"
                  :style="{ background: log.status === 'success' ? 'var(--success-dim)' : 'var(--error-dim)' }"
                >
                  <div class="flex items-center justify-between">
                    <span class="text-sm font-medium">{{ log.job_type }}</span>
                    <NTag size="tiny" :type="log.status === 'success' ? 'success' : 'error'" round>{{ log.status }}</NTag>
                  </div>
                  <div class="text-xs text-dim mt-1">
                    raw {{ log.raw_count || 0 }} / valid {{ log.valid_count || 0 }} · {{ log.started_at }}
                  </div>
                </div>
              </NSpace>
            </NCard>
          </NSpace>
        </template>
        <template v-else>
          <div class="empty-state">
            <div class="empty-state__title">{{ t('provider.providerDetailNotFound') }}</div>
          </div>
        </template>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { h } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NButton, NCard, NSpace, NTag, NInput, NInputNumber, NSelect, NSwitch,
  NGrid, NFormItemGi, NFormItem, NDivider, NCollapse,
  NCollapseItem, NDataTable, NModal, NDrawer, NDrawerContent, NSpin,
  NDropdown, useMessage,
} from 'naive-ui'
import type { DropdownOption } from 'naive-ui'
import request from '@/api/request'

const { t } = useI18n()
const message = useMessage()

const MASKED_SECRET_VALUE = '***'
const PAGE_SIZE = 15

// ── State ────────────────────────────────────────────────────────────
const loading = ref(false)
const saving = ref(false)
const reloading = ref(false)
const refreshingAll = ref(false)
const checkingAll = ref(false)
const detailLoading = ref(false)

const providers = ref<DynamicProvider[]>([])
const schedulerRunning = ref(false)
const nextRuns = ref<NextRun[]>([])
const schedulerLogs = ref<SchedulerLog[]>([])
const logFilter = ref('all')

const searchQuery = ref('')

// Modal
const showProviderModal = ref(false)
const editingProvider = ref<DynamicProvider | null>(null)
const form = ref<ProviderForm>(buildForm())
const hasSavedRotatingPassword = ref(false)
const hasSavedListAuthPassword = ref(false)
const hasSavedLocalProxyUrl = ref(false)

// Detail
const showDetailDrawer = ref(false)
const detailProviderId = ref<number | null>(null)
const detailProvider = ref<DynamicProvider | null>(null)
const detailLogs = ref<SchedulerLog[]>([])
const detailMetrics = ref<any>(null)
const candidatePreview = ref<any>(null)

// ── Types ─────────────────────────────────────────────────────────
interface DynamicProvider {
  id: number
  name: string
  billing_tier: 'paid' | 'free'
  adapter_type: string
  enabled: boolean
  priority: number
  risk_level: string
  refresh_interval_minutes: number
  supports_auto_download: boolean
  supports_cookies: boolean
  supports_country_filter: boolean
  supports_sticky_session: boolean
  notes: string | null
  last_health_status: string
  is_in_cooldown: boolean
  last_error_message: string | null
  config_json: any
}

interface SchedulerLog {
  provider_id: number
  provider_name: string
  job_type: string
  status: string
  raw_count: number
  valid_count: number
  started_at: string
  message: string
}

interface NextRun {
  id: string
  name: string
  next_run: string
}

interface ProviderConfig {
  gateway_host: string
  gateway_port: number | null
  protocol: string
  username: string
  password: string
  local_proxy_url: string
  base_url: string
  adapter_name: string
  limit: number
  items_path: string
  country: string
  has_auth: boolean
  auth_username: string
  auth_password: string
  field_mapping: {
    host: string
    port: string
    protocol: string
  }
}

interface ProviderForm {
  name: string
  billing_tier: 'paid' | 'free'
  adapter_type: string
  priority: number
  risk_level: string
  refresh_interval_minutes: number
  supports_auto_download: boolean
  supports_cookies: boolean
  supports_country_filter: boolean
  supports_sticky_session: boolean
  enabled: boolean
  notes: string
  config: ProviderConfig
}

// ── Form Builder ─────────────────────────────────────────────────────
function buildForm(): ProviderForm {
  return {
    name: '',
    billing_tier: 'paid',
    adapter_type: 'rotating_gateway',
    priority: 100,
    risk_level: 'medium',
    refresh_interval_minutes: 0,
    supports_auto_download: true,
    supports_cookies: false,
    supports_country_filter: false,
    supports_sticky_session: true,
    enabled: true,
    notes: '',
    config: {
      gateway_host: '',
      gateway_port: null,
      protocol: 'http',
      username: '',
      password: '',
      local_proxy_url: '',
      base_url: '',
      adapter_name: '',
      limit: 50,
      items_path: '',
      country: '',
      has_auth: false,
      auth_username: '',
      auth_password: '',
      field_mapping: {
        host: '',
        port: '',
        protocol: ''
      }
    }
  }
}

// ── Computed ─────────────────────────────────────────────────────────
const logFilterOptions = [
  { label: t('dynProviders.logAll'), value: 'all' },
  { label: t('dynProviders.logRefresh'), value: 'refresh' },
  { label: t('dynProviders.logCleanup'), value: 'cleanup' },
  { label: t('dynProviders.logError'), value: 'error' },
]

const rotatingPasswordPlaceholder = computed(() => (
  hasSavedRotatingPassword.value
    ? t('settings.secretSavedPlaceholder')
    : ''
))

const listAuthPasswordPlaceholder = computed(() => (
  hasSavedListAuthPassword.value
    ? t('settings.secretSavedPlaceholder')
    : ''
))

const localProxyUrlPlaceholder = computed(() => (
  hasSavedLocalProxyUrl.value
    ? t('proxyPools.proxyUrlSavedPlaceholder')
    : t('dynProviders.localProxyUrlHint')
))

const filteredLogs = computed(() => {
  const mode = logFilter.value
  if (mode === 'refresh') return schedulerLogs.value.filter(r => r.job_type === 'refresh').slice(0, 6)
  if (mode === 'cleanup') return schedulerLogs.value.filter(r => r.job_type === 'cleanup').slice(0, 6)
  if (mode === 'error') return schedulerLogs.value.filter(r => r.status === 'error').slice(0, 6)
  return schedulerLogs.value.slice(0, 6)
})

const filteredProviders = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return providers.value.slice()
  return providers.value.filter(p => {
    return String(p.id).includes(q) ||
      (p.name || '').toLowerCase().includes(q) ||
      (p.adapter_type || '').toLowerCase().includes(q) ||
      (p.notes || '').toLowerCase().includes(q)
  })
})

const totalFiltered = computed(() => filteredProviders.value.length)
const totalPages = computed(() => Math.max(1, Math.ceil(totalFiltered.value / PAGE_SIZE)))
const currentPage = computed(() => pageIndex.value + 1)
const startItem = computed(() => pageIndex.value * PAGE_SIZE + 1)
const endItem = computed(() => Math.min(startItem.value + PAGE_SIZE - 1, totalFiltered.value))
const pageIndex = ref(0)

const summaryText = computed(() => {
  if (searchQuery.value.trim()) {
    return `${providers.value.length} total · ${totalFiltered.value} filtered · ${currentPage.value}/${totalPages.value}`
  }
  return `${totalFiltered.value} total · ${currentPage.value}/${totalPages.value}`
})

const nextRunText = computed(() => {
  if (nextRuns.value.length === 0) return t('provider.noTasksYet')
  return nextRuns.value.slice(0, 12).map(j => `${j.name || j.id}: ${j.next_run}`).join('; ')
})

// ── Options ──────────────────────────────────────────────────────────
const billingTierOptions = [
  { label: t('dynProviders.paid'), value: 'paid' },
  { label: t('dynProviders.free'), value: 'free' },
]

const adapterTypeOptions = [
  { label: t('dynProviders.rotatingGateway'), value: 'rotating_gateway' },
  { label: t('dynProviders.localGateway'), value: 'local_gateway' },
  { label: t('dynProviders.listApi'), value: 'list_api' },
  { label: t('dynProviders.publicFeed'), value: 'public_feed' },
]

const riskLevelOptions = [
  { label: t('dynProviders.riskLow'), value: 'low' },
  { label: t('dynProviders.riskMedium'), value: 'medium' },
  { label: t('dynProviders.riskHigh'), value: 'high' },
]

const protocolOptions = [
  { label: 'HTTP', value: 'http' },
  { label: 'HTTPS', value: 'https' },
  { label: 'SOCKS5', value: 'socks5' },
  { label: 'SOCKS4', value: 'socks4' },
]

const listAdapterOptions = [
  { label: t('dynProviders.geonode'), value: 'geonode' },
  { label: t('dynProviders.genericJson'), value: 'generic_json' },
]

// ── Helpers ─────────────────────────────────────────────────────────
function healthType(status: string): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'healthy') return 'success'
  if (status === 'degraded') return 'warning'
  if (status === 'down') return 'error'
  return 'default'
}

// ── API Calls ───────────────────────────────────────────────────────
async function loadAll() {
  loading.value = true
  try {
    const [provsRes, schedRes, logsRes] = await Promise.all([
      request.get('/api/dynamic-providers'),
      request.get('/api/provider-scheduler/status').catch(() => null) as any,
      request.get('/api/provider-scheduler/logs').catch(() => [] as any),
    ])
    providers.value = Array.isArray(provsRes.data) ? provsRes.data : []
    const sched = schedRes?.data as any
    schedulerRunning.value = !!(sched && sched.running && !sched.error)
    nextRuns.value = Array.isArray(sched?.next_runs) ? sched.next_runs : []
    schedulerLogs.value = Array.isArray(logsRes.data) ? logsRes.data : []
  } catch (e: any) {
    message.error(t('provider.loadProvidersFailed') + ': ' + (e?.message || ''))
    providers.value = []
  } finally {
    loading.value = false
  }
}

async function toggleScheduler() {
  const action = schedulerRunning.value ? 'stop' : 'start'
  try {
    await request.post(`/api/provider-scheduler/${action}`, {})
    await loadAll()
    message.success(schedulerRunning.value ? t('provider.schedulerRunning') : t('provider.schedulerNotStarted'))
  } catch (e: any) {
    message.error(e?.message || t('provider.operationError'))
  }
}

async function reloadJobs() {
  reloading.value = true
  try {
    await request.post('/api/provider-scheduler/reload', {})
    await loadAll()
    message.success(t('scheduler.reloadDone'))
  } catch (e: any) {
    message.error(e?.message || t('scheduler.reloadFailed'))
  } finally {
    reloading.value = false
  }
}

async function refreshAll() {
  refreshingAll.value = true
  try {
    await request.post('/api/provider-scheduler/run-once', {})
    await loadAll()
    message.success(t('scheduler.execDone'))
  } catch (e: any) {
    message.error(e?.message || t('scheduler.execFailed'))
  } finally {
    refreshingAll.value = false
  }
}

async function healthCheckAll() {
  if (providers.value.length === 0) {
    message.warning(t('provider.noProvidersToCheck'))
    return
  }
  checkingAll.value = true
  message.info(t('provider.healthCheckAllStart') + ' (' + providers.value.length + ')…')
  for (let i = 0; i < providers.value.length; i++) {
    await request.post(`/api/dynamic-providers/${providers.value[i].id}/health-check`, {}).catch(() => {})
    if (i % 3 === 2 || i === providers.value.length - 1) await loadAll()
  }
  message.success(t('provider.healthCheckAllDone') + ' (' + providers.value.length + ')')
  checkingAll.value = false
}

// ── Provider Actions ─────────────────────────────────────────────────
function openAddProvider() {
  editingProvider.value = null
  form.value = buildForm()
  hasSavedRotatingPassword.value = false
  hasSavedListAuthPassword.value = false
  hasSavedLocalProxyUrl.value = false
  showProviderModal.value = true
}

function openEditProvider(row: DynamicProvider) {
  editingProvider.value = row
  form.value = buildForm()
  form.value.name = row.name || ''
  form.value.billing_tier = row.billing_tier || 'free'
  form.value.adapter_type = row.adapter_type || 'rotating_gateway'
  form.value.priority = row.priority || 100
  form.value.risk_level = row.risk_level || 'medium'
  form.value.supports_auto_download = !!row.supports_auto_download
  form.value.supports_cookies = !!row.supports_cookies
  form.value.supports_country_filter = !!row.supports_country_filter
  form.value.supports_sticky_session = !!row.supports_sticky_session
  form.value.enabled = !!row.enabled
  form.value.notes = row.notes || ''
  form.value.refresh_interval_minutes = row.refresh_interval_minutes || 0
  const cfg = row.config_json || {}
  form.value.config.gateway_host = cfg.gateway_host || ''
  form.value.config.gateway_port = cfg.gateway_port || null
  form.value.config.protocol = cfg.protocol || 'http'
  form.value.config.username = cfg.username || ''
  hasSavedRotatingPassword.value = row.adapter_type === 'rotating_gateway' && !!cfg.password
  form.value.config.password = ''
  hasSavedLocalProxyUrl.value = row.adapter_type === 'local_gateway' && !!cfg.local_proxy_url
  form.value.config.local_proxy_url = hasSavedLocalProxyUrl.value ? '' : (cfg.local_proxy_url || '')
  form.value.config.base_url = cfg.base_url || ''
  form.value.config.adapter_name = cfg.adapter_name || ''
  form.value.config.limit = cfg.limit || 50
  form.value.config.items_path = cfg.items_path || ''
  form.value.config.country = cfg.country || ''
  const hasAuth = !!(cfg.username)
  form.value.config.has_auth = hasAuth
  form.value.config.auth_username = hasAuth ? (cfg.username || '') : ''
  hasSavedListAuthPassword.value = (
    (row.adapter_type === 'list_api' || row.adapter_type === 'public_feed') &&
    hasAuth &&
    !!cfg.password
  )
  form.value.config.auth_password = ''
  const fm = cfg.field_mapping || {}
  form.value.config.field_mapping.host = (fm.host && fm.host[0]) || ''
  form.value.config.field_mapping.port = (fm.port && fm.port[0]) || ''
  form.value.config.field_mapping.protocol = Array.isArray(fm.protocol) ? fm.protocol.join(',') : ''
  showProviderModal.value = true
}

function buildConfigJson(): Record<string, any> | null {
  const cfg: Record<string, any> = {}
  const adapter = form.value.adapter_type
  if (adapter === 'rotating_gateway') {
    const host = form.value.config.gateway_host?.trim()
    const port = form.value.config.gateway_port
    if (!host || !port) { message.warning(t('provider.gatewayRequired')); return null }
    cfg.gateway_host = host
    cfg.gateway_port = port
    cfg.protocol = form.value.config.protocol
    const uname = form.value.config.username?.trim()
    const pwd = form.value.config.password
    if (uname) cfg.username = uname
    if (pwd) cfg.password = pwd
    else if (editingProvider.value && hasSavedRotatingPassword.value) cfg.password = MASKED_SECRET_VALUE
  } else if (adapter === 'local_gateway') {
    const url = form.value.config.local_proxy_url?.trim()
    if (url) cfg.local_proxy_url = url
    else if (editingProvider.value && hasSavedLocalProxyUrl.value) cfg.local_proxy_url = MASKED_SECRET_VALUE
    else { message.warning(t('provider.localProxyRequired')); return null }
  } else if (adapter === 'list_api' || adapter === 'public_feed') {
    const baseUrl = form.value.config.base_url?.trim()
    if (!baseUrl) { message.warning(t('provider.apiUrlRequired')); return null }
    cfg.base_url = baseUrl
    const adapterName = form.value.config.adapter_name?.trim()
    if (adapterName) cfg.adapter_name = adapterName
    const limit = form.value.config.limit
    if (limit > 0) cfg.limit = limit
    const itemsPath = form.value.config.items_path?.trim()
    if (itemsPath) cfg.items_path = itemsPath
    const country = form.value.config.country?.trim()
    if (country) cfg.country = country
    const proto = form.value.config.protocol?.trim()
    if (proto) cfg.protocol = proto
    if (form.value.config.has_auth) {
      const u = form.value.config.auth_username?.trim()
      const p = form.value.config.auth_password
      if (u) cfg.username = u
      if (p) cfg.password = p
      else if (editingProvider.value && hasSavedListAuthPassword.value) cfg.password = MASKED_SECRET_VALUE
    }
    cfg.field_mapping = {}
    const hf = form.value.config.field_mapping.host?.trim()
    const pf = form.value.config.field_mapping.port?.trim()
    const rf = form.value.config.field_mapping.protocol?.trim()
    if (hf) cfg.field_mapping.host = [hf]
    if (pf) cfg.field_mapping.port = [pf]
    if (rf) cfg.field_mapping.protocol = rf.split(',').map((s: string) => s.trim()).filter(Boolean)
  }
  return cfg
}

async function saveProvider() {
  if (!form.value.name?.trim()) {
    message.warning(t('provider.providerNameRequired'))
    return
  }
  const cfg = buildConfigJson()
  if (cfg === null) return
  saving.value = true
  try {
    const body = {
      name: form.value.name.trim(),
      billing_tier: form.value.billing_tier,
      adapter_type: form.value.adapter_type,
      priority: form.value.priority || 100,
      risk_level: form.value.risk_level,
      config_json: cfg,
      supports_auto_download: form.value.supports_auto_download,
      supports_cookies: form.value.supports_cookies,
      supports_country_filter: form.value.supports_country_filter,
      supports_sticky_session: form.value.supports_sticky_session,
      enabled: form.value.enabled,
      notes: form.value.notes?.trim() || null,
      refresh_interval_minutes: form.value.refresh_interval_minutes || 0,
    }
    if (editingProvider.value) {
      await request.post(`/api/dynamic-providers/${editingProvider.value.id}/update`, body)
      message.success(t('provider.editSuccess'))
    } else {
      await request.post('/api/dynamic-providers', body)
      message.success(t('provider.addSuccess'))
    }
    showProviderModal.value = false
    await loadAll()
  } catch (e: any) {
    message.error(e?.message || t('provider.operationError'))
  } finally {
    saving.value = false
  }
}

async function toggleProvider(row: DynamicProvider) {
  try {
    await request.post(`/api/dynamic-providers/${row.id}/update`, { enabled: !row.enabled })
    await loadAll()
  } catch (e: any) {
    message.error(e?.message || t('provider.operationError'))
  }
}

async function healthCheckProvider(row: DynamicProvider) {
  try {
    const res = await request.post(`/api/dynamic-providers/${row.id}/health-check`, {})
    const r = res.data
    const latency = r.latency_ms >= 0 ? r.latency_ms + 'ms' : '-'
    const statusLabel = r.status === 'healthy' ? t('provider.healthOk')
      : r.status === 'degraded' ? t('provider.healthDegraded')
      : r.status === 'down' ? t('provider.healthUnavailable') : 'unknown'
    message.success(`Health check: ${statusLabel} (${latency})`)
    await loadAll()
  } catch (e: any) {
    message.error(t('provider.healthCheckError') + ': ' + (e?.message || ''))
  }
}

async function refreshProvider(row: DynamicProvider) {
  try {
    const res = await request.post(`/api/dynamic-providers/${row.id}/refresh`, {})
    const r = res.data
    const raw = r.raw_count || 0
    const valid = r.valid_count || 0
    message.success(`${t('provider.refreshSuccess')} — raw ${raw}, valid ${valid}`)
    await loadAll()
  } catch (e: any) {
    message.error(t('provider.refreshError') + ': ' + (e?.message || ''))
  }
}

async function previewProvider(row: DynamicProvider) {
  try {
    const res = await request.get(`/api/dynamic-providers/${row.id}/candidates/preview`)
    const r = res.data
    if (!r || r.error) { message.error(t('provider.previewFailed') + ': ' + (r?.error || '')); return }
    const total = r.total_count || 0
    const sc = r.status_counts || {}
    message.success(`${t('provider.previewSuccess')} ${total} — healthy=${sc.healthy || 0} | degraded=${sc.degraded || 0} | down=${sc.down || 0}`)
  } catch (e: any) {
    message.error(t('provider.previewFailed') + ': ' + (e?.message || ''))
  }
}

async function clearCooldown(row: DynamicProvider) {
  try {
    await request.post(`/api/dynamic-providers/${row.id}/cooldown/clear`, {})
    message.success(t('provider.clearCooldown'))
    await loadAll()
  } catch (e: any) {
    message.error(e?.message || t('provider.operationError'))
  }
}

async function deleteProvider(row: DynamicProvider) {
  try {
    await request.delete(`/api/dynamic-providers/${row.id}`)
    message.success(t('provider.deleteSuccess'))
    await loadAll()
  } catch (e: any) {
    message.error(e?.message || t('provider.operationError'))
  }
}

function providerActionOptions(row: DynamicProvider): DropdownOption[] {
  const options: DropdownOption[] = [
    { label: t('provider.btnEdit'), key: 'edit' },
    { label: row.enabled ? t('provider.btnDisable') : t('provider.btnToggle'), key: 'toggle' },
    { label: t('provider.btnCheck'), key: 'check' },
    { label: t('provider.btnRefresh'), key: 'refresh' },
    { label: t('provider.btnPreview'), key: 'preview' },
    { label: t('provider.btnDetail'), key: 'detail' },
  ]

  if (row.is_in_cooldown) {
    options.push({ label: t('provider.btnClearCooldown'), key: 'clearCooldown' })
  }

  options.push(
    { type: 'divider', key: 'delete-divider' },
    {
      label: t('provider.btnDelete'),
      key: 'delete',
      props: {
        style: 'color: var(--error); font-weight: 600;',
      },
    }
  )

  return options
}

function handleProviderAction(row: DynamicProvider, key: string | number) {
  switch (key) {
    case 'edit':
      openEditProvider(row)
      break
    case 'toggle':
      toggleProvider(row)
      break
    case 'check':
      healthCheckProvider(row)
      break
    case 'refresh':
      refreshProvider(row)
      break
    case 'preview':
      previewProvider(row)
      break
    case 'detail':
      openDetail(row)
      break
    case 'clearCooldown':
      clearCooldown(row)
      break
    case 'delete':
      deleteProvider(row)
      break
  }
}

// ── Detail Drawer ────────────────────────────────────────────────────
async function openDetail(row: DynamicProvider) {
  detailProviderId.value = row.id
  detailProvider.value = row
  detailLoading.value = true
  showDetailDrawer.value = true
  try {
    const [logsRes, previewRes] = await Promise.all([
      request.get('/api/provider-scheduler/logs').catch(() => ({ data: [] })),
      request.get(`/api/dynamic-providers/${row.id}/candidates/preview`).catch(() => ({ data: null })),
    ])
    const logList: SchedulerLog[] = Array.isArray(logsRes.data) ? logsRes.data : []
    detailLogs.value = logList.filter(r => String(r.provider_id) === String(row.id)).slice(0, 8)
    detailMetrics.value = detailLogs.value.length ? detailLogs.value[0] : null
    candidatePreview.value = previewRes.data && !previewRes.data.error ? previewRes.data : null
  } catch {
    detailLogs.value = []
    candidatePreview.value = null
  } finally {
    detailLoading.value = false
  }
}

async function refreshProviderDetail() {
  if (!detailProviderId.value) return
  try {
    await request.post(`/api/dynamic-providers/${detailProviderId.value}/refresh`, {})
    message.success(t('provider.refreshSuccess'))
    await openDetail({ id: detailProviderId.value! } as DynamicProvider)
  } catch (e: any) {
    message.error(t('provider.refreshException') + ': ' + (e?.message || ''))
  }
}

async function healthCheckProviderDetail() {
  if (!detailProviderId.value) return
  try {
    await request.post(`/api/dynamic-providers/${detailProviderId.value}/health-check`, {})
    message.success(t('provider.healthCheckDone'))
    await loadAll()
  } catch (e: any) {
    message.error(t('provider.healthCheckException') + ': ' + (e?.message || ''))
  }
}

async function clearCooldownProviderDetail() {
  if (!detailProviderId.value) return
  try {
    await request.post(`/api/dynamic-providers/${detailProviderId.value}/cooldown/clear`, {})
    message.success(t('provider.clearCooldown'))
    await loadAll()
    await openDetail({ id: detailProviderId.value } as DynamicProvider)
  } catch (e: any) {
    message.error(e?.message || t('provider.operationException'))
  }
}

// ── Columns ─────────────────────────────────────────────────────────
const columns = computed(() => [
  {
    title: t('dynProviders.thId'),
    key: 'id',
    width: 50,
    render: (row: DynamicProvider) => h('span', { style: 'font-family:monospace;font-size:12px' }, row.id)
  },
  {
    title: t('dynProviders.thName'),
    key: 'name',
    width: 200,
    ellipsis: { tooltip: true },
    render: (row: DynamicProvider) => {
      const nextRun = nextRuns.value.find(j => {
        const m = /^provider_refresh_(\d+)$/.exec(j.id || '')
        return m && String(m[1]) === String(row.id)
      })
      const log = schedulerLogs.value.find(r => String(r.provider_id) === String(row.id))
      const parts = [
        h('div', row.name || '-'),
      ]
      if (nextRun || log) {
        const meta: string[] = []
        if (nextRun) meta.push(`${t('provider.nextRun')}${nextRun.next_run}`)
        if (log) meta.push(`${t('provider.lastRun')}${log.started_at || ''} raw ${log.raw_count || 0} / valid ${log.valid_count || 0}`)
        parts.push(h('div', { style: 'font-size:10px;color:#87867f;margin-top:2px' }, meta.join(' ')))
      }
      return h('div', parts)
    }
  },
  {
    title: t('dynProviders.thBilling'),
    key: 'billing_tier',
    width: 90,
    render: (row: DynamicProvider) => h(NTag, {
      type: row.billing_tier === 'paid' ? 'warning' : 'info',
      size: 'small'
    }, () => row.billing_tier === 'paid' ? t('provider.paidChip') : t('provider.freeChip'))
  },
  {
    title: t('dynProviders.thAdapter'),
    key: 'adapter_type',
    width: 130,
    render: (row: DynamicProvider) => h('span', { style: 'font-family:monospace;font-size:12px' }, row.adapter_type || '-')
  },
  {
    title: t('dynProviders.thHealth'),
    key: 'health',
    width: 120,
    render: (row: DynamicProvider) => {
      const status = row.last_health_status || ''
      const dotColor = status === 'healthy' ? 'var(--success)' : status === 'degraded' ? 'var(--warning)' : status === 'down' ? 'var(--error)' : 'var(--text-dim)'
      const label = status === 'healthy' ? t('provider.healthOk')
        : status === 'degraded' ? t('provider.healthDegraded')
        : status === 'down' ? t('provider.healthDown')
        : t('provider.healthUnknown')
      const children = [
        h('span', { style: `width:8px;height:8px;border-radius:50%;background:${dotColor};display:inline-block;flex-shrink:0` }),
        h(NTag, { type: healthType(status), size: 'small' }, () => label),
      ]
      if (row.is_in_cooldown) children.push(h(NTag, { type: 'error', size: 'tiny' }, () => t('provider.cooldownBadge')))
      if (row.last_error_message) {
        children.push(h('div', {
          style: 'font-size:10px;color:var(--error);max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
          title: row.last_error_message
        }, row.last_error_message))
      }
      return h('div', { style: 'display:flex;align-items:center;gap:5px' }, children)
    }
  },
  {
    title: t('dynProviders.thPriority'),
    key: 'priority',
    width: 70,
    render: (row: DynamicProvider) => h('span', { style: 'font-family:monospace;font-size:12px' }, row.priority)
  },
  {
    title: t('dynProviders.thFeatures'),
    key: 'features',
    width: 200,
    render: (row: DynamicProvider) => {
      const tags = []
      if (row.supports_auto_download) tags.push(h(NTag, { type: 'success', size: 'small' }, () => t('provider.autoDownloadChip')))
      if (row.supports_cookies) tags.push(h(NTag, { type: 'info', size: 'small' }, () => t('provider.cookiesChip')))
      if (row.supports_sticky_session) tags.push(h(NTag, { type: 'warning', size: 'small' }, () => t('provider.stickyChip')))
      return h('div', { style: 'display:flex;gap:4px;flex-wrap:wrap' }, tags)
    }
  },
  {
    title: t('dynProviders.thActions'),
    key: 'actions',
    width: 128,
    fixed: 'right' as const,
    render: (row: DynamicProvider) =>
      h('div', { class: 'provider-row-actions' }, [
        h(
          NDropdown,
          {
            trigger: 'click',
            placement: 'bottom-end',
            showArrow: true,
            options: providerActionOptions(row),
            onSelect: (key: string | number) => handleProviderAction(row, key),
          },
          {
            default: () =>
              h(NButton, { size: 'small', tertiary: true, class: 'provider-action-trigger' }, () => `${t('action.more')} ▾`),
          }
        ),
      ]),
  },
])

// ── Init ──────────────────────────────────────────────────────────────
onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.dyn-log-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dyn-log-row {
  padding: 8px 10px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
}
.dyn-log-row--ok {
  background: rgba(34, 197, 94, 0.04);
  border-color: rgba(34, 197, 94, 0.2);
}
.dyn-log-row--err {
  background: rgba(239, 68, 68, 0.04);
  border-color: rgba(239, 68, 68, 0.2);
}
.dyn-scheduler-help-body {
  font-size: 13px;
  line-height: 1.7;
}
.dyn-scheduler-help-body p {
  margin: 0 0 8px 0;
}
.config-section {
  padding: 4px 0;
}
.provider-row-actions {
  display: flex;
  justify-content: flex-end;
  min-width: max-content;
}
.provider-row-actions :deep(.provider-action-trigger) {
  min-width: 76px;
  font-weight: 600;
}
</style>
