<template>
  <aside class="sidebar" :class="{ 'sidebar--collapsed': collapsed }" :aria-label="t('nav.appName')">
    <!-- Logo -->
    <RouterLink to="/" class="sidebar__logo" :title="t('nav.appName')" :aria-label="t('nav.appName')">
      <div class="sidebar__logo-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2L2 7l10 5 10-5-10-5z"/>
          <path d="M2 17l10 5 10-5"/>
          <path d="M2 12l10 5 10-5"/>
        </svg>
      </div>
      <span class="sidebar__logo-text">ResDownloader</span>
    </RouterLink>

    <!-- Nav -->
    <nav class="sidebar__nav" :aria-label="t('nav.appName')">
      <!-- Primary nav items -->
      <RouterLink
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        class="sidebar__item"
        :class="{ 'sidebar__item--active': isActive(item.path) }"
        :title="navLabel(item.key)"
        :aria-current="isActive(item.path) ? 'page' : undefined"
      >
        <span class="sidebar__item-icon" aria-hidden="true" v-html="item.icon"></span>
        <span class="sidebar__item-label">{{ navLabel(item.key) }}</span>
      </RouterLink>

      <!-- Settings group (collapsible) -->
      <div class="sidebar__group--settings" :class="{ 'sidebar__group--expanded': settingsExpanded }">
        <div class="sidebar__group-head">
          <RouterLink
            to="/settings-hub"
            class="sidebar__item sidebar__item--settings-main"
            :class="{ 'sidebar__item--active-parent': isSettingsActive }"
            :title="t('nav.settings')"
            :aria-current="route.path === '/settings-hub' ? 'page' : undefined"
          >
            <span class="sidebar__item-icon" aria-hidden="true" v-html="settingsIcon"></span>
            <span class="sidebar__item-label">{{ t('nav.settings') }}</span>
          </RouterLink>
          <button
            type="button"
            class="sidebar__group-toggle"
            :aria-label="t('common.toggle')"
            :aria-expanded="settingsExpanded"
            aria-controls="settings-subnav"
            :title="t('common.toggle')"
            @click="settingsExpanded = !settingsExpanded"
          >
            <span class="sidebar__group-chevron" aria-hidden="true" v-html="chevronIcon"></span>
          </button>
        </div>

        <div id="settings-subnav" class="sidebar__subnav" :aria-label="t('nav.settings')" role="group">
          <RouterLink
            v-for="sub in settingsSubItems"
            :key="sub.path"
            :to="sub.path"
            class="sidebar__item sidebar__item--sub"
            :class="{ 'sidebar__item--active': isActive(sub.path) }"
            :title="navLabel(sub.key)"
            :aria-current="isActive(sub.path) ? 'page' : undefined"
          >
            <span class="sidebar__item-icon" aria-hidden="true" v-html="sub.icon"></span>
            <span class="sidebar__item-label">{{ navLabel(sub.key) }}</span>
          </RouterLink>
        </div>
      </div>
    </nav>

    <!-- Footer -->
    <div class="sidebar__footer">
      <div class="sidebar__footer-actions" :aria-label="t('nav.settings')" role="group">
        <!-- Theme toggle -->
        <button
          type="button"
          class="sidebar__item sidebar__item--tool"
          :aria-label="t('nav.theme')"
          :title="t('nav.theme')"
          @click="toggleTheme"
        >
          <span class="sidebar__item-icon" aria-hidden="true" v-html="themeIcon"></span>
          <span class="sidebar__item-label">{{ t('nav.theme') }}</span>
        </button>

        <!-- Language toggle -->
        <button
          type="button"
          class="sidebar__item sidebar__item--tool"
          :aria-label="t('menu.locale')"
          :title="t('menu.locale')"
          @click="toggleLocale"
        >
          <span class="sidebar__item-icon" aria-hidden="true" v-html="langIcon"></span>
          <span class="sidebar__item-label">{{ t('menu.locale') }}</span>
        </button>
      </div>

      <!-- Collapse toggle -->
      <button
        type="button"
        class="sidebar__toggle"
        :aria-pressed="collapsed"
        :title="t('nav.collapse')"
        @click="toggleCollapse"
      >
        <span class="sidebar__toggle-icon" aria-hidden="true">{{ collapsed ? '›' : '‹' }}</span>
        <span class="sidebar__item-label">{{ collapsed ? '' : t('nav.collapse') }}</span>
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t, locale } = useI18n()
const route = useRoute()

const collapsed = ref(false)
const settingsExpanded = ref(route.path.startsWith('/settings-hub'))

// SVG icons
const dashboardIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/></svg>`
const accountsIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`
const batchDownloadIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`
const apiKeysIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>`
const proxyPoolIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>`
const dynamicProxyIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1"/></svg>`
const clipHistoryIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><path d="M8.12 8.12 12 12"/><path d="M20 4 8.12 15.88"/><circle cx="6" cy="18" r="3"/><path d="M14.8 14.8 20 20"/></svg>`
const aiCreationIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v4"/><path d="M12 17v4"/><path d="M3 12h4"/><path d="M17 12h4"/><path d="m5.64 5.64 2.83 2.83"/><path d="m15.53 15.53 2.83 2.83"/><path d="m18.36 5.64-2.83 2.83"/><path d="m8.47 15.53-2.83 2.83"/><circle cx="12" cy="12" r="3"/></svg>`
const wechatCollectIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3 1.6-4.8A8 8 0 1 1 21 15z"/><path d="M8 9h8"/><path d="M8 13h5"/></svg>`
const resourceIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`
const settingsIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`
const chevronIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>`
const moonIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`
const langIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 8l6 6"/><path d="M4 14l6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="M22 22l-5-10-5 10"/><path d="M14 18h6"/></svg>`
const notifyIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`
const chartIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>`
const downloadSettingsIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>`
const aiClipIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.12 15.88"/><path d="M14.47 14.48 20 20"/><path d="M8.12 8.12 12 12"/></svg>`
const wechatPublishIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a8 8 0 0 1-8 8H7l-4 3 1.5-5A8 8 0 1 1 21 12z"/><path d="M9 10h.01"/><path d="M14 10h.01"/><path d="M10 15h4"/></svg>`
const dynamicSettingsIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 0 20"/><path d="M12 2a15.3 15.3 0 0 0 0 20"/></svg>`
const lockIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>`

const themeIcon = moonIcon

const navItems = [
  { key: 'dashboard', path: '/', icon: dashboardIcon },
  { key: 'channels', path: '/accounts', icon: accountsIcon },
  { key: 'downloads', path: '/batch-download', icon: batchDownloadIcon },
  { key: 'apiKeys', path: '/api-keys', icon: apiKeysIcon },
  { key: 'proxyPools', path: '/proxy-pools', icon: proxyPoolIcon },
  { key: 'dynamicProviders', path: '/dynamic-providers', icon: dynamicProxyIcon },
  { key: 'clipHistory', path: '/clip-history', icon: clipHistoryIcon },
  { key: 'aiCreation', path: '/ai-creation', icon: aiCreationIcon },
  { key: 'wechatCollect', path: '/wechat-collect', icon: wechatCollectIcon },
  { key: 'resources', path: '/resources', icon: resourceIcon },
]

const settingsSubItems = [
  { key: 'settingsNotify', path: '/settings-hub/notify', icon: notifyIcon },
  { key: 'settingsApi', path: '/settings-hub/api', icon: chartIcon },
  { key: 'settingsDownload', path: '/settings-hub/download', icon: downloadSettingsIcon },
  { key: 'settingsAi', path: '/settings-hub/ai', icon: aiClipIcon },
  { key: 'settingsWechat', path: '/settings-hub/wechat', icon: wechatPublishIcon },
  { key: 'settingsDynamic', path: '/settings-hub/dynamic', icon: dynamicSettingsIcon },
  { key: 'settingsProxy', path: '/settings-hub/proxy', icon: lockIcon },
]

const explicitNavLabels: Record<string, string> = {
  aiCreation: 'nav.aiCreation',
  wechatCollect: 'nav.wechatCollect',
}

const navLabel = (key: string) => {
  return t(explicitNavLabels[key] || `nav.${key}`)
}

const isActive = (path: string) => {
  return route.path === path
}

const isSettingsActive = computed(() => {
  return route.path.startsWith('/settings-hub')
})

watch(
  () => route.path,
  (path) => {
    if (path.startsWith('/settings-hub')) {
      settingsExpanded.value = true
    }
  },
)

const toggleTheme = () => {
  // Placeholder: theme toggle can be expanded later
}

const toggleLocale = () => {
  locale.value = locale.value === 'zh' ? 'en' : 'zh'
}

const toggleCollapse = () => {
  collapsed.value = !collapsed.value
}
</script>
