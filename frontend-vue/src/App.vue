<template>
  <NConfigProvider class="app-provider" :theme="theme" :theme-overrides="themeOverrides" :locale="uiLocale">
    <NaiveProvider>
      <div class="app-layout">
        <AppSider />
        <div class="app-main">
          <AppHeader />
          <main class="app-content">
            <RouterView />
          </main>
        </div>
      </div>
    </NaiveProvider>
    <NGlobalStyle/>
  </NConfigProvider>
</template>

<script setup lang="ts">
import NaiveProvider from '@/components/NaiveProvider.vue'
import AppSider from '@/components/layout/AppSider.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import { NConfigProvider, NGlobalStyle, lightTheme, zhCN, enUS } from 'naive-ui'
import { useResourceStore } from '@/stores/resourceStore'
import { useEventStore } from '@/stores/eventStore'
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

const resourceStore = useResourceStore()
const eventStore = useEventStore()
const { locale } = useI18n()

const theme = computed(() => {
  return lightTheme
})

const themeOverrides = {
  common: {
    bodyColor: '#f5f4ed',
    primaryColor: '#c96442',
    primaryColorHover: '#d97757',
    primaryColorPressed: '#b95738',
    primaryColorSuppl: '#d97757',
    textColorBase: '#141413',
    textColor1: '#141413',
    textColor2: '#4d4c48',
    textColor3: '#5e5d59',
    borderColor: '#e8e6dc',
    borderRadius: '12px',
    hoverColor: '#f0eee6',
    modalColor: '#faf9f5',
    cardColor: '#fffdf8',
    popoverColor: '#faf9f5',
    tableColor: '#fffdf8',
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
}

const uiLocale = computed(() => {
  return locale.value === 'zh' ? zhCN : enUS
})

onMounted(async () => {
  // Get token from window.__MONITOR_API_TOKEN__ (injected by Flask)
  const token = (window as any).__MONITOR_API_TOKEN__ || ''

  // Initialize SSE connection
  eventStore.init(token)

  // Register newResources handler — add to resource store
  eventStore.addHandle('newResources', (data: any) => {
    const items = Array.isArray(data) ? data : [data]
    resourceStore.addResources(items)
  })

  // Register downloadProgress handler
  eventStore.addHandle('downloadProgress', (data: any) => {
    console.debug('[downloadProgress]', data)
  })
})
</script>
