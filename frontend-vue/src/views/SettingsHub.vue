<template>
  <div>
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('settings.hubTitle') }}</div>
        <div class="page-desc">{{ t('settings.hubDesc') }}</div>
      </div>
    </div>

    <div class="settings-grid">
      <!-- Notify -->
      <RouterLink to="/settings-hub/notify" class="settings-card">
        <div class="settings-card__icon" style="color: var(--feishu)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
          </svg>
        </div>
        <div class="settings-card__body">
          <div class="settings-card__title">{{ t('settings.notifyTitle') }}</div>
          <div class="settings-card__desc">{{ t('settings.hubNotifyDesc') }}</div>
        </div>
        <div class="settings-card__arrow">→</div>
      </RouterLink>

      <!-- API -->
      <RouterLink to="/settings-hub/api" class="settings-card">
        <div class="settings-card__icon" style="color: var(--warning)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="20" x2="18" y2="10"/>
            <line x1="12" y1="20" x2="12" y2="4"/>
            <line x1="6" y1="20" x2="6" y2="14"/>
          </svg>
        </div>
        <div class="settings-card__body">
          <div class="settings-card__title">{{ t('settings.apiTitle') }}</div>
          <div class="settings-card__desc">{{ t('settings.hubApiDesc') }}</div>
        </div>
        <div class="settings-card__arrow">→</div>
      </RouterLink>

      <!-- Download -->
      <RouterLink to="/settings-hub/download" class="settings-card">
        <div class="settings-card__icon" style="color: var(--success)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <path d="M7 10l5 5 5-5"/>
            <path d="M12 15V3"/>
          </svg>
        </div>
        <div class="settings-card__body">
          <div class="settings-card__title">{{ t('settings.downloadSettingsTitle') }}</div>
          <div class="settings-card__desc">{{ t('settings.hubDownloadDesc') }}</div>
        </div>
        <div class="settings-card__arrow">→</div>
      </RouterLink>

      <!-- AI -->
      <RouterLink to="/settings-hub/ai" class="settings-card">
        <div class="settings-card__icon" style="color: var(--accent)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="6" cy="6" r="3"/>
            <circle cx="6" cy="18" r="3"/>
            <path d="M20 4 8.12 15.88"/>
            <path d="M14.47 14.48 20 20"/>
            <path d="M8.12 8.12 12 12"/>
          </svg>
        </div>
        <div class="settings-card__body">
          <div class="settings-card__title">{{ t('settings.aiTitle') }}</div>
          <div class="settings-card__desc">{{ t('settings.hubAiDesc') }}</div>
        </div>
        <div class="settings-card__arrow">→</div>
      </RouterLink>

      <!-- WeChat Publish -->
      <RouterLink to="/settings-hub/wechat" class="settings-card">
        <div class="settings-card__icon" style="color: var(--success)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12a8 8 0 0 1-8 8H7l-4 3 1.5-5A8 8 0 1 1 21 12z"/>
            <path d="M9 10h.01"/>
            <path d="M14 10h.01"/>
            <path d="M10 15h4"/>
          </svg>
        </div>
        <div class="settings-card__body">
          <div class="settings-card__title">{{ t('settings.wechatPublishTitle') }}</div>
          <div class="settings-card__desc">{{ t('settings.hubWechatDesc') }}</div>
        </div>
        <div class="settings-card__arrow">→</div>
      </RouterLink>

      <!-- Dynamic Proxy -->
      <RouterLink to="/settings-hub/dynamic" class="settings-card">
        <div class="settings-card__icon" style="color: var(--accent)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M2 12h20"/>
            <path d="M12 2a15.3 15.3 0 0 1 0 20"/>
            <path d="M12 2a15.3 15.3 0 0 0 0 20"/>
          </svg>
        </div>
        <div class="settings-card__body">
          <div class="settings-card__title">{{ t('settings.dynamicTitle') }}</div>
          <div class="settings-card__desc">{{ t('settings.hubDynamicDesc') }}</div>
        </div>
        <div class="settings-card__arrow">→</div>
      </RouterLink>

      <!-- Proxy Sniffer -->
      <RouterLink to="/settings-hub/proxy" class="settings-card">
        <div class="settings-card__icon" style="color: var(--focus)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="11" width="18" height="10" rx="2"/>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
          </svg>
        </div>
        <div class="settings-card__body">
          <div class="settings-card__title">{{ t('nav.settingsProxy') }}</div>
          <div class="settings-card__desc">{{ t('settings.hubProxyDesc') }}</div>
        </div>
        <div class="settings-card__arrow">→</div>
      </RouterLink>

    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<style scoped>
.settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.settings-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  text-decoration: none;
  transition: all 150ms ease-out;
  cursor: pointer;
}

.settings-card:hover {
  border-color: var(--accent);
  background: var(--accent-dim, rgba(201, 100, 66, 0.05));
  transform: translateY(-1px);
  box-shadow: var(--shadow-whisper);
}

.settings-card__icon {
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(232, 230, 220, 0.58);
}

.settings-card__icon svg {
  width: 21px;
  height: 21px;
}

.settings-card__body {
  flex: 1;
  min-width: 0;
}

.settings-card__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
}

.settings-card__desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
}

.settings-card__arrow {
  font-size: 18px;
  color: var(--text-dim);
  flex-shrink: 0;
}
</style>
