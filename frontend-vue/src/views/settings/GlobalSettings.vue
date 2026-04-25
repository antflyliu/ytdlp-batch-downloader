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
          <NInput v-model:value="form.feishu_webhook" :placeholder="t('settings.feishuHint')" />
        </NFormItem>

        <NFormItem :label="t('settings.dingtalkWebhook')" path="dingtalk_webhook">
          <NInput v-model:value="form.dingtalk_webhook" />
        </NFormItem>
        <NFormItem :label="t('settings.dingtalkSecret')" path="dingtalk_secret_global">
          <NInput v-model:value="form.dingtalk_secret_global" :placeholder="t('config.dingtalkSecretGlobalHint')" />
        </NFormItem>

        <NFormItem :label="t('settings.wecomWebhook')" path="wecom_webhook">
          <NInput v-model:value="form.wecom_webhook" />
        </NFormItem>

        <NFormItem :label="t('settings.telegramBotToken')" path="telegram_bot_token">
          <NInput v-model:value="form.telegram_bot_token" :placeholder="t('config.telegramBotTokenHint')" />
        </NFormItem>
        <NFormItem :label="t('settings.telegramChatId')" path="telegram_chat_id">
          <NInput v-model:value="form.telegram_chat_id" :placeholder="t('config.telegramChatIdHint')" />
        </NFormItem>
      </NCard>

      <NButton type="primary" :loading="saving" @click="save">
        {{ t('config.saveConfig') }}
      </NButton>
    </NForm>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { NForm, NFormItem, NInput, NButton, NCard, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import configApi, { AppConfig } from '@/api/config'

const { t } = useI18n()
const message = useMessage()

const saving = ref(false)

const form = reactive<AppConfig>({
  feishu_webhook: '',
  dingtalk_webhook: '',
  dingtalk_secret_global: '',
  wecom_webhook: '',
  telegram_bot_token: '',
  telegram_chat_id: '',
})

const loadConfig = async () => {
  try {
    const res = await configApi.get()
    const data = res.data || {}
    form.feishu_webhook = data.feishu_webhook || ''
    form.dingtalk_webhook = data.dingtalk_webhook || ''
    form.dingtalk_secret_global = data.dingtalk_secret_global || ''
    form.wecom_webhook = data.wecom_webhook || ''
    form.telegram_bot_token = data.telegram_bot_token || ''
    form.telegram_chat_id = data.telegram_chat_id || ''
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

