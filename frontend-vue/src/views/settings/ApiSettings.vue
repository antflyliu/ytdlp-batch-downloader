<template>
  <div>
    <!-- Back link -->
    <RouterLink to="/settings-hub" class="back-link">
      {{ t('settings.backToSettings') }}
    </RouterLink>

    <div class="page-header">
      <div class="page-title">{{ t('settings.apiTitle') }}</div>
      <div class="page-desc">{{ t('settings.apiDesc') }}</div>
    </div>

    <NForm ref="formRef" :model="form" label-placement="left" label-width="180">
      <!-- Default API Key -->
      <NCard :title="t('settings.defaultApiKey')">
        <NFormItem :label="t('settings.defaultApiKey')" path="default_api_key">
          <NSelect
            v-model:value="form.default_api_key_id"
            :options="apiKeyOptions"
            :placeholder="t('settings.noDefaultKey')"
            clearable
            style="width: 320px"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.defaultApiKeyHint') }}
        </div>
      </NCard>

      <!-- Quota -->
      <NCard :title="t('settings.apiQuota')">
        <NFormItem :label="t('config.quotaBudget')" path="quota_budget">
          <NInputNumber
            v-model:value="form.quota_budget_per_day"
            :min="0"
            style="width: 200px"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          <span v-html="t('config.quotaBudgetHint')"></span>
        </div>

        <NFormItem :label="t('settings.quotaTimezone')" path="quota_timezone">
          <NSelect
            v-model:value="form.quota_usage_timezone"
            :options="[
              { label: t('config.localTimezone'), value: 'local' },
              { label: t('config.pacificTimezone'), value: 'America/Los_Angeles' },
            ]"
            style="width: 280px"
          />
        </NFormItem>

        <NFormItem :label="t('config.quotaAlertThresholds')" path="quota_alert_thresholds">
          <NInput
            v-model:value="form.quota_alert_thresholds"
            :placeholder="'80,90,100'"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.quotaAlertThresholdsHint') }}
        </div>
      </NCard>

      <!-- Channel Meta Health -->
      <NCard :title="t('config.channelMetaHealth')">
        <NFormItem :label="t('config.channelMetaHealth')" path="channel_meta_health_enable">
          <NSwitch v-model:value="form.channel_meta_health_check_enabled" />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.channelMetaHealthEnable') }}
        </div>

        <NFormItem :label="t('settings.healthCheckInterval')" path="channel_meta_health_interval_hours">
          <NInputNumber
            v-model:value="form.channel_meta_health_check_interval_hours"
            :min="1"
            :max="168"
            style="width: 200px"
          />
        </NFormItem>

        <NFormItem :label="t('config.channelMetaTTL')" path="channel_meta_ttl_days">
          <NInputNumber
            v-model:value="form.channel_meta_max_age_days"
            :min="0"
            :max="365"
            style="width: 200px"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          <span v-html="t('config.channelMetaTTLHint')"></span>
        </div>
      </NCard>

      <!-- Scan Behavior -->
      <NCard :title="t('settings.scanBehavior')">
        <NFormItem :label="t('config.notifyOnScanError')" path="notify_on_scan_error">
          <NSwitch v-model:value="form.notify_on_scan_error" />
        </NFormItem>

        <NFormItem :label="t('settings.scanErrorCooldown')" path="scan_error_cooldown">
          <NInputNumber
            v-model:value="form.scan_error_notify_cooldown_seconds"
            :min="0"
            style="width: 200px"
          />
        </NFormItem>

        <NFormItem :label="t('config.scanJitter')" path="scan_jitter">
          <NInputNumber
            v-model:value="form.scan_jitter_seconds"
            :min="0"
            :max="3600"
            style="width: 200px"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.scanJitterHint') }}
        </div>
      </NCard>

      <NButton type="primary" :loading="saving" @click="save">
        {{ t('config.saveConfig') }}
      </NButton>
    </NForm>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import {
  NForm, NFormItem, NInput, NInputNumber, NButton, NCard,
  NSelect, NSwitch, useMessage,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import configApi, { AppConfig } from '@/api/config'

const { t } = useI18n()
const message = useMessage()

const saving = ref(false)
const apiKeys = ref<{ id: number; name: string }[]>([])

const apiKeyOptions = ref<{ label: string; value: string }[]>([
  { label: t('settings.noDefaultKey'), value: '' },
])

const form = reactive<AppConfig>({
  default_api_key_id: '',
  quota_budget_per_day: undefined,
  quota_usage_timezone: 'local',
  quota_alert_thresholds: '',
  channel_meta_health_check_enabled: false,
  channel_meta_health_check_interval_hours: 24,
  channel_meta_max_age_days: 30,
  notify_on_scan_error: false,
  scan_error_notify_cooldown_seconds: 300,
  scan_jitter_seconds: 0,
})

const loadConfig = async () => {
  try {
    const [configRes, keysRes] = await Promise.all([
      configApi.get(),
      configApi.listApiKeys(),
    ])
    const data = configRes.data || {}
    apiKeys.value = keysRes.data || []

    apiKeyOptions.value = [
      { label: t('settings.noDefaultKey'), value: '' },
      ...apiKeys.value.map(k => ({ label: k.name, value: String(k.id) })),
    ]

    form.default_api_key_id = data.default_api_key_id || ''
    form.quota_budget_per_day = data.quota_budget_per_day
    form.quota_usage_timezone = data.quota_usage_timezone || 'local'
    form.quota_alert_thresholds = data.quota_alert_thresholds || ''
    form.channel_meta_health_check_enabled = !!data.channel_meta_health_check_enabled
    form.channel_meta_health_check_interval_hours = data.channel_meta_health_check_interval_hours || 24
    form.channel_meta_max_age_days = data.channel_meta_max_age_days || 30
    form.notify_on_scan_error = !!data.notify_on_scan_error
    form.scan_error_notify_cooldown_seconds = data.scan_error_notify_cooldown_seconds || 300
    form.scan_jitter_seconds = data.scan_jitter_seconds || 0
  } catch {
    message.error(t('settings.loadFailed'))
  }
}

const save = async () => {
  saving.value = true
  try {
    await configApi.save(form as AppConfig)
    message.success(t('settings.saved'))
  } catch {
    message.error(t('settings.saveFailed'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
</style>
