<template>
  <div>
    <!-- Back link -->
    <RouterLink to="/settings-hub" class="back-link">
      {{ t('settings.backToSettings') }}
    </RouterLink>

    <div class="page-header">
      <div class="page-title">{{ t('nav.settingsProxy') }}</div>
      <div class="page-desc">{{ t('settings.hubProxyDesc') }}</div>
    </div>

    <!-- Proxy status card -->
    <NCard>
      <div class="flex items-center gap-6">
        <!-- Status indicator -->
        <div class="flex items-center gap-3">
          <div
            class="status-dot"
            :class="status.running ? 'status-dot--running' : 'status-dot--stopped'"
          ></div>
          <div>
            <div class="text-sm font-semibold" style="color: var(--text)">
              {{ status.running ? t('settings.proxyRunning') : t('settings.proxyStopped') }}
            </div>
            <div v-if="status.running && status.port" class="text-xs text-dim">
              {{ t('settings.proxyPort') }}: {{ status.port }}
            </div>
          </div>
        </div>

        <!-- Toggle switch + Action buttons -->
        <div class="flex gap-3 items-center ml-auto">
          <NSwitch
            :value="configForm.proxy_sniffer_enabled"
            :loading="switchingEnabled"
            size="large"
            @update:value="toggleEnabled"
          />
          <NButton
            v-if="!status.running"
            type="primary"
            :loading="enabling"
            :disabled="!configForm.proxy_sniffer_enabled"
            @click="enableProxy"
          >
            {{ t('settings.enableProxy') }}
          </NButton>
          <NButton
            v-else
            :loading="disabling"
            @click="disableProxy"
          >
            {{ t('settings.disableProxy') }}
          </NButton>
        </div>
      </div>
      <div v-if="!configForm.proxy_sniffer_enabled" class="text-xs text-dim mt-2">
        {{ t('settings.proxySnifferDefaultOff') }}
      </div>
    </NCard>

    <!-- System proxy -->
    <NCard :title="t('settings.systemHttpProxy')">
      <NFormItem :label="t('settings.systemHttpProxy')" path="system_proxy">
        <NSwitch
          :value="status.system_proxy"
          :loading="switchingProxy"
          @update:value="toggleSystemProxy"
        />
      </NFormItem>
      <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
        {{ t('settings.systemProxyHint') }}
      </div>

      <NFormItem :label="t('settings.caCert')" path="cert">
        <div class="flex flex-col gap-2">
          <NTag v-if="status.ca_cert_installed" type="success" size="small">
            {{ t('settings.caCertInstalled') }}
          </NTag>
          <NTag v-else type="warning" size="small">
            {{ t('settings.caCertNotInstalled') }}
          </NTag>
          <NButton size="small" :loading="installingCert" @click="installCert">
            {{ t('settings.installCert') }}
          </NButton>
        </div>
      </NFormItem>
    </NCard>

    <!-- Port config -->
    <NCard :title="t('settings.proxyPort')">
      <NFormItem :label="t('settings.proxyPort')" path="port">
        <NInputNumber
          v-model:value="configForm.proxy_sniffer_port"
          :min="1024"
          :max="65535"
          style="width: 160px"
        />
      </NFormItem>
      <NButton type="primary" :loading="saving" @click="saveConfig">
        {{ t('config.saveConfig') }}
      </NButton>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import {
  NForm, NFormItem, NInputNumber, NButton, NCard,
  NSwitch, NTag, useMessage,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import configApi, { ProxyStatus, AppConfig } from '@/api/config'

const { t } = useI18n()
const message = useMessage()

const status = reactive<ProxyStatus & { system_proxy?: boolean }>({
  running: false,
  system_proxy: false,
})
const enabling = ref(false)
const disabling = ref(false)
const switchingProxy = ref(false)
const switchingEnabled = ref(false)
const installingCert = ref(false)
const saving = ref(false)

const configForm = reactive<AppConfig>({
  proxy_sniffer_enabled: false,
  proxy_sniffer_port: 8899,
})

const loadStatus = async () => {
  try {
    const res = await configApi.getProxyStatus()
    status.running = res.data?.running || false
    status.port = res.data?.port
    status.ca_cert_installed = res.data?.ca_cert_installed
  } catch {
    // silently fail
  }
}

const loadConfig = async () => {
  try {
    const res = await configApi.get()
    const data = res.data || {}
    configForm.proxy_sniffer_enabled = data.proxy_sniffer_enabled ?? false
    configForm.proxy_sniffer_port = data.proxy_sniffer_port || 8899
  } catch {
    // silently fail
  }
}

const enableProxy = async () => {
  enabling.value = true
  try {
    await configApi.enableProxy()
    message.success(t('settings.proxyEnabled'))
    await loadStatus()
  } catch {
    message.error(t('settings.proxyEnableFailed'))
  } finally {
    enabling.value = false
  }
}

const disableProxy = async () => {
  disabling.value = true
  try {
    await configApi.disableProxy()
    message.success(t('settings.proxyDisabled'))
    await loadStatus()
  } catch {
    message.error(t('settings.proxyDisableFailed'))
  } finally {
    disabling.value = false
  }
}

const toggleEnabled = async (val: boolean) => {
  switchingEnabled.value = true
  try {
    // Save config
    await configApi.save({ proxy_sniffer_enabled: val } as AppConfig)
    configForm.proxy_sniffer_enabled = val
    // Start or stop proxy accordingly
    if (val && !status.running) {
      await configApi.enableProxy()
      message.success(t('settings.proxyEnabled'))
    } else if (!val && status.running) {
      await configApi.disableProxy()
      message.success(t('settings.proxyDisabled'))
    }
    await loadStatus()
  } catch {
    message.error(t('settings.saveFailed'))
  } finally {
    switchingEnabled.value = false
  }
}

const toggleSystemProxy = async (val: boolean) => {
  switchingProxy.value = true
  try {
    await configApi.setSystemProxy(val)
    status.system_proxy = val
    message.success(val ? t('settings.systemProxyEnabled') : t('settings.systemProxyDisabled'))
  } catch {
    message.error('操作失败')
  } finally {
    switchingProxy.value = false
  }
}

const installCert = async () => {
  installingCert.value = true
  try {
    await configApi.installCert()
    message.success(t('settings.caCertInstallSuccess'))
    await loadStatus()
  } catch {
    message.error(t('settings.caCertInstallFailed'))
  } finally {
    installingCert.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await configApi.save({
      proxy_sniffer_port: configForm.proxy_sniffer_port,
    } as AppConfig)
    message.success(t('settings.saved'))
  } catch {
    message.error(t('settings.saveFailed'))
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadConfig()
  await loadStatus()
  // If config says enabled but proxy not running, auto-start it
  if (configForm.proxy_sniffer_enabled && !status.running) {
    try {
      await configApi.enableProxy()
      await loadStatus()
    } catch {
      // ignore
    }
  }
})
</script>

<style scoped>
.status-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot--running {
  background: var(--success);
  box-shadow: 0 0 6px var(--success);
}
.status-dot--stopped {
  background: var(--text-dim);
}
</style>
