<template>
  <div class="resource-index p-4">
    <!-- Filter pills -->
    <div class="filter-bar mb-4 flex gap-2">
      <NButtonGroup>
        <NButton
          v-for="f in filters"
          :key="f.value"
          :type="filter === f.value ? 'primary' : 'default'"
          @click="setFilter(f.value)"
        >
          {{ f.label.value }}
        </NButton>
      </NButtonGroup>
    </div>

    <!-- Resource count -->
    <div class="text-sm text-gray-500 mb-2">
      {{ filteredResources.length }} {{ t('filter.items', { count: filteredResources.length }) }}
    </div>

    <!-- Resource table -->
    <NDataTable
      :columns="columns"
      :data="filteredResources"
      :pagination="{ pageSize: 20 }"
      :virtual="true"
      :row-key="(row: MediaInfo) => row.UrlSign"
      striped
    />

    <!-- Preview modal -->
    <Preview
      v-if="previewRow"
      :show-modal="showPreview"
      :preview-row="previewRow"
      @update:show-modal="showPreview = $event"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, h, ref } from 'vue'
import { NDataTable, NButton, NButtonGroup, NTag } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useResourceStore } from '@/stores/resourceStore'
import type { MediaInfo } from '@/stores/resourceStore'
import ResourceAction from '@/components/ResourceAction.vue'
import Preview from '@/components/Preview.vue'

const { t } = useI18n()
const store = useResourceStore()

const filter = computed(() => store.filter)
const filteredResources = computed(() => store.filteredResources)

const filters = [
  { value: 'all' as const, label: computed(() => t('filter.all')) },
  { value: 'video' as const, label: computed(() => t('filter.video')) },
  { value: 'audio' as const, label: computed(() => t('filter.audio')) },
  { value: 'image' as const, label: computed(() => t('filter.image')) },
]

const setFilter = (f: typeof filter.value) => {
  store.setFilter(f)
}

const previewRow = ref<MediaInfo | null>(null)
const showPreview = ref(false)

const handlePreview = (row: MediaInfo) => {
  previewRow.value = row
  showPreview.value = true
}

const handleDelete = (urlSign: string) => {
  store.removeResource(urlSign)
}

const columns = computed(() => [
  {
    title: t('column.url'),
    key: 'Url',
    width: 200,
    ellipsis: true,
    render: (row: MediaInfo) => {
      const canPreview = ['video', 'audio', 'm3u8', 'live'].includes(row.Classify)
      return h('a', {
        href: 'javascript:void(0)',
        onClick: () => canPreview ? handlePreview(row) : null,
        class: canPreview ? 'text-blue-500 underline cursor-pointer' : 'text-gray-400',
      }, row.Url)
    }
  },
  {
    title: t('column.type'),
    key: 'Classify',
    width: 80,
    render: (row: MediaInfo) => {
      const colors: Record<string, string> = { video: 'info', audio: 'warning', image: 'success', live: 'error', m3u8: 'warning' }
      return h(NTag, { type: colors[row.Classify] as any || 'default', size: 'small' }, () => row.Classify)
    }
  },
  {
    title: t('column.size'),
    key: 'Size',
    width: 100,
    render: (row: MediaInfo) => formatSize(row.Size)
  },
  {
    title: t('column.domain'),
    key: 'Domain',
    width: 120,
    ellipsis: true
  },
  {
    title: t('column.description'),
    key: 'Description',
    ellipsis: true,
    render: (row: MediaInfo) => {
      if (row.Description) return row.Description
      // Fallback: extract filename/host from URL (same logic as old monitor_web)
      try {
        const u = new URL(row.Url)
        const parts = u.pathname.split('/')
        const last = parts[parts.length - 1]
        if (last && last.includes('.')) return decodeURIComponent(last)
        return u.hostname
      } catch {
        return row.Url || '-'
      }
    }
  },
  {
    title: t('column.action'),
    key: 'actions',
    width: 200,
    render: (row: MediaInfo) => h(ResourceAction, { row, onDelete: handleDelete })
  },
])

const formatSize = (bytes: number) => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}
</script>
