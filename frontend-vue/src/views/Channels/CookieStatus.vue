<template>
  <div class="sph-config-grid">
    <!-- 状态卡片 -->
    <div class="sph-status-card">
      <div :class="dotClass" />
      <div style="flex:1; min-width:0;">
        <div style="font-weight:600;">{{ statusText }}</div>
        <div v-if="store.status?.preview" class="meta-row meta-row--dim">
          {{ store.status.preview }}
        </div>
      </div>
    </div>

    <!-- 手动更新 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">
            <NIcon><CreateOutline /></NIcon>
          </div>
          <span>{{ t('channels.manualUpdate') }}</span>
        </div>
      </div>
      <div class="card-body">
        <div class="form-hint">{{ t('channels.manualUpdateHint') }}</div>
        <NInput
          v-model:value="manualCookie"
          type="textarea"
          :rows="4"
          placeholder="hy_source=web; hy_user=xxx; hy_token=xxx"
        />
        <div style="margin-top: 12px; display: flex; gap: 8px;">
          <NButton type="primary" :loading="saving" @click="onSave">
            {{ t('channels.save') }}
          </NButton>
        </div>
        <div v-if="errorMsg" style="color: var(--error); font-size: 12px; margin-top: 8px;">
          {{ errorMsg }}
        </div>
      </div>
    </div>

    <!-- Playwright 自动刷新 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">
            <NIcon><Refresh /></NIcon>
          </div>
          <span>{{ t('channels.autoRefresh') }}</span>
        </div>
      </div>
      <div class="card-body">
        <div class="form-hint">{{ t('channels.autoRefreshHint') }}</div>
        <div style="display: flex; align-items: center; gap: 12px; margin-top: 8px;">
          <span class="meta-row">
            刷新状态: <strong>{{ store.refreshState.state }}</strong>
            <span v-if="store.refreshState.pid" style="margin-left: 8px;">
              PID: {{ store.refreshState.pid }}
            </span>
          </span>
          <NButton
            v-if="store.refreshState.state === 'idle'"
            type="primary"
            @click="onStartRefresh"
          >
            {{ t('channels.startRefresh') }}
          </NButton>
          <NButton
            v-else-if="store.refreshState.state === 'running'"
            @click="onCancelRefresh"
          >
            {{ t('channels.cancelRefresh') }}
          </NButton>
        </div>
        <div v-if="store.refreshState.last_error" style="color: var(--error); font-size: 12px; margin-top: 8px;">
          {{ t('channels.refreshFailed', { error: store.refreshState.last_error }) }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { NButton, NIcon, NInput, useMessage } from 'naive-ui'
import { CreateOutline, Refresh } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useSphCookieStore } from '@/stores/sphCookie'

const { t } = useI18n()
const message = useMessage()
const store = useSphCookieStore()

const manualCookie = ref('')
const saving = ref(false)
const errorMsg = ref('')

const dotClass = computed(() => {
  if (!store.status?.exists) return 'sph-status-card__dot sph-status-card__dot--err'
  return 'sph-status-card__dot sph-status-card__dot--ok'
})

const statusText = computed(() => {
  if (!store.status?.exists) return t('channels.statusUnconfigured')
  return t('channels.statusConfigured')
})

async function onSave() {
  if (!manualCookie.value.trim()) {
    errorMsg.value = t('channels.invalidFormat')
    return
  }
  saving.value = true
  errorMsg.value = ''
  try {
    await store.saveCookie(manualCookie.value.trim())
    message.success(t('channels.refreshSuccess'))
    manualCookie.value = ''
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.error || e?.message || String(e)
  } finally {
    saving.value = false
  }
}

async function onStartRefresh() {
  try {
    await store.startRefresh()
    message.info(t('channels.refreshRunning', { pid: store.refreshState.pid || '?' }))
  } catch (e: any) {
    if (e?.response?.status === 409) {
      message.warning('已有刷新任务在跑')
    } else {
      message.error(e?.message || String(e))
    }
  }
}

async function onCancelRefresh() {
  try {
    await store.cancelRefresh()
  } catch (e: any) {
    message.error(e?.message || String(e))
  }
}

onMounted(() => {
  store.fetchStatus()
})
</script>
