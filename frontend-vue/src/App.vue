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
      <DesktopCloseDialog
        v-model:show="desktopCloseDialogVisible"
        @choose="handleDesktopCloseChoice"
      />
    </NaiveProvider>
    <NGlobalStyle/>
  </NConfigProvider>
</template>

<script setup lang="ts">
import NaiveProvider from '@/components/NaiveProvider.vue'
import AppSider from '@/components/layout/AppSider.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import DesktopCloseDialog from '@/components/DesktopCloseDialog.vue'
import { NConfigProvider, NGlobalStyle, lightTheme, zhCN, enUS } from 'naive-ui'
import { useResourceStore } from '@/stores/resourceStore'
import { useEventStore } from '@/stores/eventStore'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  closeWithDesktopChoice,
  forceQuitDesktop,
  getDesktopBridge,
  setDesktopCloseLocale,
  type DesktopCloseChoice,
} from '@/utils/desktopBridge'

const resourceStore = useResourceStore()
const eventStore = useEventStore()
const { locale } = useI18n()
const desktopCloseDialogVisible = ref(false)

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

const syncDesktopCloseLocale = () => {
  void setDesktopCloseLocale(String(locale.value))
}

const markDesktopCloseBridgeReady = () => {
  const bridge = getDesktopBridge()
  if (!bridge?.closeWithChoice) return
  window.__YTDLP_DESKTOP_CLOSE_READY__ = true
  syncDesktopCloseLocale()
  flushPendingDesktopCloseRequest()
}

const handleDesktopCloseRequest = () => {
  desktopCloseDialogVisible.value = true
}

const flushPendingDesktopCloseRequest = () => {
  if (!window.__YTDLP_PENDING_DESKTOP_CLOSE__) return
  window.__YTDLP_PENDING_DESKTOP_CLOSE__ = false
  handleDesktopCloseRequest()
}

const handleDesktopCloseChoice = async (choice: DesktopCloseChoice) => {
  desktopCloseDialogVisible.value = false
  const handled = await closeWithDesktopChoice(choice)
  if (!handled) {
    if (choice.action === 'quit') {
      const forced = await forceQuitDesktop()
      if (!forced) window.close()
      return
    }
    desktopCloseDialogVisible.value = true
  }
}

onMounted(async () => {
  window.addEventListener('desktop-close-request', handleDesktopCloseRequest)
  window.addEventListener('pywebviewready', markDesktopCloseBridgeReady)
  markDesktopCloseBridgeReady()

  // Initialize SSE connection（Monitor API 无 token 鉴权）
  eventStore.init()

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

onBeforeUnmount(() => {
  window.__YTDLP_DESKTOP_CLOSE_READY__ = false
  window.__YTDLP_PENDING_DESKTOP_CLOSE__ = false
  window.removeEventListener('pywebviewready', markDesktopCloseBridgeReady)
  window.removeEventListener('desktop-close-request', handleDesktopCloseRequest)
})

watch(locale, syncDesktopCloseLocale)
</script>
