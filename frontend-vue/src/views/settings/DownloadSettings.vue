<template>
  <div>
    <!-- Back link -->
    <RouterLink to="/settings-hub" class="back-link">
      {{ t('settings.backToSettings') }}
    </RouterLink>

    <div class="page-header">
      <div class="page-title">{{ t('settings.downloadSettingsTitle') }}</div>
      <div class="page-desc">{{ t('settings.downloadDesc') }}</div>
    </div>

    <NForm ref="formRef" :model="form" label-placement="left" label-width="180">
      <NCard :title="t('settings.saveDirectory')">
        <NFormItem :label="t('config.downloadPath')" path="download_path">
          <NInput
            v-model:value="form.download_output_path"
            :placeholder="t('settings.downloadPathPlaceholder')"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.downloadPathHint') }}
        </div>

        <NFormItem :label="t('config.enableAria2Enable')" path="enable_aria2">
          <NSwitch v-model:value="form.enable_aria2" />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.enableAria2Hint') }}
        </div>
      </NCard>

      <NCard :title="t('settings.cookiesFile')">
        <NFormItem :label="t('settings.cookiesFile')" path="cookies_file">
          <NInput
            v-model:value="form.download_cookies_file"
            :placeholder="t('settings.cookiesFilePlaceholder')"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          <span v-html="t('config.cookiesFileHint')"></span>
        </div>
      </NCard>

      <NCard :title="t('settings.subLangs')">
        <NFormItem :label="t('settings.subLangs')" path="sub_langs">
          <NInput
            v-model:value="form.default_sub_langs"
            placeholder="en,zh-Hans,zh-Hant"
          />
        </NFormItem>
        <div class="text-xs text-dim -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.subLangsHint') }}
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
import { NForm, NFormItem, NInput, NButton, NCard, NSwitch, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import configApi, { AppConfig } from '@/api/config'

const { t } = useI18n()
const message = useMessage()

const saving = ref(false)

const form = reactive<AppConfig>({
  download_output_path: '',
  download_cookies_file: '',
  default_sub_langs: '',
  enable_aria2: false,
})

const loadConfig = async () => {
  try {
    const res = await configApi.get()
    const data = res.data || {}
    form.download_output_path = data.download_output_path || ''
    form.download_cookies_file = data.download_cookies_file || ''
    form.default_sub_langs = data.default_sub_langs || ''
    form.enable_aria2 = !!data.enable_aria2
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
