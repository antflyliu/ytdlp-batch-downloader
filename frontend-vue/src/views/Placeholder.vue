<template>
  <div>
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('nav.' + pageName) }}</div>
        <div class="page-desc">{{ t('common.comingSoon') }}</div>
      </div>
    </div>
    <div class="empty-state">
      <div class="empty-state__icon" aria-hidden="true">—</div>
      <div class="empty-state__title">{{ t('common.underConstruction') }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const route = useRoute()

// Derive page name from route name
const pageName = computed(() => {
  const name = route.name as string
  // Map route name to locale key
  const nameMap: Record<string, string> = {
    accounts: 'channels',
    batchDownload: 'downloads',
    settingsHub: 'settings',
  }
  return nameMap[name] || name.charAt(0).toLowerCase() + name.slice(1)
})
</script>

