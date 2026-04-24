<template>
  <div>
    <!-- Back link -->
    <RouterLink to="/settings-hub" class="back-link mb-4">
      {{ t('settings.backToSettings') }}
    </RouterLink>

    <div class="page-header mb-6">
      <div class="page-title">{{ t('settings.dynamicTitle') }}</div>
      <div class="page-desc">{{ t('settings.dynamicDesc') }}</div>
    </div>

    <NForm ref="formRef" :model="form" label-placement="left" label-width="200">
      <!-- System Default Dynamic Proxy -->
      <NCard class="mb-4" :title="t('config.dynProxySection')">
        <NFormItem :label="t('config.dynProxyEnable')" path="dyn_proxy_enable">
          <NSwitch v-model:value="form.dyn_proxy_enable" />
        </NFormItem>
        <div class="text-xs text-gray-500 -mt-2 mb-3" style="padding-left: 200px">
          {{ t('config.dynProxyEnableDesc') }}
        </div>

        <NFormItem :label="t('config.dynProxyNewAccount')" path="dyn_proxy_new_account">
          <NSwitch v-model:value="form.dyn_proxy_new_account" />
        </NFormItem>
        <div class="text-xs text-gray-500 -mt-2 mb-3" style="padding-left: 200px">
          {{ t('config.dynProxyNewAccountDesc') }}
        </div>

        <NFormItem :label="t('config.dynProxyExistingAccount')" path="dyn_proxy_existing_account">
          <NSwitch v-model:value="form.dyn_proxy_existing_account" />
        </NFormItem>
        <div class="text-xs text-red-500 -mt-2 mb-3" style="padding-left: 200px">
          {{ t('config.dynProxyExistingAccountWarn') }}
        </div>

        <NFormItem :label="t('config.stickyMinutes')" path="dyn_proxy_sticky_minutes">
          <NInputNumber
            v-model:value="form.dyn_proxy_sticky_minutes"
            :min="0"
            style="width: 160px"
          />
        </NFormItem>
      </NCard>

      <!-- Risk Control -->
      <NCard class="mb-4" :title="t('config.riskControlSection')">
        <NFormItem :label="t('config.riskFreeProxyAuto')" path="risk_free_proxy_auto">
          <NSwitch v-model:value="form.risk_free_proxy_auto" />
        </NFormItem>

        <NFormItem :label="t('config.riskFreeProxyManual')" path="risk_free_proxy_manual">
          <NSwitch v-model:value="form.risk_free_proxy_manual" />
        </NFormItem>

        <NFormItem :label="t('config.riskCookieNoFreeProxy')" path="risk_cookie_no_free_proxy">
          <NSwitch v-model:value="form.risk_cookie_no_free_proxy" />
        </NFormItem>
        <div class="text-xs text-gray-500 -mt-2 mb-3" style="padding-left: 200px">
          {{ t('config.riskCookieNoFreeProxyDesc') }}
        </div>

        <NFormItem :label="t('config.riskAutoDirectFallback')" path="risk_auto_direct_fallback">
          <NSwitch v-model:value="form.risk_auto_direct_fallback" />
        </NFormItem>
        <div class="text-xs text-red-500 -mt-2 mb-3" style="padding-left: 200px">
          {{ t('config.riskAutoDirectFallbackWarn') }}
        </div>

        <NFormItem :label="t('config.riskManualDirectFallback')" path="risk_manual_direct_fallback">
          <NSwitch v-model:value="form.risk_manual_direct_fallback" />
        </NFormItem>

        <NFormItem :label="t('config.maskProxyLogs')" path="mask_proxy_logs">
          <NSwitch v-model:value="form.mask_proxy_logs" />
        </NFormItem>
        <div class="text-xs text-gray-500 -mt-2 mb-3" style="padding-left: 200px">
          {{ t('config.maskProxyLogsDesc') }}
        </div>

        <NFormItem :label="t('config.proxyProtocolOrder')" path="proxy_protocol_order">
          <NSelect
            v-model:value="form.proxy_protocol_order"
            :options="protocolOptions"
            style="width: 320px"
          />
        </NFormItem>
        <div class="text-xs text-gray-500 -mt-2 mb-3" style="padding-left: 200px">
          {{ t('config.proxyProtocolOrderDesc') }}
        </div>
      </NCard>

      <!-- Dynamic Provider -->
      <NCard class="mb-4" :title="t('config.dynProviderManageTitle')">
        <div class="text-sm text-gray-600 mb-3">
          {{ t('config.dynProviderManageDesc') }}
        </div>
        <NButton @click="goToProviders">
          {{ t('config.dynProviderManageBtn') }}
        </NButton>
      </NCard>

      <NButton type="primary" :loading="saving" @click="save">
        {{ t('config.saveConfig') }}
      </NButton>
    </NForm>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NForm, NFormItem, NInputNumber, NButton, NCard,
  NSelect, NSwitch, useMessage,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import configApi, { AppConfig } from '@/api/config'

const { t } = useI18n()
const router = useRouter()
const message = useMessage()

const saving = ref(false)

const protocolOptions = [
  { label: t('config.proxyProtoHttpHttpsSocks5Socks4'), value: 'http>https>socks5>socks4' },
  { label: t('config.proxyProtoSocks5HttpsHttpSocks4'), value: 'socks5>https>http>socks4' },
  { label: t('config.proxyProtoHttpsHttpSocks5Socks4'), value: 'https>http>socks5>socks4' },
  { label: t('config.proxyProtoSocks5HttpsHttp'), value: 'socks5>https>http' },
  { label: t('config.proxyProtoHttpHttpsSocks5'), value: 'http>https>socks5' },
  { label: t('config.proxyProtoHttpsHttpSocks5'), value: 'https>http>socks5' },
]

const form = reactive<AppConfig>({
  dyn_proxy_enable: false,
  dyn_proxy_new_account: false,
  dyn_proxy_existing_account: false,
  dyn_proxy_sticky_minutes: 5,
  risk_free_proxy_auto: false,
  risk_free_proxy_manual: true,
  risk_cookie_no_free_proxy: true,
  risk_auto_direct_fallback: false,
  risk_manual_direct_fallback: true,
  mask_proxy_logs: false,
  proxy_protocol_order: 'http>https>socks5>socks4',
})

const goToProviders = () => {
  router.push('/dynamic-providers')
}

const loadConfig = async () => {
  try {
    const res = await configApi.get()
    const data = res.data || {}
    form.dyn_proxy_enable = !!data.dyn_proxy_enable
    form.dyn_proxy_new_account = !!data.dyn_proxy_new_account
    form.dyn_proxy_existing_account = !!data.dyn_proxy_existing_account
    form.dyn_proxy_sticky_minutes = data.dyn_proxy_sticky_minutes || 5
    form.risk_free_proxy_auto = !!data.risk_free_proxy_auto
    form.risk_free_proxy_manual = !!data.risk_free_proxy_manual
    form.risk_cookie_no_free_proxy = !!data.risk_cookie_no_free_proxy
    form.risk_auto_direct_fallback = !!data.risk_auto_direct_fallback
    form.risk_manual_direct_fallback = !!data.risk_manual_direct_fallback
    form.mask_proxy_logs = !!data.mask_proxy_logs
    form.proxy_protocol_order = data.proxy_protocol_order || 'http>https>socks5>socks4'
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
.back-link {
  display: inline-flex;
  align-items: center;
  color: var(--accent);
  text-decoration: none;
  font-size: 13px;
}
.back-link:hover {
  text-decoration: underline;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
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
</style>
