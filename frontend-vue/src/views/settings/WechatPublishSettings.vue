<template>
  <div class="wechat-settings-page">
    <RouterLink to="/settings-hub" class="back-link">
      {{ t('settings.backToSettings') }}
    </RouterLink>

    <div class="page-header">
      <div class="page-title">{{ t('wechatPublish.title') }}</div>
      <div class="page-desc">{{ t('wechatPublish.desc') }}</div>
    </div>

    <NForm :model="form" label-placement="left" label-width="180">
      <NCard :title="t('wechatPublish.credentials')">
        <NFormItem :label="t('wechatPublish.appId')" path="wechat_app_id">
          <NInput v-model:value="form.wechat_app_id" :placeholder="t('wechatPublish.appIdHint')" />
        </NFormItem>

        <NFormItem :label="t('wechatPublish.appSecret')" path="wechat_app_secret">
          <NInput
            v-model:value="wechatAppSecretInput"
            type="password"
            show-password-on="click"
            :placeholder="wechatAppSecretPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('wechatPublish.defaultAuthor')" path="wechat_default_author">
          <NInput v-model:value="form.wechat_default_author" />
        </NFormItem>
      </NCard>

      <NCard :title="t('wechatCollect.title')">
        <NFormItem :label="t('wechatCollect.baseUrl')" path="wechat_exporter_base_url">
          <NInput v-model:value="form.wechat_exporter_base_url" />
        </NFormItem>

        <NFormItem :label="t('wechatCollect.authKey')" path="wechat_exporter_auth_key">
          <NInput
            v-model:value="wechatExporterAuthKeyInput"
            type="password"
            show-password-on="click"
            :placeholder="wechatExporterAuthKeyPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('wechatCollect.outputDir')" path="wechat_collection_output_dir">
          <NInput v-model:value="form.wechat_collection_output_dir" />
        </NFormItem>

        <NFormItem :label="t('wechatCollect.defaultFormat')" path="wechat_collection_default_format">
          <NSelect v-model:value="form.wechat_collection_default_format" :options="collectFormatOptions" style="width: 220px" />
        </NFormItem>

        <NFormItem :label="t('wechatCollect.maxArticles')" path="wechat_collection_max_articles">
          <NInputNumber v-model:value="form.wechat_collection_max_articles" :min="1" :max="1000" :show-button="false" style="width: 220px" />
        </NFormItem>

        <NFormItem :label="t('wechatCollect.delaySeconds')" path="wechat_collection_delay_seconds">
          <NInputNumber v-model:value="form.wechat_collection_delay_seconds" :min="0" :max="30" :step="0.5" :show-button="false" style="width: 220px" />
        </NFormItem>
      </NCard>

      <NCard :title="t('wechatPublish.publishDefaults')">
        <NFormItem :label="t('wechatPublish.theme')" path="wechat_default_theme">
          <NSelect v-model:value="form.wechat_default_theme" :options="themeOptions" style="width: 220px" />
        </NFormItem>

        <NFormItem :label="t('wechatPublish.color')" path="wechat_default_color">
          <NSelect v-model:value="form.wechat_default_color" :options="colorOptions" style="width: 220px" />
        </NFormItem>

        <NFormItem :label="t('wechatPublish.markdownRenderer')" path="wechat_markdown_renderer">
          <NSelect v-model:value="form.wechat_markdown_renderer" :options="rendererOptions" style="width: 260px" />
        </NFormItem>

        <NFormItem :label="t('wechatPublish.baoyuScript')" path="wechat_baoyu_markdown_to_html_script">
          <NInput
            v-model:value="form.wechat_baoyu_markdown_to_html_script"
            :placeholder="t('wechatPublish.baoyuScriptHint')"
          />
        </NFormItem>

        <NFormItem :label="t('wechatPublish.needOpenComment')" path="wechat_need_open_comment">
          <NSwitch v-model:value="form.wechat_need_open_comment" />
        </NFormItem>

        <NFormItem :label="t('wechatPublish.onlyFansCanComment')" path="wechat_only_fans_can_comment">
          <NSwitch v-model:value="form.wechat_only_fans_can_comment" />
        </NFormItem>

        <NFormItem :label="t('wechatPublish.aiCover')" path="wechat_baoyu_ai_cover">
          <NSwitch v-model:value="form.wechat_baoyu_ai_cover" />
        </NFormItem>

        <NFormItem :label="t('wechatPublish.layoutModules')" path="wechat_baoyu_layout_modules">
          <NSwitch v-model:value="form.wechat_baoyu_layout_modules" />
        </NFormItem>
      </NCard>

      <div class="settings-actions">
        <NButton type="primary" :loading="saving" @click="save">
          {{ t('config.saveConfig') }}
        </NButton>
      </div>
    </NForm>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NCard, NForm, NFormItem, NInput, NInputNumber, NSelect, NSwitch, useMessage } from 'naive-ui'
import configApi, { type AppConfig } from '@/api/config'
import wechatPublishApi from '@/api/wechatPublish'

const { t } = useI18n()
const message = useMessage()

const MASKED_SECRET_VALUE = '***'
const saving = ref(false)
const hasSavedSecret = ref(false)
const hasSavedExporterAuthKey = ref(false)
const wechatAppSecretInput = ref('')
const wechatExporterAuthKeyInput = ref('')

const form = reactive<AppConfig>({
  wechat_app_id: '',
  wechat_app_secret: '',
  wechat_default_author: '',
  wechat_default_theme: 'default',
  wechat_default_color: 'blue',
  wechat_markdown_renderer: 'auto',
  wechat_baoyu_markdown_to_html_script: '',
  wechat_need_open_comment: true,
  wechat_only_fans_can_comment: false,
  wechat_baoyu_ai_cover: false,
  wechat_baoyu_layout_modules: true,
  wechat_exporter_base_url: 'https://down.mptext.top',
  wechat_exporter_auth_key: '',
  wechat_collection_output_dir: '',
  wechat_collection_default_format: 'markdown',
  wechat_collection_delay_seconds: 1,
  wechat_collection_max_articles: 50,
})

const wechatAppSecretPlaceholder = computed(() => (
  hasSavedSecret.value ? t('wechatPublish.secretSavedPlaceholder') : t('wechatPublish.appSecretHint')
))

const wechatExporterAuthKeyPlaceholder = computed(() => (
  hasSavedExporterAuthKey.value ? t('wechatPublish.secretSavedPlaceholder') : t('wechatCollect.authKeyPlaceholder')
))

const themeOptions = computed(() => [
  { label: t('wechatPublish.themeDefault'), value: 'default' },
  { label: t('wechatPublish.themeGrace'), value: 'grace' },
  { label: t('wechatPublish.themeSimple'), value: 'simple' },
  { label: t('wechatPublish.themeModern'), value: 'modern' },
])

// 堡鱼主题列表
const WECHAT_BAOYU_THEMES = [
  'default', 'grace', 'simple', 'modern',
] as const
type WechatBaoyuTheme = typeof WECHAT_BAOYU_THEMES[number]

const colorOptions = [
  'blue', 'green', 'vermilion', 'yellow', 'purple', 'sky',
  'rose', 'olive', 'black', 'gray', 'pink', 'red', 'orange',
].map((value) => ({ label: value, value }))

const rendererOptions = computed(() => [
  { label: t('wechatPublish.rendererAuto'), value: 'auto' },
  { label: t('wechatPublish.rendererBaoyu'), value: 'baoyu-markdown-to-html' },
  { label: t('wechatPublish.rendererLocal'), value: 'local' },
])

const normalizeRenderer = (value?: string) => (
  value === 'baoyu' ? 'baoyu-markdown-to-html' : (value || 'auto')
)

const collectFormatOptions = [
  { label: 'Markdown', value: 'markdown' },
  { label: 'HTML', value: 'html' },
  { label: 'Text', value: 'text' },
  { label: 'JSON', value: 'json' },
]

const load = async () => {
  try {
    const [publishRes, configRes] = await Promise.all([
      wechatPublishApi.getConfig(),
      configApi.get(),
    ])
    const data = publishRes.data || {}
    const fullConfig = configRes.data || {}
    form.wechat_app_id = data.wechat_app_id || ''
    form.wechat_default_author = data.wechat_default_author || ''
    form.wechat_default_theme = data.wechat_default_theme || 'default'
    form.wechat_default_color = data.wechat_default_color || 'blue'
    form.wechat_markdown_renderer = normalizeRenderer(data.wechat_markdown_renderer || fullConfig.wechat_markdown_renderer)
    form.wechat_baoyu_markdown_to_html_script = (
      data.wechat_baoyu_markdown_to_html_script
      || fullConfig.wechat_baoyu_markdown_to_html_script
      || ''
    )
    form.wechat_need_open_comment = data.wechat_need_open_comment ?? true
    form.wechat_only_fans_can_comment = data.wechat_only_fans_can_comment ?? false
    form.wechat_exporter_base_url = fullConfig.wechat_exporter_base_url || 'https://down.mptext.top'
    form.wechat_collection_output_dir = fullConfig.wechat_collection_output_dir || ''
    form.wechat_collection_default_format = fullConfig.wechat_collection_default_format || 'markdown'
    form.wechat_collection_delay_seconds = Number(fullConfig.wechat_collection_delay_seconds ?? 1)
    form.wechat_collection_max_articles = Number(fullConfig.wechat_collection_max_articles || 50)
    hasSavedSecret.value = Boolean(data.configured)
    hasSavedExporterAuthKey.value = Boolean(fullConfig.wechat_exporter_auth_key)
    form.wechat_app_secret = hasSavedSecret.value ? MASKED_SECRET_VALUE : ''
    form.wechat_exporter_auth_key = hasSavedExporterAuthKey.value ? MASKED_SECRET_VALUE : ''
    wechatAppSecretInput.value = ''
    wechatExporterAuthKeyInput.value = ''
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('settings.loadFailed'))
  }
}

const save = async () => {
  saving.value = true
  try {
    const current = (await configApi.get()).data || {}
    const payload: AppConfig = {
      ...current,
      ...form,
      wechat_app_secret: hasSavedSecret.value && !wechatAppSecretInput.value
        ? MASKED_SECRET_VALUE
        : wechatAppSecretInput.value,
      wechat_exporter_auth_key: hasSavedExporterAuthKey.value && !wechatExporterAuthKeyInput.value
        ? MASKED_SECRET_VALUE
        : wechatExporterAuthKeyInput.value,
    }
    await configApi.save(payload)
    hasSavedSecret.value = Boolean(payload.wechat_app_secret)
    hasSavedExporterAuthKey.value = Boolean(payload.wechat_exporter_auth_key)
    form.wechat_app_secret = hasSavedSecret.value ? MASKED_SECRET_VALUE : ''
    form.wechat_exporter_auth_key = hasSavedExporterAuthKey.value ? MASKED_SECRET_VALUE : ''
    wechatAppSecretInput.value = ''
    wechatExporterAuthKeyInput.value = ''
    message.success(t('settings.saved'))
  } catch (error: any) {
    message.error(error?.response?.data?.error || error?.message || t('settings.saveFailed'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.wechat-settings-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.settings-actions {
  display: flex;
  justify-content: flex-start;
}

@media (max-width: 720px) {
  .wechat-settings-page :deep(.n-form-item) {
    --n-label-width: auto;
  }
}
</style>
