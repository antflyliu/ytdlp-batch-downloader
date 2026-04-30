<template>
  <header class="header">
    <div class="header-left">
      <span class="header-nav-title">{{ pageTitle }}</span>
    </div>
    <div class="header-right">
      <!-- Language switch -->
      <button class="btn btn--ghost btn--sm" @click="toggleLocale">
        {{ t('menu.locale') }}
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t, locale } = useI18n()
const route = useRoute()

// Map route paths to nav i18n keys
const routeTitleMap: Record<string, string> = {
  '/': 'nav.dashboard',
  '/accounts': 'nav.channels',
  '/batch-download': 'nav.downloads',
  '/api-keys': 'nav.apiKeys',
  '/proxy-pools': 'nav.proxyPools',
  '/dynamic-providers': 'nav.dynamicProviders',
  '/clip-history': 'nav.clipHistory',
  '/resources': 'nav.resources',
  '/ai-creation': 'nav.aiCreation',
  '/wechat-collect': 'nav.wechatCollect',
  '/wechat-native-collect': 'nav.wechatNativeCollect',
  '/settings-hub': 'nav.settings',
  '/settings-hub/notify': 'nav.settingsNotify',
  '/settings-hub/api': 'nav.settingsApi',
  '/settings-hub/download': 'nav.settingsDownload',
  '/settings-hub/ai': 'nav.settingsAi',
  '/settings-hub/dynamic': 'nav.settingsDynamic',
  '/settings-hub/proxy': 'nav.settingsProxy',
}

const pageTitle = computed(() => {
  // Try exact match first
  const key = routeTitleMap[route.path]
  if (key) return t(key)
  // Try parent path for nested routes
  const parts = route.path.split('/')
  if (parts.length >= 3) {
    const parent = '/' + parts.slice(0, 3).join('/')
    const parentKey = routeTitleMap[parent]
    if (parentKey) return t(parentKey)
  }
  return t('nav.dashboard')
})

const toggleLocale = () => {
  locale.value = locale.value === 'zh' ? 'en' : 'zh'
}
</script>
