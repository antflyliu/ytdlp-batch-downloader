<template>
  <NModal
    v-model:show="visible"
    preset="card"
    :bordered="false"
    :closable="false"
    :mask-closable="false"
    :block-scroll="false"
    :mask-style="maskStyle"
    class="desktop-close-modal"
    transform-origin="center"
  >
    <section
      class="desktop-close-card"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      :aria-describedby="descriptionId"
      tabindex="-1"
    >
      <button
        type="button"
        class="desktop-close-dismiss"
        ref="dismissButton"
        :aria-label="t('desktopClose.dismiss')"
        @click="visible = false"
      >
        <NIcon :size="24">
          <CloseOutline />
        </NIcon>
      </button>

      <div class="desktop-close-header">
        <h2 :id="titleId">{{ t('desktopClose.title') }}</h2>
        <p :id="descriptionId">{{ t('desktopClose.description') }}</p>
      </div>

      <div class="desktop-close-options">
        <button
          v-for="option in options"
          :key="option.action"
          type="button"
          class="desktop-close-option"
          :class="`desktop-close-option--${option.tone}`"
          :disabled="pending"
          @click="choose(option.action)"
        >
          <span class="desktop-close-option__icon" aria-hidden="true">
            <NIcon :size="30">
              <component :is="option.icon" />
            </NIcon>
          </span>
          <span class="desktop-close-option__copy">
            <strong>{{ t(option.titleKey) }}</strong>
            <span>{{ t(option.descriptionKey) }}</span>
          </span>
        </button>
      </div>

      <NCheckbox v-model:checked="remember" class="desktop-close-remember">
        {{ t('desktopClose.remember') }}
      </NCheckbox>
    </section>
  </NModal>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { NCheckbox, NIcon, NModal } from 'naive-ui'
import { CloseOutline, ContractOutline, ExitOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { Component } from 'vue'
import type { DesktopCloseAction, DesktopCloseChoice } from '@/utils/desktopBridge'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  choose: [choice: DesktopCloseChoice]
}>()

const { t } = useI18n()
const remember = ref(false)
const pending = ref(false)
const dismissButton = ref<HTMLButtonElement | null>(null)
const titleId = 'desktop-close-title'
const descriptionId = 'desktop-close-description'
const maskStyle = {
  backgroundColor: 'rgba(45, 42, 38, 0.46)',
  backdropFilter: 'blur(8px)',
}

const visible = computed({
  get: () => props.show,
  set: (value: boolean) => emit('update:show', value),
})

const options: Array<{
  action: DesktopCloseAction
  tone: 'tray' | 'quit'
  icon: Component
  titleKey: string
  descriptionKey: string
}> = [
  {
    action: 'tray',
    tone: 'tray',
    icon: ContractOutline,
    titleKey: 'desktopClose.trayTitle',
    descriptionKey: 'desktopClose.trayDescription',
  },
  {
    action: 'quit',
    tone: 'quit',
    icon: ExitOutline,
    titleKey: 'desktopClose.quitTitle',
    descriptionKey: 'desktopClose.quitDescription',
  },
]

const choose = (action: DesktopCloseAction) => {
  if (pending.value) return
  pending.value = true
  emit('choose', {
    action,
    remember: remember.value,
  })
}

watch(
  () => props.show,
  async (show) => {
    pending.value = false
    if (!show) {
      remember.value = false
      return
    }
    await nextTick()
    dismissButton.value?.focus()
  },
)
</script>

<style scoped>
:global(.desktop-close-modal.n-card) {
  width: min(92vw, 600px);
  border-radius: 22px !important;
  background: var(--surface) !important;
  border: 1px solid var(--border-cream) !important;
  box-shadow: 0 22px 70px rgba(45, 42, 38, 0.24), 0 0 0 1px rgba(20, 20, 19, 0.04) !important;
}

:global(.desktop-close-modal .n-card__content) {
  padding: 0 !important;
}

.desktop-close-card {
  position: relative;
  max-height: min(640px, calc(100vh - 64px));
  overflow-y: auto;
  padding: 44px 42px 36px;
  border-radius: 22px;
  background: var(--surface);
  color: var(--text);
  font-family: var(--font-sans);
}

.desktop-close-card:focus {
  outline: none;
}

.desktop-close-dismiss {
  position: absolute;
  top: 26px;
  right: 28px;
  width: 44px;
  height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: var(--r-md);
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  transition: color 160ms ease, background 160ms ease;
}

.desktop-close-dismiss:hover {
  background: var(--surface2);
  color: var(--text);
}

.desktop-close-dismiss:focus-visible,
.desktop-close-option:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 3px;
}

.desktop-close-header {
  padding-right: 48px;
}

.desktop-close-header h2 {
  margin: 0;
  font-family: var(--font);
  font-size: 30px;
  font-weight: 500;
  line-height: 1.18;
  color: var(--text);
  letter-spacing: 0;
}

.desktop-close-header p {
  margin: 14px 0 0;
  font-size: 18px;
  line-height: 1.5;
  color: var(--text-muted);
}

.desktop-close-options {
  display: grid;
  gap: 18px;
  margin: 32px 0 28px;
}

.desktop-close-option {
  min-height: 120px;
  width: 100%;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 24px;
  border: 1px solid var(--border-medium);
  border-radius: 18px;
  background: #fffdf8;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  box-shadow: 0 0 0 1px rgba(20, 20, 19, 0.015);
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease, background 160ms ease;
}

.desktop-close-option:hover {
  transform: translateY(-1px);
  border-color: rgba(201, 100, 66, 0.42);
  background: #fffaf0;
  box-shadow: var(--shadow-whisper), 0 0 0 1px rgba(201, 100, 66, 0.10);
}

.desktop-close-option:disabled {
  cursor: wait;
  opacity: 0.72;
  transform: none;
}

.desktop-close-option__icon {
  width: 72px;
  height: 72px;
  flex: 0 0 72px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 20px;
  color: #fffdf8;
}

.desktop-close-option--tray .desktop-close-option__icon {
  background: var(--accent);
  box-shadow: 0 14px 28px rgba(201, 100, 66, 0.20), 0 0 0 1px rgba(201, 100, 66, 0.22);
}

.desktop-close-option--quit .desktop-close-option__icon {
  background: var(--error);
  box-shadow: 0 14px 28px rgba(181, 51, 51, 0.18), 0 0 0 1px rgba(181, 51, 51, 0.20);
}

.desktop-close-option__copy {
  min-width: 0;
  display: grid;
  gap: 8px;
}

.desktop-close-option__copy strong {
  display: block;
  font-family: var(--font);
  font-size: 22px;
  font-weight: 500;
  line-height: 1.2;
  letter-spacing: 0;
  color: var(--text);
}

.desktop-close-option__copy span {
  display: block;
  font-size: 17px;
  line-height: 1.4;
  color: var(--text-muted);
}

.desktop-close-remember {
  --n-text-color: var(--text-muted) !important;
  --n-color-checked: var(--accent) !important;
  --n-border-checked: 1px solid var(--accent) !important;
  --n-border-focus: 1px solid var(--focus) !important;
  font-size: 17px;
}

@media (max-width: 640px) {
  :global(.desktop-close-modal.n-card) {
    width: calc(100vw - 32px);
  }

  .desktop-close-card {
    max-height: calc(100dvh - 32px);
    padding: 34px 24px 28px;
  }

  .desktop-close-dismiss {
    top: 16px;
    right: 16px;
  }

  .desktop-close-header h2 {
    font-size: 26px;
  }

  .desktop-close-header p {
    font-size: 16px;
  }

  .desktop-close-option {
    min-height: 104px;
    gap: 16px;
    padding: 18px;
  }

  .desktop-close-option__icon {
    width: 58px;
    height: 58px;
    flex-basis: 58px;
    border-radius: 16px;
  }

  .desktop-close-option__copy strong {
    font-size: 20px;
  }

  .desktop-close-option__copy span,
  .desktop-close-remember {
    font-size: 15px;
  }
}
</style>
