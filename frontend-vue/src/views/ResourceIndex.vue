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
          {{ f.label }}
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
  </div>
</template>

<script setup lang="ts">
import { computed, h } from 'vue'
import { NDataTable, NButton, NButtonGroup, NTag } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useResourceStore } from '@/stores/resourceStore'
import type { MediaInfo } from '@/stores/resourceStore'

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

// Columns: Url (link to preview), Classify badge, Size, Domain, Description, Actions
const columns = computed(() => [
  {
    title: t('column.url'),
    key: 'Url',
    width: 200,
    ellipsis: true,
    render: (row: MediaInfo) => {
      return h('a', { href: 'javascript:void(0)', onClick: () => preview(row) }, row.Url)
    }
  },
  {
    title: t('column.type'),
    key: 'Classify',
    width: 80,
    render: (row: MediaInfo) => {
      const colors: Record<string, string> = { video: 'info', audio: 'warning', image: 'success' }
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
    ellipsis: true
  },
])

// Helper
const formatSize = (bytes: number) => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

const preview = (row: MediaInfo) => {
  // Emit event to open Preview modal
  // This would typically use a modal store or event
}
</script>