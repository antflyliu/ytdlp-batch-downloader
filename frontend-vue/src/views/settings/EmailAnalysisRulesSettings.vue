<template>
  <div>
    <RouterLink to="/settings-hub" class="back-link">
      {{ t('settings.backToSettings') }}
    </RouterLink>

    <div class="page-header">
      <div>
        <div class="page-title">{{ t('settings.emailAnalysisRulesTitle') }}</div>
        <div class="page-desc">{{ t('settings.emailAnalysisRulesDesc') }}</div>
      </div>
      <div class="rules-actions">
        <NButton :loading="loading" @click="loadRules">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>
          {{ t('settings.emailRulesRefresh') }}
        </NButton>
        <NButton :loading="validating" @click="validateEditor">
          <template #icon><NIcon><CheckmarkCircleOutline /></NIcon></template>
          {{ t('settings.emailRulesValidate') }}
        </NButton>
        <NButton type="primary" :loading="saving" @click="saveRules">
          <template #icon><NIcon><SaveOutline /></NIcon></template>
          {{ t('settings.emailRulesSave') }}
        </NButton>
      </div>
    </div>

    <div class="rules-layout">
      <section class="rules-editor">
        <NCard>
          <template #header>{{ t('settings.emailRulesEditor') }}</template>
          <div class="rules-form">
            <NInput
              v-model:value="note"
              :placeholder="t('settings.emailRulesNotePlaceholder')"
              clearable
            />
            <NInput
              v-model:value="editorText"
              type="textarea"
              :autosize="{ minRows: 22, maxRows: 34 }"
              spellcheck="false"
              class="rules-textarea"
            />
            <div class="rules-file-actions">
              <input
                ref="importInput"
                type="file"
                accept="application/json,.json"
                class="rules-file-input"
                @change="handleImportFile"
              />
              <NButton :loading="exporting" @click="exportRules">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>
                {{ t('settings.emailRulesExport') }}
              </NButton>
              <NButton :loading="importing" @click="openImportPicker">
                <template #icon><NIcon><CloudUploadOutline /></NIcon></template>
                {{ t('settings.emailRulesImport') }}
              </NButton>
            </div>
          </div>
        </NCard>
      </section>

      <aside class="rules-side">
        <NCard>
          <template #header>{{ t('settings.emailRulesValidation') }}</template>
          <NAlert
            v-if="validation"
            :type="validation.ok ? 'success' : 'error'"
            :show-icon="true"
          >
            {{ validation.ok ? t('settings.emailRulesValid') : t('settings.emailRulesInvalid') }}
          </NAlert>
          <NAlert v-else type="info" :show-icon="true">
            {{ t('settings.emailRulesValidateHint') }}
          </NAlert>
          <ul v-if="validation?.errors?.length" class="rules-errors">
            <li v-for="error in validation.errors" :key="error">{{ error }}</li>
          </ul>
        </NCard>

        <NCard>
          <template #header>{{ t('settings.emailRulesSchema') }}</template>
          <pre class="json-preview">{{ schemaText }}</pre>
        </NCard>

        <NCard>
          <template #header>{{ t('settings.emailRulesHistory') }}</template>
          <NDataTable
            :columns="historyColumns"
            :data="history"
            :pagination="{ pageSize: 6 }"
            :row-key="(row: EmailAnalysisRulesVersion) => row.version_id"
            size="small"
          />
        </NCard>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NIcon,
  NInput,
  useMessage,
} from 'naive-ui'
import {
  CheckmarkCircleOutline,
  CloudUploadOutline,
  DownloadOutline,
  RefreshOutline,
  SaveOutline,
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import emailApi, {
  type EmailAnalysisRulesValidation,
  type EmailAnalysisRulesVersion,
} from '@/api/email'

const { t } = useI18n()
const message = useMessage()

const loading = ref(false)
const saving = ref(false)
const validating = ref(false)
const importing = ref(false)
const exporting = ref(false)
const editorText = ref('{}')
const note = ref('')
const validation = ref<EmailAnalysisRulesValidation | null>(null)
const schema = ref<Record<string, unknown>>({})
const history = ref<EmailAnalysisRulesVersion[]>([])
const importInput = ref<HTMLInputElement | null>(null)
const restoringVersionId = ref('')

const schemaText = computed(() => JSON.stringify(schema.value || {}, null, 2))

const historyColumns = computed(() => [
  {
    title: t('settings.emailRulesHistoryTime'),
    key: 'created_at',
    minWidth: 150,
  },
  {
    title: t('settings.emailRulesHistorySource'),
    key: 'source',
    width: 90,
  },
  {
    title: t('settings.emailRulesHistoryNote'),
    key: 'note',
    minWidth: 150,
    ellipsis: true,
  },
  {
    title: t('settings.emailRulesHistoryAction'),
    key: 'actions',
    width: 92,
    render: (row: EmailAnalysisRulesVersion) =>
      h(
        NButton,
        {
          size: 'small',
          loading: restoringVersionId.value === row.version_id,
          onClick: () => restoreVersion(row),
        },
        () => t('settings.emailRulesRestore'),
      ),
  },
])

const parseEditorRules = () => {
  try {
    return JSON.parse(editorText.value || '{}')
  } catch {
    message.error(t('settings.emailRulesJsonInvalid'))
    return null
  }
}

const requestError = (error: unknown) => {
  const response = (error as { response?: { data?: { error?: string; details?: string[] } } }).response
  const details = response?.data?.details
  if (Array.isArray(details) && details.length) {
    return details.join('\n')
  }
  return response?.data?.error || t('emailPipeline.requestFailed')
}

const loadRules = async () => {
  loading.value = true
  try {
    const res = await emailApi.getAnalysisRules()
    const data = res.data
    const editableRules = Object.prototype.hasOwnProperty.call(data, 'raw_rules')
      ? data.raw_rules
      : data.rules
    editorText.value = JSON.stringify(editableRules ?? {}, null, 2)
    validation.value = data.validation
    schema.value = data.schema || {}
    history.value = data.history || []
  } catch (error) {
    message.error(requestError(error))
  } finally {
    loading.value = false
  }
}

const validateEditor = async () => {
  const rules = parseEditorRules()
  if (!rules) return
  validating.value = true
  try {
    const res = await emailApi.validateAnalysisRules({ rules })
    validation.value = res.data
    schema.value = res.data.schema || schema.value
    message[res.data.ok ? 'success' : 'error'](
      res.data.ok ? t('settings.emailRulesValid') : t('settings.emailRulesInvalid'),
    )
  } catch (error) {
    message.error(requestError(error))
  } finally {
    validating.value = false
  }
}

const saveRules = async () => {
  const rules = parseEditorRules()
  if (!rules) return
  saving.value = true
  try {
    await emailApi.saveAnalysisRules({ rules, note: note.value })
    message.success(t('settings.emailRulesSaved'))
    note.value = ''
    await loadRules()
  } catch (error) {
    message.error(requestError(error))
  } finally {
    saving.value = false
  }
}

const exportRules = async () => {
  exporting.value = true
  try {
    const res = await emailApi.exportAnalysisRules()
    const json = JSON.stringify(res.data, null, 2)
    const blob = new Blob([json], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `email-analysis-rules-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    message.error(requestError(error))
  } finally {
    exporting.value = false
  }
}

const openImportPicker = () => {
  importInput.value?.click()
}

const handleImportFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  importing.value = true
  try {
    const text = await file.text()
    const payload = JSON.parse(text)
    await emailApi.importAnalysisRules({ payload, note: note.value || file.name })
    message.success(t('settings.emailRulesImported'))
    note.value = ''
    await loadRules()
  } catch (error) {
    if (error instanceof SyntaxError) {
      message.error(t('settings.emailRulesJsonInvalid'))
    } else {
      message.error(requestError(error))
    }
  } finally {
    importing.value = false
    input.value = ''
  }
}

const restoreVersion = async (row: EmailAnalysisRulesVersion) => {
  restoringVersionId.value = row.version_id
  try {
    await emailApi.restoreAnalysisRules({
      version_id: row.version_id,
      note: note.value || `restore ${row.version_id}`,
    })
    message.success(t('settings.emailRulesRestored'))
    note.value = ''
    await loadRules()
  } catch (error) {
    message.error(requestError(error))
  } finally {
    restoringVersionId.value = ''
  }
}

onMounted(loadRules)
</script>

<style scoped>
.rules-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.rules-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
  gap: 12px;
}

.rules-form,
.rules-side {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rules-file-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.rules-file-input {
  display: none;
}

.rules-textarea :deep(textarea) {
  font-family: "Cascadia Mono", "Consolas", monospace;
  font-size: 12px;
  line-height: 1.55;
}

.rules-errors {
  margin: 12px 0 0;
  padding-left: 18px;
  color: var(--error);
  font-size: 12px;
  line-height: 1.55;
}

.json-preview {
  max-height: 260px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--surface-2);
  color: var(--text);
  font-family: "Cascadia Mono", "Consolas", monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
}

@media (max-width: 1080px) {
  .rules-layout {
    grid-template-columns: 1fr;
  }
}
</style>
