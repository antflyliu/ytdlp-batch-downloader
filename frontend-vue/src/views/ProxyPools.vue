<template>
  <div class="proxy-pools-page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('proxyPools.title') }}</div>
        <div class="page-desc text-sm text-gray-500">{{ t('proxyPools.desc') }}</div>
      </div>
    </div>

    <!-- Card -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon" style="background:var(--accent-dim);color:var(--accent)" aria-hidden="true">代</div>
          <span>{{ t('account.title') }}</span>
        </div>
        <div class="actions">
          <NButton type="primary" @click="openAddModal">
            <template #icon>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2v20M2 12h20" stroke="currentColor" stroke-width="2.5" fill="none"/></svg>
            </template>
            {{ t('proxyPools.addNode') }}
          </NButton>
          <NButton quaternary @click="openDemoModal">
            <template #icon>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </template>
            {{ t('proxyPools.watchDemo') }}
          </NButton>
        </div>
      </div>

      <!-- Meta info bar -->
      <div class="card-proxy-pool-meta">
        <span class="pp-demo-note">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20"/><path d="M2 12h20"/></svg>
          {{ t('proxyPools.maskedNote') }}
        </span>
        <span class="card-proxy-pool-meta__hint">{{ t('proxyPools.metaHint') }}</span>
      </div>

      <!-- Table -->
      <div v-if="pools.length > 0" class="table-wrap">
        <NDataTable
          :columns="columns"
          :data="pools"
          :pagination="{ pageSize: 20 }"
          :virtual="true"
          :row-key="(row: ProxyPoolNode) => String(row.id)"
          striped
        />
      </div>

      <!-- Empty state -->
      <div v-else class="empty-state">
        <div class="empty-icon" aria-hidden="true">—</div>
        <div class="empty-title">{{ t('proxyPools.emptyTitle') }}</div>
        <div class="empty-desc">{{ t('proxyPools.emptyDesc') }}</div>
        <NButton type="primary" @click="openAddModal">
          {{ t('proxyPools.addFirst') }}
        </NButton>
      </div>
    </div>

    <!-- Add/Edit Modal -->
    <NModal
      v-model:show="showFormModal"
      preset="card"
      :title="editingNode ? t('proxy.modalTitleEdit') : t('proxy.modalTitleAdd')"
      style="width: 480px"
      :mask-closable="false"
    >
      <NForm :model="formData" label-placement="top">
        <NFormItem :label="t('proxyPools.nodeName')" required>
          <NInput
            v-model:value="formData.name"
            :placeholder="t('proxyPools.nodeNamePlaceholder')"
          />
        </NFormItem>
        <NFormItem :label="t('proxyPools.proxyUrl')" required>
          <NInput
            v-model:value="formData.proxy_url"
            :placeholder="t('proxyPools.nodeNamePlaceholder')"
          />
          <template #feedback>
            <div class="form-hint">{{ t('proxyPools.proxyHint') }}</div>
          </template>
        </NFormItem>
        <NFormItem :label="t('proxyPools.enableNow')">
          <NSwitch v-model:value="formData.enabled" />
          <template #feedback>
            <div class="form-hint">{{ t('proxyPools.enableNowHint') }}</div>
          </template>
        </NFormItem>
      </NForm>
      <template #footer>
        <div class="modal-footer">
          <NButton @click="showFormModal = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" :loading="saving" @click="saveNode">
            {{ t('proxyPools.saveNode') }}
          </NButton>
        </div>
      </template>
    </NModal>

    <!-- Demo Modal -->
    <NModal
      v-model:show="showDemoModal"
      preset="card"
      :title="t('proxyPools.watchDemo')"
      style="width: 720px; max-width: 90vw"
    >
      <div class="demo-iframe-wrap">
        <iframe
          src="/proxy-pool-feature.html"
          frameborder="0"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowfullscreen
          style="width: 100%; height: 405px; border-radius: 8px;"
        />
      </div>
    </NModal>

    <!-- Delete Confirm -->
    <NModal
      v-model:show="showDeleteModal"
      preset="dialog"
      :title="t('proxy.deleteConfirmTitle').replace('{name}', deletingNode?.name || '')"
      :content="t('proxy.deleteConfirmMsg')"
      negative-text=""
      positive-text=""
      :closable="false"
    >
      <template #icon><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></template>
      <template #action>
        <div style="display:flex;gap:8px">
          <NButton size="small" @click="showDeleteModal = false">{{ t('common.cancel') }}</NButton>
          <NButton size="small" type="error" :loading="deleting" @click="confirmDelete">
            {{ t('proxy.btnDelete') }}
          </NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSwitch,
  useMessage,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import request from '@/api/request'

const { t } = useI18n()
const message = useMessage()

// ── Types ──────────────────────────────────────────────────────────────────────

interface ProxyPoolNode {
  id: number
  name: string
  proxy_url: string
  enabled: boolean
  status?: string
  created_at?: string
}

// ── State ──────────────────────────────────────────────────────────────────────

const pools = ref<ProxyPoolNode[]>([])
const saving = ref(false)
const deleting = ref(false)

// Form modal
const showFormModal = ref(false)
const editingNode = ref<ProxyPoolNode | null>(null)
const formData = reactive({
  name: '',
  proxy_url: '',
  enabled: true,
})

// Demo modal
const showDemoModal = ref(false)

// Delete modal
const showDeleteModal = ref(false)
const deletingNode = ref<ProxyPoolNode | null>(null)

// ── API ────────────────────────────────────────────────────────────────────────

async function loadPools() {
  try {
    const resp = await request.get('/api/proxy-pools')
    pools.value = Array.isArray(resp.data) ? resp.data : (resp.data?.data || [])
  } catch (e: any) {
    message.error(e?.response?.data?.error || t('proxy.loadFailed') || 'Failed to load')
  }
}

async function saveNode() {
  if (!formData.name.trim() || !formData.proxy_url.trim()) {
    message.error(t('proxy.nameAndUrlRequired'))
    return
  }
  saving.value = true
  try {
    const body = {
      name: formData.name.trim(),
      proxy_url: formData.proxy_url.trim(),
      enabled: formData.enabled,
    }
    if (editingNode.value) {
      await request.post(`/api/proxy-pools/${editingNode.value.id}/update`, body)
      message.success(t('proxy.saved'))
    } else {
      await request.post('/api/proxy-pools', body)
      message.success(t('proxy.added'))
    }
    showFormModal.value = false
    await loadPools()
  } catch (e: any) {
    message.error(e?.response?.data?.error || t('proxy.saveFailed'))
  } finally {
    saving.value = false
  }
}

async function toggleNode(node: ProxyPoolNode) {
  try {
    await request.post(`/api/proxy-pools/${node.id}/update`, { enabled: !node.enabled })
    message.success(!node.enabled ? t('proxy.enabled') : t('proxy.disabled'))
    await loadPools()
  } catch (e: any) {
    message.error(e?.response?.data?.error || t('provider.operationError'))
  }
}

async function confirmDelete() {
  if (!deletingNode.value) return
  deleting.value = true
  try {
    const resp = await request.delete(`/api/proxy-pools/${deletingNode.value.id}`)
    const affected = resp.data?.affected_accounts?.length || 0
    if (affected > 0) {
      message.warning(t('proxy.deletedWithAccounts').replace('{n}', String(affected)))
    } else {
      message.success(t('proxy.deleteSuccess'))
    }
    showDeleteModal.value = false
    await loadPools()
  } catch (e: any) {
    message.error(e?.response?.data?.error || t('provider.operationError'))
  } finally {
    deleting.value = false
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function maskProxyUrl(url: string): string {
  if (!url) return ''
  try {
    const u = new URL(url.startsWith('http') ? url : `http://${url}`)
    return u.hostname
  } catch {
    // No protocol, try to extract host:port
    const match = url.match(/([^:/]+)(:\d+)?(\/.*)?$/)
    return match ? (match[2] ? `${match[1]}${match[2]}` : match[1]) : url
  }
}

// ── Modals ─────────────────────────────────────────────────────────────────────

function openAddModal() {
  editingNode.value = null
  formData.name = ''
  formData.proxy_url = ''
  formData.enabled = true
  showFormModal.value = true
}

function openEditModal(node: ProxyPoolNode) {
  editingNode.value = node
  formData.name = node.name
  formData.proxy_url = node.proxy_url
  formData.enabled = !!node.enabled
  showFormModal.value = true
}

function openDemoModal() {
  showDemoModal.value = true
}

function openDeleteModal(node: ProxyPoolNode) {
  deletingNode.value = node
  showDeleteModal.value = true
}

// ── Table Columns ──────────────────────────────────────────────────────────────

const columns = computed(() => [
  {
    title: t('proxyPools.tableId'),
    key: 'id',
    width: 70,
    render: (row: ProxyPoolNode) => h('span', { style: 'font-family: var(--mono)' }, String(row.id)),
  },
  {
    title: t('proxyPools.tableName'),
    key: 'name',
    width: 180,
    ellipsis: true,
  },
  {
    title: t('proxyPools.tableNode'),
    key: 'proxy_url',
    ellipsis: { tooltip: true },
    width: 280,
    render: (row: ProxyPoolNode) => h('span', { title: row.proxy_url, style: 'font-family: var(--mono); font-size: 12px' }, maskProxyUrl(row.proxy_url)),
  },
  {
    title: t('proxyPools.tableStatus'),
    key: 'status',
    width: 100,
    render: (row: ProxyPoolNode) => {
      const online = row.enabled
      return h('div', { class: 'proxy-pool-status' }, [
        h('span', { class: `proxy-dot ${online ? 'on' : 'off'}` }),
        h('span', { class: online ? 'proxy-pool-status__on' : 'proxy-pool-status__off' }, online ? t('proxy.statusOnline') : t('proxy.statusOffline')),
      ])
    },
  },
  {
    title: t('proxyPools.tableActions'),
    key: 'actions',
    width: 220,
    render: (row: ProxyPoolNode) =>
      h('div', { class: 'actions' }, [
        h(NButton, { size: 'small', quaternary: true, onClick: () => openEditModal(row) }, () => t('proxy.btnEdit')),
        h(NButton, {
          size: 'small',
          quaternary: true,
          type: row.enabled ? 'warning' : 'success',
          onClick: () => toggleNode(row),
        }, () => row.enabled ? t('proxy.btnDisable') : t('proxy.btnEnable')),
        h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => openDeleteModal(row) }, () => t('proxy.btnDelete')),
      ]),
  },
])

// ── Lifecycle ──────────────────────────────────────────────────────────────────

onMounted(() => {
  loadPools()
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
.card {
  background: var(--surface2);
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  overflow: hidden;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  gap: 12px;
}
.card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 500;
}
.card-title-icon {
  width: 28px;
  height: 28px;
  border-radius: var(--r-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  flex-shrink: 0;
}
.card-proxy-pool-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-muted);
  background: var(--surface);
}
.pp-demo-note {
  display: flex;
  align-items: center;
  gap: 4px;
}
.table-wrap {
  overflow-x: auto;
}
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 16px;
  gap: 12px;
  text-align: center;
}
.empty-icon {
  font-size: 32px;
  color: var(--text-muted);
  opacity: 0.4;
}
.empty-title {
  font-size: 15px;
  font-weight: 500;
  color: var(--text);
}
.empty-desc {
  font-size: 13px;
  color: var(--text-muted);
  max-width: 360px;
}
.form-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.demo-iframe-wrap {
  border-radius: 8px;
  overflow: hidden;
}

/* Proxy pool status dots */
.proxy-pool-status {
  display: flex;
  align-items: center;
  gap: 6px;
}
.proxy-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.proxy-dot.on {
  background: #52c41a;
}
.proxy-dot.off {
  background: #d9d9d9;
}
.proxy-pool-status__on {
  color: #52c41a;
  font-size: 13px;
}
.proxy-pool-status__off {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
