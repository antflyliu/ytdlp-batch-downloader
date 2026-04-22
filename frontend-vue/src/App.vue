<template>
  <NConfigProvider class="h-full" :theme="theme" :locale="uiLocale">
    <NaiveProvider>
      <RouterView/>
    </NaiveProvider>
    <NGlobalStyle/>
    <NModalProvider/>
  </NConfigProvider>
</template>

<script setup lang="ts">
import NaiveProvider from '@/components/NaiveProvider.vue'
import {darkTheme, lightTheme, zhCN, enUS} from 'naive-ui'
import {useResourceStore} from "@/stores/resourceStore"
import {useEventStore} from "@/stores/eventStore"
import {computed, onMounted} from "vue"
import {useI18n} from 'vue-i18n'

const resourceStore = useResourceStore()
const eventStore = useEventStore()
const {locale} = useI18n()

const theme = computed(() => {
  // Default to lightTheme (dark mode toggle can be added later)
  return lightTheme
})

const uiLocale = computed(() => {
  return locale.value === "zh" ? zhCN : enUS
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
    // Progress updates handled by UI components watching the queue
    console.debug('[downloadProgress]', data)
  })
})
</script>