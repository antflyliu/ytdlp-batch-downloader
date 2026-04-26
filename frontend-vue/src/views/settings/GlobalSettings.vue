<template>
  <div>
    <!-- Back link -->
    <RouterLink to="/settings-hub" class="back-link">
      {{ t('settings.backToSettings') }}
    </RouterLink>

    <div class="page-header">
      <div class="page-title">{{ t('settings.hubTitle') }}</div>
      <div class="page-desc">{{ t('settings.notifyDesc') }}</div>
    </div>

    <NForm ref="formRef" :model="form" label-placement="left" label-width="180">
      <NCard :title="t('settings.notifyChannel')">
        <NFormItem :label="t('settings.feishuWebhook')" path="feishu_webhook">
          <NInput v-model:value="form.global_feishu_url" :placeholder="t('settings.feishuHint')" />
        </NFormItem>

        <NFormItem :label="t('settings.dingtalkWebhook')" path="dingtalk_webhook">
          <NInput v-model:value="form.global_dingtalk_url" />
        </NFormItem>
        <NFormItem :label="t('settings.dingtalkSecret')" path="dingtalk_secret_global">
          <NInput
            v-model:value="dingtalkSecretInput"
            type="password"
            show-password-on="click"
            :placeholder="dingtalkSecretPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('settings.wecomWebhook')" path="wecom_webhook">
          <NInput v-model:value="form.global_wecom_url" />
        </NFormItem>

        <NFormItem :label="t('settings.telegramBotToken')" path="telegram_bot_token">
          <NInput
            v-model:value="telegramTokenInput"
            type="password"
            show-password-on="click"
            :placeholder="telegramTokenPlaceholder"
          />
        </NFormItem>
        <NFormItem :label="t('settings.telegramChatId')" path="telegram_chat_id">
          <NInput v-model:value="form.global_telegram_chat_id" :placeholder="t('config.telegramChatIdHint')" />
        </NFormItem>
      </NCard>

      <NButton type="primary" :loading="saving" @click="save">
        {{ t('config.saveConfig') }}
      </NButton>
    </NForm>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { NForm, NFormItem, NInput, NButton, NCard, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import configApi, { AppConfig } from '@/api/config'

const { t } = useI18n()
const message = useMessage()

const MASKED_SECRET_VALUE = '***'
const saving = ref(false)
const dingtalkSecretInput = ref('')
const telegramTokenInput = ref('')
const hasSavedDingtalkSecret = ref(false)
const hasSavedTelegramToken = ref(false)

const dingtalkSecretPlaceholder = computed(() => (
  hasSavedDingtalkSecret.value
    ? t('settings.secretSavedPlaceholder')
    : t('config.dingtalkSecretGlobalHint')
))

const telegramTokenPlaceholder = computed(() => (
  hasSavedTelegramToken.value
    ? t('settings.secretSavedPlaceholder')
    : t('config.telegramBotTokenHint')
))

const form = reactive<AppConfig>({
  global_feishu_url: '',
  global_dingtalk_url: '',
  global_dingtalk_sign_secret: '',
  global_wecom_url: '',
  global_telegram_token: '',
  global_telegram_chat_id: '',
})

const loadConfig = async () => {
  try {
    const res = await configApi.get()
    const data = res.data || {}
    form.global_feishu_url = data.global_feishu_url || ''
    form.global_dingtalk_url = data.global_dingtalk_url || ''
    const loadedDingtalkSecret = data.global_dingtalk_sign_secret || ''
    hasSavedDingtalkSecret.value = loadedDingtalkSecret === MASKED_SECRET_VALUE
    dingtalkSecretInput.value = hasSavedDingtalkSecret.value ? '' : loadedDingtalkSecret
    form.global_dingtalk_sign_secret = hasSavedDingtalkSecret.value
      ? MASKED_SECRET_VALUE
      : loadedDingtalkSecret
    form.global_wecom_url = data.global_wecom_url || ''
    const loadedTelegramToken = data.global_telegram_token || ''
    hasSavedTelegramToken.value = loadedTelegramToken === MASKED_SECRET_VALUE
    telegramTokenInput.value = hasSavedTelegramToken.value ? '' : loadedTelegramToken
    form.global_telegram_token = hasSavedTelegramToken.value
      ? MASKED_SECRET_VALUE
      : loadedTelegramToken
    form.global_telegram_chat_id = data.global_telegram_chat_id || ''
  } catch {
    message.error(t('settings.loadFailed'))
  }
}

const buildPayload = (): AppConfig => {
  const payload: AppConfig = {
    ...form,
    global_dingtalk_sign_secret: dingtalkSecretInput.value,
    global_telegram_token: telegramTokenInput.value,
  }
  if (hasSavedDingtalkSecret.value && !dingtalkSecretInput.value) {
    payload.global_dingtalk_sign_secret = MASKED_SECRET_VALUE
  }
  if (hasSavedTelegramToken.value && !telegramTokenInput.value) {
    payload.global_telegram_token = MASKED_SECRET_VALUE
  }
  return payload
}

const syncSecretInputsAfterSave = (payload: AppConfig) => {
  if (payload.global_dingtalk_sign_secret) {
    hasSavedDingtalkSecret.value = true
    dingtalkSecretInput.value = ''
    form.global_dingtalk_sign_secret = MASKED_SECRET_VALUE
  } else {
    hasSavedDingtalkSecret.value = false
    form.global_dingtalk_sign_secret = ''
  }
  if (payload.global_telegram_token) {
    hasSavedTelegramToken.value = true
    telegramTokenInput.value = ''
    form.global_telegram_token = MASKED_SECRET_VALUE
  } else {
    hasSavedTelegramToken.value = false
    form.global_telegram_token = ''
  }
}

const save = async () => {
  saving.value = true
  try {
    const payload = buildPayload()
    await configApi.save(payload)
    syncSecretInputsAfterSave(payload)
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
