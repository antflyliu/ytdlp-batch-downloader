<template>
  <div>
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('nav.' + pageName) }}</div>
        <div class="page-desc">{{ t('common.comingSoon') }}</div>
      </div>
    </div>
    <div class="empty-state">
      <div class="empty-icon">🚧</div>
      <div class="empty-title">{{ t('common.underConstruction') }}</div>
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

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 0 0 16px;
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
.empty-state {
  text-align: center;
  padding: 48px 24px;
  color: var(--text-muted);
}
.empty-icon { font-size: 40px; margin-bottom: 12px; opacity: 0.4; }
.empty-title { font-size: 15px; font-weight: 600; margin-bottom: 6px; color: var(--text); }
</style>
