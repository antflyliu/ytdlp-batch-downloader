<template>
  <div>
    <!-- Back link -->
    <RouterLink to="/settings-hub" class="back-link mb-4">
      {{ t('settings.backToSettings') }}
    </RouterLink>

    <div class="page-header mb-6">
      <div class="page-title">{{ t('settings.downloadSettingsTitle') }}</div>
      <div class="page-desc">{{ t('settings.downloadDesc') }}</div>
    </div>

    <NForm ref="formRef" :model="form" label-placement="left" label-width="180">
      <NCard class="mb-4" :title="t('settings.saveDirectory')">
        <NFormItem :label="t('config.downloadPath')" path="download_path">
          <NInput
            v-model:value="form.download_path"
            :placeholder="t('settings.downloadPathPlaceholder')"
          />
        </NFormItem>
        <div class="text-xs text-gray-500 -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.downloadPathHint') }}
        </div>

        <NFormItem :label="t('config.enableAria2Enable')" path="enable_aria2">
          <NSwitch v-model:value="form.enable_aria2" />
        </NFormItem>
        <div class="text-xs text-gray-500 -mt-2 mb-3" style="padding-left: 180px">
          {{ t('config.enableAria2Hint') }}
        </div>
      </NCard>

      <NCard class="mb-4" :title="t('settings.cookiesFile')">
        <NFormItem :label="t('settings.cookiesFile')" path="cookies_file">
          <NInput
            v-model:value="form.cookies_file"
            :placeholder="t('settings.cookiesFilePlaceholder')"
          />
        </NFormItem>
        <div class="text-xs text-gray-500 -mt-2 mb-3" style="padding-left: 180px">
          <span v-html="t('config.cookiesFileHint')"></span>
        </div>
      </NCard>

      <NCard class="mb-4" :title="t('settings.subLangs')">
        <NFormItem :label="t('settings.subLangs')" path="sub_langs">
          <NInput
            v-model:value="form.sub_langs"
            placeholder="en,zh-Hans,zh-Hant"
          />
        </NFormItem>
        <div class="text-xs text-gray-500 -mt-2 mb-3" style="padding-left: 180px">
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
  download_path: '',
  cookies_file: '',
  sub_langs: '',
  enable_aria2: false,
})

const loadConfig = async () => {
  try {
    const res = await configApi.get()
    const data = res.data || {}
    form.download_path = data.download_path || ''
    form.cookies_file = data.cookies_file || ''
    form.sub_langs = data.sub_langs || ''
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
