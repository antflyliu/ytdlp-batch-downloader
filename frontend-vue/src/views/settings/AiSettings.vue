<template>
  <div>
    <!-- Back link -->
    <RouterLink to="/settings-hub" class="back-link">
      {{ t('settings.backToSettings') }}
    </RouterLink>

    <div class="page-header">
      <div class="page-title">{{ t('settings.aiTitle') }}</div>
      <div class="page-desc">{{ t('settings.aiDesc') }}</div>
    </div>

    <NForm ref="formRef" :model="form" label-placement="left" label-width="180">
      <!-- LLM Provider -->
      <NCard :title="t('config.llmProvider')">
        <NFormItem :label="t('config.llmProvider')" path="llm_provider">
          <NSelect
            v-model:value="form.llm_provider"
            :options="providerOptions"
            style="width: 240px"
          />
        </NFormItem>

        <NFormItem :label="t('config.llmApiKey')" path="llm_api_key">
          <NInput
            v-model:value="llmApiKeyInput"
            type="password"
            show-password-on="click"
            :placeholder="llmApiKeyPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('config.llmModel')" path="llm_model">
          <NInput
            v-model:value="form.llm_model"
            :placeholder="t('config.llmModelHint')"
          />
        </NFormItem>

        <NFormItem :label="t('config.llmBaseUrl')" path="llm_base_url">
          <NInput
            v-model:value="form.llm_base_url"
            :placeholder="t('config.llmBaseUrlHint')"
          />
        </NFormItem>
      </NCard>

      <!-- Clip Settings -->
      <NCard :title="t('settings.aiTitle')">
        <NFormItem :label="t('config.llmCategory')" path="llm_category">
          <NSelect
            v-model:value="form.llm_category"
            :options="categoryOptions"
            style="width: 240px"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.llmCategoryHint') }}
        </div>

        <NFormItem :label="t('config.llmMinScore')" path="llm_min_score">
          <NInputNumber
            v-model:value="form.llm_min_score"
            :min="1"
            :max="10"
            style="width: 120px"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.llmMinScoreHint') }}
        </div>
      </NCard>

      <!-- Clip Enhance -->
      <NCard :title="t('config.clipEnhanceFeatures')">
        <NFormItem :label="t('config.clipEmbedThumbnail')" path="clip_embed_thumbnail">
          <NSwitch v-model:value="form.clip_embed_thumbnail" />
        </NFormItem>

        <NFormItem :label="t('config.clipEmbedSubtitle')" path="clip_embed_subtitle">
          <NSwitch v-model:value="form.clip_embed_subtitle" />
        </NFormItem>

        <NFormItem :label="t('config.clipAdaptAspectRatio')" path="clip_adapt_aspect_ratio">
          <NSwitch v-model:value="form.clip_adapt_aspect_ratio" />
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
import {
  NForm, NFormItem, NInput, NInputNumber, NButton, NCard,
  NSelect, NSwitch, useMessage,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import configApi, { AppConfig } from '@/api/config'

const { t } = useI18n()
const message = useMessage()

const MASKED_SECRET_VALUE = '***'
const saving = ref(false)
const llmApiKeyInput = ref('')
const hasSavedLlmApiKey = ref(false)

const llmApiKeyPlaceholder = computed(() => (
  hasSavedLlmApiKey.value
    ? t('settings.llmApiKeySavedPlaceholder')
    : t('settings.llmApiKey')
))

const providerOptions = [
  { label: t('config.llmQwen'), value: 'qwen' },
  { label: t('config.llmOpenai'), value: 'openai' },
  { label: t('config.llmOllama'), value: 'ollama' },
  { label: t('config.llmGroq'), value: 'groq' },
]

const categoryOptions = [
  { label: t('config.llmCatEntertainment'), value: 'entertainment' },
  { label: t('config.llmCatNews'), value: 'news' },
  { label: t('config.llmCatKnowledge'), value: 'knowledge' },
  { label: t('config.llmCatVlog'), value: 'vlog' },
]

const form = reactive<AppConfig>({
  llm_provider: 'qwen',
  llm_api_key: '',
  llm_model: '',
  llm_base_url: '',
  llm_category: 'entertainment',
  llm_min_score: 5,
  clip_embed_thumbnail: false,
  clip_embed_subtitle: false,
  clip_adapt_aspect_ratio: false,
  clip_thumbnail_quality: 2,
  auto_clip_enabled: false,
  auto_clip_notify_enabled: false,
})

const loadConfig = async () => {
  try {
    const res = await configApi.get()
    const data = res.data || {}
    form.llm_provider = data.llm_provider || 'qwen'
    const loadedLlmApiKey = data.llm_api_key || ''
    hasSavedLlmApiKey.value = loadedLlmApiKey === MASKED_SECRET_VALUE
    llmApiKeyInput.value = hasSavedLlmApiKey.value ? '' : loadedLlmApiKey
    form.llm_api_key = hasSavedLlmApiKey.value ? MASKED_SECRET_VALUE : loadedLlmApiKey
    form.llm_model = data.llm_model || ''
    form.llm_base_url = data.llm_base_url || ''
    form.llm_category = data.llm_category || 'entertainment'
    form.llm_min_score = data.llm_min_score || 5
    form.clip_embed_thumbnail = !!data.clip_embed_thumbnail
    form.clip_embed_subtitle = !!data.clip_embed_subtitle
    form.clip_adapt_aspect_ratio = !!data.clip_adapt_aspect_ratio
    form.clip_thumbnail_quality = data.clip_thumbnail_quality ?? 2
    form.auto_clip_enabled = !!data.auto_clip_enabled
    form.auto_clip_notify_enabled = !!data.auto_clip_notify_enabled
  } catch {
    message.error(t('settings.loadFailed'))
  }
}

const save = async () => {
  saving.value = true
  try {
    const payload: AppConfig = {
      ...form,
      llm_api_key: llmApiKeyInput.value,
    }
    if (hasSavedLlmApiKey.value && !llmApiKeyInput.value) {
      payload.llm_api_key = MASKED_SECRET_VALUE
    }
    await configApi.save(payload)
    if (payload.llm_api_key) {
      hasSavedLlmApiKey.value = true
      llmApiKeyInput.value = ''
      form.llm_api_key = MASKED_SECRET_VALUE
    } else {
      hasSavedLlmApiKey.value = false
      form.llm_api_key = ''
    }
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
