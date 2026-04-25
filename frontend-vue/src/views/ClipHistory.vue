<template>
  <div>
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('clipHistory.title') }}</div>
        <div class="page-desc">{{ t('clipHistory.desc') }}</div>
      </div>
    </div>

    <!-- Filter toolbar -->
    <div class="filter-bar" style="margin-bottom:16px">
      <NSelect
        v-model:value="filterAccountId"
        :options="accountOptions"
        :placeholder="t('clipHistory.filterAccount')"
        clearable
        style="width: 200px"
        @update:value="handleFilterChange"
      />
      <NSelect
        v-model:value="filterStatus"
        :options="statusOptions"
        :placeholder="t('clipHistory.filterStatus')"
        clearable
        style="width: 160px"
        @update:value="handleFilterChange"
      />
      <NButton @click="refresh">
        <template #icon>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
            <polyline points="23 4 23 10 17 10"/>
            <polyline points="1 20 1 14 7 14"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
        </template>
        {{ t('clipHistory.refresh') }}
      </NButton>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="text-sm text-dim" style="padding:16px 0">
      {{ t('clipHistory.loading') }}
    </div>

    <!-- Task table -->
    <NDataTable
      v-else
      :columns="columns"
      :data="tasks"
      :pagination="pagination"
      :row-key="(row: ClipTask) => row.id"
      striped
    />

    <!-- Detail modal -->
    <ClipDetailModal
      v-if="detailId !== null"
      :id="detailId"
      @close="detailId = null"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { h } from 'vue'
import { NDataTable, NButton, NSelect, NTag, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { ClipTask } from '@/api/clips'
import clipsApi from '@/api/clips'
import configApi from '@/api/config'
import ClipDetailModal from '@/components/ClipDetailModal.vue'

const { t } = useI18n()
const message = useMessage()

const loading = ref(false)
const tasks = ref<ClipTask[]>([])
const accounts = ref<{ id: number; name: string }[]>([])

const filterAccountId = ref<number | null>(null)
const filterStatus = ref<string | null>(null)
const detailId = ref<number | null>(null)

// Pagination
const pagination = ref({
  page: 1,
  pageSize: 20,
  showSizePicker: true,
  pageSizes: [10, 20, 50],
  onChange: (page: number) => {
    pagination.value.page = page
    fetchTasks()
  },
  onUpdatePageSize: (size: number) => {
    pagination.value.pageSize = size
    pagination.value.page = 1
    fetchTasks()
  },
})

const accountOptions = computed(() => [
  { label: t('clipHistory.filterAccount'), value: -1 },
  ...accounts.value.map(a => ({ label: a.name, value: a.id })),
])

const statusOptions = [
  { label: t('clipHistory.filterStatus'), value: '' },
  { label: t('clipHistory.statusPending'), value: 'pending' },
  { label: t('clipHistory.statusRunning'), value: 'running' },
  { label: t('clipHistory.statusDone'), value: 'done' },
  { label: t('clipHistory.statusError'), value: 'error' },
]

const statusTagType = (status: string) => {
  const map: Record<string, 'default' | 'info' | 'success' | 'error'> = {
    pending: 'default',
    running: 'info',
    done: 'success',
    error: 'error',
  }
  return map[status] || 'default'
}

const statusLabel = (status: string) => {
  const map: Record<string, string> = {
    pending: t('clipHistory.statusPending'),
    running: t('clipHistory.statusRunning'),
    done: t('clipHistory.statusDone'),
    error: t('clipHistory.statusError'),
  }
  return map[status] || status
}

const columns = computed(() => [
  {
    title: t('clipHistory.tableId'),
    key: 'id',
    width: 80,
  },
  {
    title: t('clipHistory.tableAccount'),
    key: 'account_name',
    width: 140,
    ellipsis: true,
  },
  {
    title: t('clipHistory.tableTitle'),
    key: 'video_title',
    ellipsis: true,
    render: (row: ClipTask) => row.video_title || t('clip.unknownVideo'),
  },
  {
    title: t('clipHistory.tableStatus'),
    key: 'status',
    width: 110,
    render: (row: ClipTask) =>
      h(NTag, { type: statusTagType(row.status), size: 'small' }, () => statusLabel(row.status)),
  },
  {
    title: t('clipHistory.tableClips'),
    key: 'clip_count',
    width: 80,
  },
  {
    title: t('clipHistory.tableCollection'),
    key: 'collection_count',
    width: 80,
  },
  {
    title: t('clipHistory.tableCreated'),
    key: 'created_at',
    width: 170,
    render: (row: ClipTask) => formatDate(row.created_at),
  },
  {
    title: t('clipHistory.tableActions'),
    key: 'actions',
    width: 120,
    render: (row: ClipTask) =>
      h(
        'a',
        {
          href: 'javascript:void(0)',
          style: 'color:var(--accent);text-decoration:underline;cursor:pointer;font-size:13px',
          onClick: () => { detailId.value = row.id },
        },
        t('clip.btnDetail')
      ),
  },
])

const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  try {
    const d = new Date(dateStr)
    return d.toLocaleString()
  } catch {
    return dateStr
  }
}

const fetchTasks = async () => {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: pagination.value.page,
      limit: pagination.value.pageSize,
    }
    if (filterAccountId.value !== null && filterAccountId.value !== -1) {
      params.account_id = filterAccountId.value
    }
    if (filterStatus.value) {
      params.status = filterStatus.value
    }
    const res = await clipsApi.list(params)
    tasks.value = res.data.items || []
    pagination.value.page = res.data.page
  } catch {
    message.error(t('clip.loadFailed'))
  } finally {
    loading.value = false
  }
}

const fetchAccounts = async () => {
  try {
    const res = await configApi.listAccounts()
    accounts.value = res.data || []
  } catch {
    // silently fail, account filter stays empty
  }
}

const handleFilterChange = () => {
  pagination.value.page = 1
  fetchTasks()
}

const refresh = () => {
  fetchTasks()
}

onMounted(() => {
  fetchTasks()
  fetchAccounts()
})
</script>

<style scoped>
/* Page-specific styles only — page-header/page-title inherit from layout.css */
</style>
