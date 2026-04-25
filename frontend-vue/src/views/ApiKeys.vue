<template>
  <div>
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('nav.apiKeys') }}</div>
        <div class="page-desc">{{ t('apiKeys.desc') }}</div>
      </div>
      <NButton type="primary" size="small" @click="openAdd">
        {{ t('apiKeys.addKey') }}
      </NButton>
    </div>

    <!-- Hint text -->
    <div class="hint-text">{{ t('apiKeys.hint') }}</div>

    <!-- Key list -->
    <div class="key-list" v-if="!loading">
      <template v-if="error">
        <div class="ak-empty">
          <div class="ak-empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
            </svg>
          </div>
          <div class="ak-empty-title">{{ t('apiKeysUi.emptyLoadTitle') }}</div>
          <div class="ak-empty-desc">{{ t('apiKeysUi.emptyLoadDesc') }}</div>
          <NButton size="small" @click="loadKeys">{{ t('apiKeysUi.emptyReload') }}</NButton>
        </div>
      </template>

      <template v-else-if="keys.length === 0">
        <div class="ak-empty">
          <div class="ak-empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
            </svg>
          </div>
          <div class="ak-empty-title">{{ t('apiKeysUi.emptyNoKeysTitle') }}</div>
          <div class="ak-empty-desc">{{ t('apiKeysUi.emptyNoKeysDesc') }}</div>
          <NButton type="primary" size="small" @click="openAdd">{{ t('apiKeysUi.emptyAddFirst') }}</NButton>
        </div>
      </template>

      <template v-else>
        <div v-for="k in keys" :key="k.id" class="ak-card">
          <!-- Ring chart -->
          <div class="ak-ring">
            <svg viewBox="0 0 56 56">
              <circle class="ak-ring-bg" cx="28" cy="28" r="22"/>
              <circle
                class="ak-ring-progress"
                cx="28" cy="28" r="22"
                :stroke="ringColor(k)"
                :stroke-dasharray="`${ringDash(k)} ${ringGap(k)}`"
              />
            </svg>
            <div class="ak-ring-text">
              <span class="ak-ring-pct" :style="{ color: ringColor(k) }">{{ ringPct(k) }}</span>
              <span class="ak-ring-label">%</span>
            </div>
          </div>

          <!-- Info -->
          <div class="ak-info">
            <div class="ak-name-row">
              <span class="ak-name">{{ k.name }}</span>
              <NTag :type="k.is_active ? 'success' : 'error'" size="small" round>
                {{ k.is_active ? t('apiKeysUi.statusOn') : t('apiKeysUi.statusOff') }}
              </NTag>
            </div>
            <div class="ak-key">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/><path d="M12 8v4l2 2"/>
              </svg>
              {{ k.key_value }}
            </div>
            <div class="ak-quota-bar">
              <div class="ak-quota-fill" :style="{ width: ringPct(k) + '%', background: ringColor(k) }"></div>
            </div>
            <div class="ak-quota-stats">
              <span>{{ t('apiKeysUi.quotaUsed') }} <strong class="used">{{ k.quota_used.toLocaleString() }}</strong></span>
              <span>{{ t('apiKeysUi.quotaLimit') }} <strong>{{ k.daily_quota.toLocaleString() }}</strong></span>
              <span>{{ t('apiKeysUi.quotaRemaining') }} <strong class="remaining">{{ Math.max(k.daily_quota - k.quota_used, 0).toLocaleString() }}</strong></span>
              <span>{{ t('apiKeysUi.scans') }} <strong>{{ k.scans_done || 0 }}</strong> {{ t('apiKeysUi.times') }}</span>
            </div>
          </div>

          <!-- Actions -->
          <div class="ak-actions">
            <NButton size="tiny" quaternary @click="openEdit(k)" :title="t('apiKeysUi.editTitle')">
              <template #icon>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
              </template>
            </NButton>
            <NButton size="tiny" quaternary type="error" @click="confirmDelete(k)" :title="t('apiKeysUi.deleteTitle')">
              <template #icon>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6l-1 14H6L5 6"/>
                  <path d="M10 11v6M14 11v6"/>
                  <path d="M9 6V4h6v2"/>
                </svg>
              </template>
            </NButton>
          </div>
        </div>
      </template>
    </div>

    <!-- Loading skeleton -->
    <div v-else class="key-list">
      <div v-for="i in 3" :key="i" class="ak-card ak-card--skeleton">
        <div class="ak-ring ak-ring--skeleton"></div>
        <div class="ak-info">
          <div class="skel-line skel-line--name"></div>
          <div class="skel-line skel-line--key"></div>
          <div class="skel-line skel-line--bar"></div>
        </div>
      </div>
    </div>

    <!-- Add/Edit modal -->
    <NModal
      v-model:show="showModal"
      preset="card"
      :title="isEditing ? t('apiKeyForm.editTitle') : t('apiKeyForm.addTitle')"
      style="width: 480px; max-width: 95vw"
      :mask-closable="false"
    >
      <NForm ref="formRef" :model="form" label-placement="top" :rules="rules">
        <!-- Identity section -->
        <div class="ak-form-section-title">{{ t('apiKeyForm.title') }}</div>
        <NFormItem :label="t('apiKeyForm.keyName')" path="name">
          <NInput v-model:value="form.name" :placeholder="t('apiKeyForm.keyNamePlaceholder')" clearable />
        </NFormItem>
        <NFormItem :label="t('apiKeyForm.keyValue')" path="key_value">
          <NInput
            v-model:value="form.key_value"
            :placeholder="t('apiKeyForm.keyValueHint')"
            :readonly="isEditing"
            :disabled="isEditing"
            clearable
          />
          <template #feedback>
            <div class="form-hint">{{ isEditing ? t('apiKeyForm.keyValueHintEdit') : t('apiKeyForm.keyValueHint') }}</div>
          </template>
        </NFormItem>

        <!-- Quota section -->
        <div class="ak-form-section-title ak-form-section-title--quota">{{ t('apiKeyForm.quota') }}</div>
        <NFormItem :label="t('apiKeyForm.quota')" path="daily_quota">
          <NInputNumber
            v-model:value="form.daily_quota"
            :min="0"
            :max="1000000"
            style="width: 100%"
          />
          <template #feedback>
            <div class="form-hint">{{ t('apiKeyForm.quotaHint') }}</div>
          </template>
        </NFormItem>
        <NFormItem :label="t('apiKeyForm.enableKey')">
          <NSwitch v-model:value="form.is_active" />
        </NFormItem>
      </NForm>

      <template #footer>
        <div class="modal-footer">
          <NButton @click="showModal = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="saving" @click="save">{{ t('apiKeyForm.save') }}</NButton>
        </div>
      </template>
    </NModal>

    <!-- Delete confirm -->
    <NModal
      v-model:show="showDeleteConfirm"
      preset="card"
      :title="t('apiKeysUi.deleteConfirmTitle').replace('{name}', deletingKey?.name || '')"
      style="width: 420px; max-width: 95vw"
    >
      <div style="color: var(--text-muted); margin-bottom: 8px">{{ t('apiKeysUi.deleteConfirmMsg') }}</div>
      <template #footer>
        <div class="modal-footer">
          <NButton @click="showDeleteConfirm = false">{{ t('common.cancel') }}</NButton>
          <NButton type="error" :loading="deleting" @click="doDelete">{{ t('apiKeysUi.deleteConfirmBtn') }}</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'
import {
  NButton, NModal, NForm, NFormItem, NInput, NInputNumber,
  NSwitch, NTag,
} from 'naive-ui'
import type { FormRules, FormItemRule } from 'naive-ui'
import request from '@/api/request'

const { t } = useI18n()
const message = useMessage()

// ── Types ────────────────────────────────────────────────────────────────────
interface ApiKey {
  id: number
  name: string
  key_value: string
  daily_quota: number
  quota_used: number
  scans_done: number
  blocked_scans: number
  is_active: boolean
  created_at: string
}

// ── State ────────────────────────────────────────────────────────────────────
const keys = ref<ApiKey[]>([])
const loading = ref(false)
const error = ref(false)
const showModal = ref(false)
const isEditing = ref(false)
const saving = ref(false)
const formRef = ref<any>(null)

const form = reactive({
  id: null as number | null,
  name: '',
  key_value: '',
  daily_quota: 10000,
  is_active: true,
})

const rules: FormRules = {
  name: { required: true, message: t('apiKeysUi.toastNameRequired'), trigger: 'blur' as FormItemRule['trigger'] },
  key_value: isEditing.value ? [] : { required: true, message: t('apiKeysUi.toastKeyRequired'), trigger: 'blur' as FormItemRule['trigger'] },
}

// Delete
const showDeleteConfirm = ref(false)
const deletingKey = ref<ApiKey | null>(null)
const deleting = ref(false)

// ── Ring chart helpers ──────────────────────────────────────────────────────
const RING_R = 22
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_R

const ringPct = (k: ApiKey) => {
  if (!k.daily_quota) return 0
  return Math.min(Math.round((k.quota_used / k.daily_quota) * 100), 100)
}

const ringColor = (k: ApiKey) => {
  const p = ringPct(k)
  if (p >= 90) return 'var(--error)'
  if (p >= 70) return 'var(--warning)'
  return 'var(--accent)'
}

const ringDash = (k: ApiKey) => {
  return ((ringPct(k) / 100) * RING_CIRCUMFERENCE).toFixed(1)
}

const ringGap = (k: ApiKey) => {
  return (RING_CIRCUMFERENCE - (ringPct(k) / 100) * RING_CIRCUMFERENCE).toFixed(1)
}

// ── API ──────────────────────────────────────────────────────────────────────
const loadKeys = async () => {
  loading.value = true
  error.value = false
  try {
    const resp = await request.get<ApiKey[]>('/api/api-keys')
    keys.value = Array.isArray(resp.data) ? resp.data : []
  } catch {
    error.value = true
    message.warning(t('apiKeysUi.emptyLoadTitle'))
  } finally {
    loading.value = false
  }
}

const openAdd = () => {
  isEditing.value = false
  form.id = null
  form.name = ''
  form.key_value = ''
  form.daily_quota = 10000
  form.is_active = true
  showModal.value = true
}

const openEdit = (k: ApiKey) => {
  isEditing.value = true
  form.id = k.id
  form.name = k.name
  form.key_value = k.key_value
  form.daily_quota = k.daily_quota
  form.is_active = k.is_active
  showModal.value = true
}

const save = async () => {
  // Validate
  if (!form.name.trim()) {
    message.warning(t('apiKeysUi.toastNameRequired'))
    return
  }
  if (!isEditing.value && !form.key_value.trim()) {
    message.warning(t('apiKeysUi.toastKeyRequired'))
    return
  }

  saving.value = true
  try {
    const body = {
      name: form.name.trim(),
      daily_quota: form.daily_quota,
      is_active: form.is_active,
      ...(isEditing.value ? {} : { key_value: form.key_value.trim() }),
    }

    let resp: any
    if (isEditing.value && form.id) {
      resp = await request.post(`/api/api-keys/${form.id}/update`, body)
    } else {
      resp = await request.post('/api/api-keys', body)
    }

    if (resp.data?.error) {
      message.error(resp.data.error)
      return
    }
    message.success(t('apiKeysUi.toastSaved'))
    showModal.value = false
    await loadKeys()
  } catch (e: any) {
    message.error(e?.message || t('apiKeysUi.saveConfigFail'))
  } finally {
    saving.value = false
  }
}

const confirmDelete = (k: ApiKey) => {
  deletingKey.value = k
  showDeleteConfirm.value = true
}

const doDelete = async () => {
  if (!deletingKey.value) return
  deleting.value = true
  try {
    const resp: any = await request.delete(`/api/api-keys/${deletingKey.value.id}`)
    if (resp.data?.error) {
      message.error(resp.data.error)
      return
    }
    if (resp.data?.affected_accounts?.length > 0) {
      message.success(t('apiKeysUi.toastDeletedWithAccounts', { n: resp.data.affected_accounts.length }))
    } else {
      message.success(t('apiKeysUi.toastDeleted'))
    }
    showDeleteConfirm.value = false
    deletingKey.value = null
    await loadKeys()
  } catch (e: any) {
    message.error(e?.message || t('apiKeysUi.saveConfigFail'))
  } finally {
    deleting.value = false
  }
}

// ── Lifecycle ────────────────────────────────────────────────────────────────
onMounted(() => {
  loadKeys()
})
</script>

<style scoped>
.hint-text {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 16px;
  line-height: 1.6;
}

.key-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* API Key card */
.ak-card {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  gap: 16px;
  transition: border-color 0.15s, box-shadow 0.2s;
}
.ak-card:hover {
  border-color: rgba(201, 100, 66, 0.4);
  box-shadow: 0 0 0 1px rgba(201, 100, 66, 0.1);
}
.ak-card--skeleton {
  opacity: 0.6;
  pointer-events: none;
}

/* Ring chart */
.ak-ring {
  flex-shrink: 0;
  position: relative;
  width: 56px;
  height: 56px;
}
.ak-ring svg {
  transform: rotate(-90deg);
  width: 56px;
  height: 56px;
}
.ak-ring-bg {
  fill: none;
  stroke: var(--surface3);
  stroke-width: 4;
}
.ak-ring-progress {
  fill: none;
  stroke-width: 4;
  stroke-linecap: round;
  transition: stroke-dasharray 0.4s ease-out, stroke 0.3s;
}
.ak-ring-text {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.ak-ring-pct {
  font-size: 12px;
  font-weight: 700;
  font-family: var(--mono);
}
.ak-ring-label {
  font-size: 8px;
  color: var(--text-dim);
}
.ak-ring--skeleton {
  background: var(--surface3);
  border-radius: 50%;
}

/* Info */
.ak-info {
  flex: 1;
  min-width: 0;
}
.ak-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.ak-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.ak-key {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.ak-key svg {
  flex-shrink: 0;
}

/* Quota bar */
.ak-quota-bar {
  height: 4px;
  background: var(--surface3);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 6px;
}
.ak-quota-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s ease-out;
}
.ak-quota-stats {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.ak-quota-stats strong {
  font-family: var(--mono);
}
.ak-quota-stats .used {
  color: var(--accent);
}
.ak-quota-stats .remaining {
  color: var(--success);
}

/* Actions */
.ak-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

/* Empty state */
.ak-empty {
  text-align: center;
  padding: 48px 24px;
  background: var(--surface2);
  border-radius: 12px;
  border: 1px dashed var(--border);
}
.ak-empty-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto 16px;
  background: var(--surface3);
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ak-empty-icon svg {
  width: 28px;
  height: 28px;
  color: var(--text-dim);
  opacity: 0.5;
}
.ak-empty-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 6px;
}
.ak-empty-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 16px;
}

/* Form sections */
.ak-form-section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.8px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.ak-form-section-title::before {
  content: '';
  width: 3px;
  height: 12px;
  border-radius: 2px;
  background: var(--accent);
}
.ak-form-section-title--quota {
  color: var(--warning);
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.ak-form-section-title--quota::before {
  background: var(--warning);
}
.form-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
  line-height: 1.5;
}

/* Modal footer */
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* Skeleton */
.skel-line {
  background: var(--surface3);
  border-radius: 4px;
  margin-bottom: 6px;
}
.skel-line--name {
  height: 14px;
  width: 40%;
}
.skel-line--key {
  height: 11px;
  width: 60%;
}
.skel-line--bar {
  height: 4px;
  width: 80%;
}
</style>
