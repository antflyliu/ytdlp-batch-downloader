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

      <NCard :title="t('config.articleWorkflow')">
        <NFormItem :label="t('config.whisperProvider')" path="whisper_provider">
          <NSelect
            v-model:value="form.whisper_provider"
            :options="whisperProviderOptions"
            style="width: 240px"
          />
        </NFormItem>

        <NFormItem :label="t('config.whisperBaseUrl')" path="whisper_base_url">
          <NInput v-model:value="form.whisper_base_url" :placeholder="t('config.whisperBaseUrlHint')" />
        </NFormItem>

        <NFormItem :label="t('config.whisperApiKey')" path="whisper_api_key">
          <NInput
            v-model:value="whisperApiKeyInput"
            type="password"
            show-password-on="click"
            :placeholder="whisperApiKeyPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('config.whisperModel')" path="whisper_model">
          <NInput v-model:value="form.whisper_model" />
        </NFormItem>

        <NFormItem :label="t('config.whisperLanguage')" path="whisper_language">
          <NSelect
            v-model:value="form.whisper_language"
            :options="whisperLanguageOptions"
            style="width: 240px"
          />
        </NFormItem>

        <NFormItem :label="t('config.whisperComputeType')" path="whisper_compute_type">
          <NSelect
            v-model:value="form.whisper_compute_type"
            :options="whisperComputeTypeOptions"
            style="width: 240px"
          />
        </NFormItem>

        <NFormItem :label="t('config.whisperDevice')" path="whisper_device">
          <NSelect
            v-model:value="form.whisper_device"
            :options="whisperDeviceOptions"
            style="width: 240px"
          />
        </NFormItem>

        <NFormItem :label="t('config.whisperChunkSeconds')" path="whisper_chunk_seconds">
          <NInputNumber
            v-model:value="form.whisper_chunk_seconds"
            :min="30"
            :max="60"
            :step="5"
            style="width: 140px"
          />
        </NFormItem>

        <NFormItem :label="t('config.articleOutputDir')" path="article_output_dir">
          <NInput v-model:value="form.article_output_dir" />
        </NFormItem>

        <NFormItem :label="t('config.articleToolsPath')" path="article_tools_path">
          <NInput v-model:value="form.article_tools_path" />
        </NFormItem>

        <NFormItem :label="t('config.articleTargetLang')" path="article_default_target_lang">
          <NInput v-model:value="form.article_default_target_lang" />
        </NFormItem>

        <NFormItem :label="t('config.articleSubtitleLanguages')" path="article_subtitle_languages">
          <NInput v-model:value="form.article_subtitle_languages" />
        </NFormItem>

        <NFormItem :label="t('config.articleSubtitleProxyMode')" path="article_subtitle_proxy_mode">
          <NSelect
            v-model:value="form.article_subtitle_proxy_mode"
            :options="subtitleProxyModeOptions"
            style="width: 240px"
          />
        </NFormItem>

        <NFormItem v-if="form.article_subtitle_proxy_mode === 'account_only'" :label="t('config.articleSubtitleProxyPool')" path="article_subtitle_proxy_pool_id">
          <NSelect
            v-model:value="form.article_subtitle_proxy_pool_id"
            :options="proxyPoolOptions"
            :loading="proxyPoolsLoading"
            placeholder=""
            clearable
            style="width: 240px"
          />
        </NFormItem>

        <NFormItem :label="t('config.articleAuthor')" path="article_author">
          <NInput v-model:value="form.article_author" />
        </NFormItem>
      </NCard>

      <NCard :title="t('config.gmailOAuthWorkflow')">
        <NAlert type="info" :bordered="false" class="mb-3">
          {{ t('config.gmailOAuthSetupHint') }}
        </NAlert>

        <NFormItem :label="t('config.gmailOAuthClientId')" path="gmail_oauth_client_id">
          <NInput
            v-model:value="form.gmail_oauth_client_id"
            :placeholder="t('config.gmailOAuthClientIdHint')"
          />
        </NFormItem>

        <NFormItem :label="t('config.gmailOAuthClientSecret')" path="gmail_oauth_client_secret">
          <NInput
            v-model:value="gmailOAuthClientSecretInput"
            type="password"
            show-password-on="click"
            :placeholder="gmailOAuthClientSecretPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('config.gmailOAuthRedirectUri')" path="gmail_oauth_redirect_uri">
          <NInput
            v-model:value="form.gmail_oauth_redirect_uri"
            :placeholder="t('config.gmailOAuthRedirectUriHint')"
          />
        </NFormItem>

        <NFormItem :label="t('config.gmailOAuthScopes')" path="gmail_oauth_scopes">
          <NInput
            v-model:value="form.gmail_oauth_scopes"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.gmailOAuthScopesHint') }}
        </div>
      </NCard>

      <NCard :title="t('config.videoGenerationWorkflow')">
        <NFormItem :label="t('config.comfyuiUrl')" path="comfyui_url">
          <NInput v-model:value="form.comfyui_url" :placeholder="t('config.comfyuiUrlHint')" />
        </NFormItem>

        <NFormItem :label="t('config.comfyuiApiKey')" path="comfyui_api_key">
          <NInput
            v-model:value="comfyuiApiKeyInput"
            type="password"
            show-password-on="click"
            :placeholder="comfyuiApiKeyPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('config.runninghubUrl')" path="runninghub_url">
          <NInput v-model:value="form.runninghub_url" />
        </NFormItem>

        <NFormItem :label="t('config.runninghubApiKey')" path="runninghub_api_key">
          <NInput
            v-model:value="runninghubApiKeyInput"
            type="password"
            show-password-on="click"
            :placeholder="runninghubApiKeyPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('config.ttsProvider')" path="tts_provider">
          <NSelect v-model:value="form.tts_provider" :options="ttsProviderOptions" style="width: 240px" />
        </NFormItem>

        <NFormItem :label="t('config.localTtsUrl')" path="local_tts_url">
          <NInput v-model:value="form.local_tts_url" />
        </NFormItem>

        <NFormItem :label="t('config.videoGenOutputDir')" path="video_gen_output_dir">
          <NInput v-model:value="form.video_gen_output_dir" />
        </NFormItem>

        <NFormItem :label="t('config.voiceProvider')" path="voice_provider">
          <NSelect v-model:value="form.voice_provider" :options="voiceProviderOptions" style="width: 280px" />
        </NFormItem>

        <NFormItem :label="t('config.voiceFallbackOrder')" path="voice_fallback_order">
          <NInput v-model:value="form.voice_fallback_order" :placeholder="t('config.voiceFallbackOrderHint')" />
        </NFormItem>

        <NFormItem :label="t('config.voiceFlowDefaults')" path="voice_flow_defaults_json">
          <NInput
            v-model:value="form.voice_flow_defaults_json"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            :placeholder="t('config.voiceFlowDefaultsHint')"
          />
        </NFormItem>

        <NFormItem :label="t('config.voiceOutputDir')" path="voice_output_dir">
          <NInput v-model:value="form.voice_output_dir" />
        </NFormItem>

        <NFormItem :label="t('config.voiceMaxTextChars')" path="voice_max_text_chars">
          <NInputNumber v-model:value="form.voice_max_text_chars" :min="100" :max="20000" :step="500" style="width: 140px" />
        </NFormItem>

        <NFormItem :label="t('config.voiceRequireDisclosure')" path="voice_require_disclosure">
          <NSwitch v-model:value="form.voice_require_disclosure" />
        </NFormItem>

        <NFormItem :label="t('config.voiceAllowReferenceClone')" path="voice_allow_reference_clone">
          <NSwitch v-model:value="form.voice_allow_reference_clone" />
        </NFormItem>

        <NFormItem :label="t('config.voiceAllowPromptTranscriptClone')" path="voice_allow_prompt_transcript_clone">
          <NSwitch v-model:value="form.voice_allow_prompt_transcript_clone" />
        </NFormItem>

        <NFormItem :label="t('config.transcriptionProvider')" path="transcription_provider">
          <NSelect v-model:value="form.transcription_provider" :options="transcriptionProviderOptions" style="width: 280px" />
        </NFormItem>

        <NFormItem :label="t('config.openaiSpeechApiKey')" path="openai_speech_api_key">
          <NInput v-model:value="openaiSpeechApiKeyInput" type="password" show-password-on="click" :placeholder="openaiSpeechApiKeyPlaceholder" />
        </NFormItem>

        <NFormItem :label="t('config.azureSpeechApiKey')" path="azure_speech_api_key">
          <NInput v-model:value="azureSpeechApiKeyInput" type="password" show-password-on="click" :placeholder="azureSpeechApiKeyPlaceholder" />
        </NFormItem>

        <NFormItem :label="t('config.minimaxSpeechApiKey')" path="minimax_speech_api_key">
          <NInput v-model:value="minimaxSpeechApiKeyInput" type="password" show-password-on="click" :placeholder="minimaxSpeechApiKeyPlaceholder" />
        </NFormItem>

        <NFormItem :label="t('config.voxcpmApiKey')" path="voxcpm_api_key">
          <NInput v-model:value="voxcpmApiKeyInput" type="password" show-password-on="click" :placeholder="voxcpmApiKeyPlaceholder" />
        </NFormItem>

        <NFormItem :label="t('config.vibevoiceTtsApiKey')" path="vibevoice_tts_api_key">
          <NInput v-model:value="vibevoiceTtsApiKeyInput" type="password" show-password-on="click" :placeholder="vibevoiceTtsApiKeyPlaceholder" />
        </NFormItem>

        <NFormItem :label="t('config.vibevoiceAsrApiKey')" path="vibevoice_asr_api_key">
          <NInput v-model:value="vibevoiceAsrApiKeyInput" type="password" show-password-on="click" :placeholder="vibevoiceAsrApiKeyPlaceholder" />
        </NFormItem>

        <NFormItem :label="t('config.defaultTemplate')" path="video_gen_default_template">
          <NInput v-model:value="form.video_gen_default_template" />
        </NFormItem>

        <NFormItem :label="t('config.defaultSceneCount')" path="video_gen_default_scene_count">
          <NInputNumber v-model:value="form.video_gen_default_scene_count" :min="1" :max="12" style="width: 120px" />
        </NFormItem>
      </NCard>

      <NCard :title="t('config.imageGenerationWorkflow')">
        <NFormItem :label="t('config.imageGenerationProvider')" path="image_generation_provider">
          <NSelect
            v-model:value="form.image_generation_provider"
            :options="imageProviderOptions"
            style="width: 240px"
          />
        </NFormItem>

        <NFormItem :label="t('config.imageGenerationFallbackOrder')" path="image_generation_fallback_order">
          <NInput
            v-model:value="form.image_generation_fallback_order"
            :placeholder="t('config.imageGenerationFallbackOrderHint')"
          />
        </NFormItem>

        <NFormItem :label="t('config.imageGenerationTimeout')" path="image_generation_timeout_seconds">
          <NInputNumber v-model:value="form.image_generation_timeout_seconds" :min="30" :max="900" style="width: 140px" />
        </NFormItem>

        <NFormItem :label="t('config.minimaxApiKey')" path="minimax_api_key">
          <NInput
            v-model:value="minimaxApiKeyInput"
            type="password"
            show-password-on="click"
            :placeholder="minimaxApiKeyPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('config.minimaxBaseUrl')" path="minimax_base_url">
          <NInput v-model:value="form.minimax_base_url" />
        </NFormItem>

        <NFormItem :label="t('config.minimaxImageModel')" path="minimax_image_model">
          <NInput v-model:value="form.minimax_image_model" />
        </NFormItem>

        <NFormItem :label="t('config.openaiImageApiKey')" path="openai_api_key">
          <NInput
            v-model:value="openaiApiKeyInput"
            type="password"
            show-password-on="click"
            :placeholder="openaiApiKeyPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('config.openaiBaseUrl')" path="openai_base_url">
          <NInput v-model:value="form.openai_base_url" />
        </NFormItem>

        <NFormItem :label="t('config.openaiImageModel')" path="openai_image_model">
          <NInput v-model:value="form.openai_image_model" />
        </NFormItem>

        <NFormItem :label="t('config.openaiImageSize')" path="openai_image_size">
          <NInput v-model:value="form.openai_image_size" />
        </NFormItem>

        <NFormItem :label="t('config.openaiImageQuality')" path="openai_image_quality">
          <NSelect v-model:value="form.openai_image_quality" :options="imageQualityOptions" style="width: 180px" />
        </NFormItem>

        <NFormItem :label="t('config.geminiApiKey')" path="gemini_api_key">
          <NInput
            v-model:value="geminiApiKeyInput"
            type="password"
            show-password-on="click"
            :placeholder="geminiApiKeyPlaceholder"
          />
        </NFormItem>

        <NFormItem :label="t('config.geminiBaseUrl')" path="gemini_base_url">
          <NInput v-model:value="form.gemini_base_url" />
        </NFormItem>

        <NFormItem :label="t('config.geminiImageModel')" path="gemini_image_model">
          <NInput v-model:value="form.gemini_image_model" />
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
  NSelect, NSwitch, NAlert, useMessage,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import configApi, { AppConfig } from '@/api/config'

const { t } = useI18n()
const message = useMessage()

const MASKED_SECRET_VALUE = '***'
const saving = ref(false)
const llmApiKeyInput = ref('')
const whisperApiKeyInput = ref('')
const comfyuiApiKeyInput = ref('')
const runninghubApiKeyInput = ref('')
const minimaxApiKeyInput = ref('')
const openaiApiKeyInput = ref('')
const geminiApiKeyInput = ref('')
const gmailOAuthClientSecretInput = ref('')
const openaiSpeechApiKeyInput = ref('')
const azureSpeechApiKeyInput = ref('')
const minimaxSpeechApiKeyInput = ref('')
const voxcpmApiKeyInput = ref('')
const vibevoiceTtsApiKeyInput = ref('')
const vibevoiceAsrApiKeyInput = ref('')
const hasSavedLlmApiKey = ref(false)
const hasSavedWhisperApiKey = ref(false)
const hasSavedComfyuiApiKey = ref(false)
const hasSavedRunninghubApiKey = ref(false)
const hasSavedMinimaxApiKey = ref(false)
const hasSavedOpenaiApiKey = ref(false)
const hasSavedGeminiApiKey = ref(false)
const hasSavedGmailOAuthClientSecret = ref(false)
const hasSavedOpenaiSpeechApiKey = ref(false)
const hasSavedAzureSpeechApiKey = ref(false)
const hasSavedMinimaxSpeechApiKey = ref(false)
const hasSavedVoxcpmApiKey = ref(false)
const hasSavedVibevoiceTtsApiKey = ref(false)
const hasSavedVibevoiceAsrApiKey = ref(false)

const llmApiKeyPlaceholder = computed(() => (
  hasSavedLlmApiKey.value
    ? t('settings.llmApiKeySavedPlaceholder')
    : t('settings.llmApiKey')
))

const whisperApiKeyPlaceholder = computed(() => (
  hasSavedWhisperApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.whisperApiKey')
))

const comfyuiApiKeyPlaceholder = computed(() => (
  hasSavedComfyuiApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.comfyuiApiKey')
))

const runninghubApiKeyPlaceholder = computed(() => (
  hasSavedRunninghubApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.runninghubApiKey')
))

const minimaxApiKeyPlaceholder = computed(() => (
  hasSavedMinimaxApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.minimaxApiKey')
))

const openaiApiKeyPlaceholder = computed(() => (
  hasSavedOpenaiApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.openaiImageApiKey')
))

const geminiApiKeyPlaceholder = computed(() => (
  hasSavedGeminiApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.geminiApiKey')
))

const gmailOAuthClientSecretPlaceholder = computed(() => (
  hasSavedGmailOAuthClientSecret.value
    ? t('settings.secretSavedPlaceholder')
    : t('config.gmailOAuthClientSecret')
))

const openaiSpeechApiKeyPlaceholder = computed(() => (
  hasSavedOpenaiSpeechApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.openaiSpeechApiKey')
))

const azureSpeechApiKeyPlaceholder = computed(() => (
  hasSavedAzureSpeechApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.azureSpeechApiKey')
))

const minimaxSpeechApiKeyPlaceholder = computed(() => (
  hasSavedMinimaxSpeechApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.minimaxSpeechApiKey')
))

const voxcpmApiKeyPlaceholder = computed(() => (
  hasSavedVoxcpmApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.voxcpmApiKey')
))

const vibevoiceTtsApiKeyPlaceholder = computed(() => (
  hasSavedVibevoiceTtsApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.vibevoiceTtsApiKey')
))

const vibevoiceAsrApiKeyPlaceholder = computed(() => (
  hasSavedVibevoiceAsrApiKey.value ? t('settings.secretSavedPlaceholder') : t('config.vibevoiceAsrApiKey')
))

const providerOptions = [
  { label: t('config.llmQwen'), value: 'qwen' },
  { label: t('config.llmOpenai'), value: 'openai' },
  { label: t('config.llmAnthropic'), value: 'anthropic' },
  { label: t('config.llmOllama'), value: 'ollama' },
  { label: t('config.llmGroq'), value: 'groq' },
]

const categoryOptions = [
  { label: t('config.llmCatEntertainment'), value: 'entertainment' },
  { label: t('config.llmCatNews'), value: 'news' },
  { label: t('config.llmCatKnowledge'), value: 'knowledge' },
  { label: t('config.llmCatVlog'), value: 'vlog' },
]

const ttsProviderOptions = [
  { label: t('config.ttsLocal'), value: 'local' },
  { label: t('config.ttsEdge'), value: 'edge-tts' },
]

const voiceProviderOptions = [
  { label: 'Edge TTS', value: 'edge_tts' },
  { label: 'Local HTTP TTS', value: 'local_http_tts' },
  { label: 'OpenAI Speech', value: 'openai_speech' },
  { label: 'Azure Speech', value: 'azure_speech' },
  { label: 'MiniMax Speech', value: 'minimax_speech' },
  { label: 'VoxCPM HTTP', value: 'voxcpm_http' },
  { label: 'VibeVoice TTS', value: 'vibevoice_tts' },
  { label: 'Silent', value: 'silent' },
]

const transcriptionProviderOptions = [
  { label: 'Whisper API', value: 'whisper_api' },
  { label: t('config.whisperProviderLocal'), value: 'whisper_local' },
  { label: 'VibeVoice ASR', value: 'vibevoice_asr' },
  { label: 'VibeVoice vLLM ASR', value: 'vibevoice_vllm_asr' },
]

const imageProviderOptions = [
  { label: 'MiniMax', value: 'minimax' },
  { label: 'OpenAI', value: 'openai' },
  { label: 'Gemini', value: 'gemini' },
  { label: t('config.imageProviderLocal'), value: 'local' },
]

const imageQualityOptions = [
  { label: t('config.imageQualityLow'), value: 'low' },
  { label: t('config.imageQualityMedium'), value: 'medium' },
  { label: t('config.imageQualityHigh'), value: 'high' },
]

const whisperProviderOptions = [
  { label: 'API', value: 'api' },
  { label: t('config.whisperProviderLocal'), value: 'local' },
]

const whisperComputeTypeOptions = [
  { label: t('config.whisperComputeAuto'), value: 'auto' },
  { label: 'float32', value: 'float32' },
  { label: 'float16', value: 'float16' },
  { label: 'int8', value: 'int8' },
  { label: 'int8_float32', value: 'int8_float32' },
]

const whisperDeviceOptions = [
  { label: t('config.whisperDeviceAuto'), value: 'auto' },
  { label: 'CUDA', value: 'cuda' },
  { label: 'CPU', value: 'cpu' },
]

const whisperLanguageOptions = [
  { label: t('config.whisperLanguageAuto'), value: 'auto' },
  { label: t('config.whisperLanguageZh'), value: 'zh' },
  { label: t('config.whisperLanguageEn'), value: 'en' },
  { label: t('config.whisperLanguageJa'), value: 'ja' },
  { label: t('config.whisperLanguageKo'), value: 'ko' },
]

const subtitleProxyModeOptions = [
  { label: t('config.subtitleProxyModeAuto'), value: 'auto' },
  { label: t('config.subtitleProxyModeSystemOnly'), value: 'system_only' },
  { label: t('config.subtitleProxyModeDirectOnly'), value: 'direct_only' },
  { label: t('config.subtitleProxyModeAccountOnly'), value: 'account_only' },
]

const proxyPoolsLoading = ref(false)
const proxyPoolOptions = ref<Array<{ label: string; value: number }>>([])

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
  whisper_provider: 'api',
  whisper_base_url: '',
  whisper_api_key: '',
  whisper_model: 'base',
  whisper_compute_type: 'auto',
  whisper_device: 'auto',
  whisper_chunk_seconds: 30,
  whisper_language: 'auto',
  article_output_dir: '',
  article_tools_path: '',
  article_default_target_lang: 'zh-Hans',
  article_subtitle_languages: 'en,zh-Hans,zh-Hant,zh,ja,ko',
  article_subtitle_proxy: '',
  article_subtitle_proxy_mode: 'auto',
  article_subtitle_proxy_pool_id: null,
  article_author: '',
  gmail_oauth_client_id: '',
  gmail_oauth_client_secret: '',
  gmail_oauth_redirect_uri: '',
  gmail_oauth_scopes: 'https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send',
  comfyui_url: '',
  comfyui_api_key: '',
  runninghub_url: '',
  runninghub_api_key: '',
  tts_provider: 'local',
  local_tts_url: '',
  video_gen_output_dir: '',
  voice_provider: 'edge_tts',
  voice_fallback_order: 'edge_tts,local_http_tts,silent',
  voice_flow_defaults_json: '{}',
  voice_output_dir: '',
  voice_require_disclosure: true,
  voice_allow_reference_clone: false,
  voice_allow_prompt_transcript_clone: false,
  voice_max_text_chars: 5000,
  transcription_provider: 'whisper_api',
  openai_speech_base_url: 'https://api.openai.com/v1',
  openai_speech_api_key: '',
  openai_speech_model: 'gpt-4o-mini-tts',
  openai_speech_voice: 'alloy',
  azure_speech_region: '',
  azure_speech_endpoint: '',
  azure_speech_api_key: '',
  azure_speech_voice: '',
  azure_speech_output_format: 'riff-24khz-16bit-mono-pcm',
  minimax_speech_base_url: 'https://api.minimax.io',
  minimax_speech_api_key: '',
  minimax_speech_model: 'speech-2.8-hd',
  minimax_speech_voice: '',
  voxcpm_base_url: '',
  voxcpm_api_key: '',
  voxcpm_model: 'openbmb/VoxCPM2',
  voxcpm_default_voice: 'default',
  voxcpm_default_control_instruction: '',
  vibevoice_tts_base_url: '',
  vibevoice_tts_api_key: '',
  vibevoice_tts_model: 'microsoft/VibeVoice-Realtime-0.5B',
  vibevoice_tts_voice: 'Carter',
  vibevoice_asr_base_url: '',
  vibevoice_asr_api_key: '',
  vibevoice_asr_model: 'microsoft/VibeVoice-ASR',
  video_gen_default_template: '1080x1920/image_default.html',
  video_gen_default_scene_count: 5,
  image_generation_provider: 'minimax',
  image_generation_fallback_order: 'minimax,openai,gemini,local',
  image_generation_timeout_seconds: 300,
  minimax_api_key: '',
  minimax_base_url: 'https://api.minimaxi.com',
  minimax_image_model: 'image-01',
  openai_api_key: '',
  openai_base_url: 'https://api.openai.com/v1',
  openai_image_model: 'gpt-image-2',
  openai_image_size: '1536x1024',
  openai_image_quality: 'medium',
  gemini_api_key: '',
  gemini_base_url: 'https://generativelanguage.googleapis.com',
  gemini_image_model: 'imagen-4.0-generate-001',
})

const hydrateSecret = (
  loadedValue: string,
  inputRef: typeof llmApiKeyInput,
  savedRef: typeof hasSavedLlmApiKey,
) => {
  savedRef.value = loadedValue === MASKED_SECRET_VALUE
  inputRef.value = savedRef.value ? '' : loadedValue
  return savedRef.value ? MASKED_SECRET_VALUE : loadedValue
}

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
    form.whisper_base_url = data.whisper_base_url || ''
    form.whisper_provider = data.whisper_provider || 'api'
    form.whisper_api_key = hydrateSecret(data.whisper_api_key || '', whisperApiKeyInput, hasSavedWhisperApiKey)
    form.whisper_model = data.whisper_model || 'base'
    form.whisper_compute_type = data.whisper_compute_type || 'auto'
    form.whisper_device = data.whisper_device || 'auto'
    form.whisper_chunk_seconds = data.whisper_chunk_seconds || 30
    form.whisper_language = data.whisper_language || 'auto'
    form.article_output_dir = data.article_output_dir || ''
    form.article_tools_path = data.article_tools_path || ''
    form.article_default_target_lang = data.article_default_target_lang || data.article_target_lang || 'zh-Hans'
    form.article_subtitle_languages = data.article_subtitle_languages || 'en,zh-Hans,zh-Hant,zh,ja,ko'
    form.article_subtitle_proxy = data.article_subtitle_proxy || ''
    form.article_subtitle_proxy_mode = data.article_subtitle_proxy_mode || 'auto'
    form.article_subtitle_proxy_pool_id = data.article_subtitle_proxy_pool_id ?? null
    form.article_author = data.article_author || ''
    form.gmail_oauth_client_id = data.gmail_oauth_client_id || ''
    form.gmail_oauth_client_secret = hydrateSecret(
      data.gmail_oauth_client_secret || '',
      gmailOAuthClientSecretInput,
      hasSavedGmailOAuthClientSecret,
    )
    form.gmail_oauth_redirect_uri = data.gmail_oauth_redirect_uri || ''
    form.gmail_oauth_scopes = data.gmail_oauth_scopes || 'https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send'
    form.comfyui_url = data.comfyui_url || ''
    form.comfyui_api_key = hydrateSecret(data.comfyui_api_key || '', comfyuiApiKeyInput, hasSavedComfyuiApiKey)
    form.runninghub_url = data.runninghub_url || ''
    form.runninghub_api_key = hydrateSecret(data.runninghub_api_key || '', runninghubApiKeyInput, hasSavedRunninghubApiKey)
    form.tts_provider = data.tts_provider || 'local'
    form.local_tts_url = data.local_tts_url || ''
    form.video_gen_output_dir = data.video_gen_output_dir || ''
    form.voice_provider = data.voice_provider || 'edge_tts'
    form.voice_fallback_order = data.voice_fallback_order || 'edge_tts,local_http_tts,silent'
    form.voice_flow_defaults_json = data.voice_flow_defaults_json || '{}'
    form.voice_output_dir = data.voice_output_dir || ''
    form.voice_require_disclosure = data.voice_require_disclosure ?? true
    form.voice_allow_reference_clone = !!data.voice_allow_reference_clone
    form.voice_allow_prompt_transcript_clone = !!data.voice_allow_prompt_transcript_clone
    form.voice_max_text_chars = data.voice_max_text_chars || 5000
    form.transcription_provider = data.transcription_provider || 'whisper_api'
    form.openai_speech_base_url = data.openai_speech_base_url || 'https://api.openai.com/v1'
    form.openai_speech_api_key = hydrateSecret(data.openai_speech_api_key || '', openaiSpeechApiKeyInput, hasSavedOpenaiSpeechApiKey)
    form.openai_speech_model = data.openai_speech_model || 'gpt-4o-mini-tts'
    form.openai_speech_voice = data.openai_speech_voice || 'alloy'
    form.azure_speech_region = data.azure_speech_region || ''
    form.azure_speech_endpoint = data.azure_speech_endpoint || ''
    form.azure_speech_api_key = hydrateSecret(data.azure_speech_api_key || '', azureSpeechApiKeyInput, hasSavedAzureSpeechApiKey)
    form.azure_speech_voice = data.azure_speech_voice || ''
    form.azure_speech_output_format = data.azure_speech_output_format || 'riff-24khz-16bit-mono-pcm'
    form.minimax_speech_base_url = data.minimax_speech_base_url || 'https://api.minimax.io'
    form.minimax_speech_api_key = hydrateSecret(data.minimax_speech_api_key || '', minimaxSpeechApiKeyInput, hasSavedMinimaxSpeechApiKey)
    form.minimax_speech_model = data.minimax_speech_model || 'speech-2.8-hd'
    form.minimax_speech_voice = data.minimax_speech_voice || ''
    form.voxcpm_base_url = data.voxcpm_base_url || ''
    form.voxcpm_api_key = hydrateSecret(data.voxcpm_api_key || '', voxcpmApiKeyInput, hasSavedVoxcpmApiKey)
    form.voxcpm_model = data.voxcpm_model || 'openbmb/VoxCPM2'
    form.voxcpm_default_voice = data.voxcpm_default_voice || 'default'
    form.voxcpm_default_control_instruction = data.voxcpm_default_control_instruction || ''
    form.vibevoice_tts_base_url = data.vibevoice_tts_base_url || ''
    form.vibevoice_tts_api_key = hydrateSecret(data.vibevoice_tts_api_key || '', vibevoiceTtsApiKeyInput, hasSavedVibevoiceTtsApiKey)
    form.vibevoice_tts_model = data.vibevoice_tts_model || 'microsoft/VibeVoice-Realtime-0.5B'
    form.vibevoice_tts_voice = data.vibevoice_tts_voice || 'Carter'
    form.vibevoice_asr_base_url = data.vibevoice_asr_base_url || ''
    form.vibevoice_asr_api_key = hydrateSecret(data.vibevoice_asr_api_key || '', vibevoiceAsrApiKeyInput, hasSavedVibevoiceAsrApiKey)
    form.vibevoice_asr_model = data.vibevoice_asr_model || 'microsoft/VibeVoice-ASR'
    form.video_gen_default_template = data.video_gen_default_template || data.default_template || '1080x1920/image_default.html'
    form.video_gen_default_scene_count = data.video_gen_default_scene_count || data.default_scene_count || 5
    form.image_generation_provider = data.image_generation_provider || 'minimax'
    form.image_generation_fallback_order = data.image_generation_fallback_order || 'minimax,openai,gemini,local'
    form.image_generation_timeout_seconds = data.image_generation_timeout_seconds || 300
    form.minimax_api_key = hydrateSecret(data.minimax_api_key || '', minimaxApiKeyInput, hasSavedMinimaxApiKey)
    form.minimax_base_url = data.minimax_base_url || 'https://api.minimaxi.com'
    form.minimax_image_model = data.minimax_image_model || 'image-01'
    form.openai_api_key = hydrateSecret(data.openai_api_key || '', openaiApiKeyInput, hasSavedOpenaiApiKey)
    form.openai_base_url = data.openai_base_url || 'https://api.openai.com/v1'
    form.openai_image_model = data.openai_image_model || 'gpt-image-2'
    form.openai_image_size = data.openai_image_size || '1536x1024'
    form.openai_image_quality = data.openai_image_quality || 'medium'
    form.gemini_api_key = hydrateSecret(data.gemini_api_key || '', geminiApiKeyInput, hasSavedGeminiApiKey)
    form.gemini_base_url = data.gemini_base_url || 'https://generativelanguage.googleapis.com'
    form.gemini_image_model = data.gemini_image_model || 'imagen-4.0-generate-001'
  } catch {
    message.error(t('settings.loadFailed'))
  }
}

const loadProxyPools = async () => {
  try {
    proxyPoolsLoading.value = true
    const res = await configApi.listProxyPools()
    proxyPoolOptions.value = (res.data || []).map((p: { id: number; name: string }) => ({
      label: p.name,
      value: p.id,
    }))
  } catch {
    // silently fail
  } finally {
    proxyPoolsLoading.value = false
  }
}

const save = async () => {
  saving.value = true
  try {
    const payload: AppConfig = {
      ...form,
      llm_api_key: llmApiKeyInput.value,
      whisper_api_key: whisperApiKeyInput.value,
      comfyui_api_key: comfyuiApiKeyInput.value,
      runninghub_api_key: runninghubApiKeyInput.value,
      minimax_api_key: minimaxApiKeyInput.value,
      openai_api_key: openaiApiKeyInput.value,
      gemini_api_key: geminiApiKeyInput.value,
      gmail_oauth_client_secret: gmailOAuthClientSecretInput.value,
      openai_speech_api_key: openaiSpeechApiKeyInput.value,
      azure_speech_api_key: azureSpeechApiKeyInput.value,
      minimax_speech_api_key: minimaxSpeechApiKeyInput.value,
      voxcpm_api_key: voxcpmApiKeyInput.value,
      vibevoice_tts_api_key: vibevoiceTtsApiKeyInput.value,
      vibevoice_asr_api_key: vibevoiceAsrApiKeyInput.value,
      article_target_lang: form.article_default_target_lang,
      default_template: form.video_gen_default_template,
      default_scene_count: form.video_gen_default_scene_count,
    }
    if (hasSavedLlmApiKey.value && !llmApiKeyInput.value) {
      payload.llm_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedWhisperApiKey.value && !whisperApiKeyInput.value) {
      payload.whisper_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedComfyuiApiKey.value && !comfyuiApiKeyInput.value) {
      payload.comfyui_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedRunninghubApiKey.value && !runninghubApiKeyInput.value) {
      payload.runninghub_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedMinimaxApiKey.value && !minimaxApiKeyInput.value) {
      payload.minimax_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedOpenaiApiKey.value && !openaiApiKeyInput.value) {
      payload.openai_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedGeminiApiKey.value && !geminiApiKeyInput.value) {
      payload.gemini_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedGmailOAuthClientSecret.value && !gmailOAuthClientSecretInput.value) {
      payload.gmail_oauth_client_secret = MASKED_SECRET_VALUE
    }
    if (hasSavedOpenaiSpeechApiKey.value && !openaiSpeechApiKeyInput.value) {
      payload.openai_speech_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedAzureSpeechApiKey.value && !azureSpeechApiKeyInput.value) {
      payload.azure_speech_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedMinimaxSpeechApiKey.value && !minimaxSpeechApiKeyInput.value) {
      payload.minimax_speech_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedVoxcpmApiKey.value && !voxcpmApiKeyInput.value) {
      payload.voxcpm_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedVibevoiceTtsApiKey.value && !vibevoiceTtsApiKeyInput.value) {
      payload.vibevoice_tts_api_key = MASKED_SECRET_VALUE
    }
    if (hasSavedVibevoiceAsrApiKey.value && !vibevoiceAsrApiKeyInput.value) {
      payload.vibevoice_asr_api_key = MASKED_SECRET_VALUE
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
    hasSavedWhisperApiKey.value = Boolean(payload.whisper_api_key)
    hasSavedComfyuiApiKey.value = Boolean(payload.comfyui_api_key)
    hasSavedRunninghubApiKey.value = Boolean(payload.runninghub_api_key)
    hasSavedMinimaxApiKey.value = Boolean(payload.minimax_api_key)
    hasSavedOpenaiApiKey.value = Boolean(payload.openai_api_key)
    hasSavedGeminiApiKey.value = Boolean(payload.gemini_api_key)
    hasSavedGmailOAuthClientSecret.value = Boolean(payload.gmail_oauth_client_secret)
    hasSavedOpenaiSpeechApiKey.value = Boolean(payload.openai_speech_api_key)
    hasSavedAzureSpeechApiKey.value = Boolean(payload.azure_speech_api_key)
    hasSavedMinimaxSpeechApiKey.value = Boolean(payload.minimax_speech_api_key)
    hasSavedVoxcpmApiKey.value = Boolean(payload.voxcpm_api_key)
    hasSavedVibevoiceTtsApiKey.value = Boolean(payload.vibevoice_tts_api_key)
    hasSavedVibevoiceAsrApiKey.value = Boolean(payload.vibevoice_asr_api_key)
    whisperApiKeyInput.value = ''
    comfyuiApiKeyInput.value = ''
    runninghubApiKeyInput.value = ''
    minimaxApiKeyInput.value = ''
    openaiApiKeyInput.value = ''
    geminiApiKeyInput.value = ''
    gmailOAuthClientSecretInput.value = ''
    openaiSpeechApiKeyInput.value = ''
    azureSpeechApiKeyInput.value = ''
    minimaxSpeechApiKeyInput.value = ''
    voxcpmApiKeyInput.value = ''
    vibevoiceTtsApiKeyInput.value = ''
    vibevoiceAsrApiKeyInput.value = ''
    form.whisper_api_key = hasSavedWhisperApiKey.value ? MASKED_SECRET_VALUE : ''
    form.comfyui_api_key = hasSavedComfyuiApiKey.value ? MASKED_SECRET_VALUE : ''
    form.runninghub_api_key = hasSavedRunninghubApiKey.value ? MASKED_SECRET_VALUE : ''
    form.minimax_api_key = hasSavedMinimaxApiKey.value ? MASKED_SECRET_VALUE : ''
    form.openai_api_key = hasSavedOpenaiApiKey.value ? MASKED_SECRET_VALUE : ''
    form.gemini_api_key = hasSavedGeminiApiKey.value ? MASKED_SECRET_VALUE : ''
    form.gmail_oauth_client_secret = hasSavedGmailOAuthClientSecret.value ? MASKED_SECRET_VALUE : ''
    form.openai_speech_api_key = hasSavedOpenaiSpeechApiKey.value ? MASKED_SECRET_VALUE : ''
    form.azure_speech_api_key = hasSavedAzureSpeechApiKey.value ? MASKED_SECRET_VALUE : ''
    form.minimax_speech_api_key = hasSavedMinimaxSpeechApiKey.value ? MASKED_SECRET_VALUE : ''
    form.voxcpm_api_key = hasSavedVoxcpmApiKey.value ? MASKED_SECRET_VALUE : ''
    form.vibevoice_tts_api_key = hasSavedVibevoiceTtsApiKey.value ? MASKED_SECRET_VALUE : ''
    form.vibevoice_asr_api_key = hasSavedVibevoiceAsrApiKey.value ? MASKED_SECRET_VALUE : ''
    message.success(t('settings.saved'))
  } catch {
    message.error(t('settings.saveFailed'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig()
  loadProxyPools()
})
</script>
