<template>
  <div>
    <div class="filter-bar" style="margin-bottom: 16px; display: flex; gap: 12px;">
      <NInput
        v-model:value="keyword"
        :placeholder="t('channels.historySearch')"
        clearable
        style="max-width: 360px"
        @update:value="onSearchDebounced"
      />
    </div>

    <div v-if="items.length === 0" class="empty-state">
      <div class="empty-state__icon">
        <NIcon :size="24"><FilmOutline /></NIcon>
      </div>
      <div class="empty-state__title">{{ t('channels.historyEmpty') }}</div>
    </div>

    <div v-else class="sph-history-grid">
      <div
        v-for="item in items"
        :key="item.id"
        class="sph-history-card"
        @click="onDownload(item)"
      >
        <div
          class="sph-history-card__cover"
          :style="{ backgroundImage: item.cover_url ? `url(${item.cover_url})` : 'none' }"
        />
        <div class="sph-history-card__body">
          <div class="sph-history-card__title">{{ item.video_title || '(无标题)' }}</div>
          <div class="sph-history-card__meta">
            <span>{{ item.author_nickname || '匿名' }}</span>
            <span>·</span>
            <span>{{ formatTime(item.parsed_at) }}</span>
          </div>
          <div>
            <span v-if="item.downloaded" class="status-badge status-badge--ok">
              {{ t('channels.downloaded') }}
            </span>
            <span v-else class="status-badge">{{ t('channels.download') }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="total > limit" style="margin-top: 16px; display: flex; justify-content: center;">
      <NPagination
        v-model:page="page"
        :page-count="Math.ceil(total / limit)"
        @update:page="loadPage"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NIcon, NInput, NPagination, useMessage } from 'naive-ui'
import { FilmOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { listSphHistory, downloadFromSph, type SphHistoryItem } from '@/api/channels'

const { t } = useI18n()
const message = useMessage()
const items = ref<SphHistoryItem[]>([])
const total = ref(0)
const page = ref(1)
const limit = 20
const keyword = ref('')

let searchTimer: number | null = null

async function loadPage() {
    try {
        const r = await listSphHistory({
            limit,
            offset: (page.value - 1) * limit,
            keyword: keyword.value || undefined,
        })
        items.value = (r as any).data?.items ?? (r as any).items ?? []
        total.value = (r as any).data?.total ?? (r as any).total ?? 0
    } catch (e: any) {
        message.error(e?.response?.data?.error || e?.message || String(e))
    }
}

function onSearchDebounced() {
  if (searchTimer !== null) clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    page.value = 1
    loadPage()
  }, 300)
}

async function onDownload(item: SphHistoryItem) {
  if (item.downloaded) return
  try {
    await downloadFromSph({ history_id: item.id })
    message.success('下载任务已提交')
    await loadPage()
  } catch (e: any) {
    message.error(e?.response?.data?.error || e?.message || String(e))
  }
}

function formatTime(iso: string) {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const now = Date.now()
  const diffMin = Math.floor((now - d.getTime()) / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  if (diffMin < 1440) return `${Math.floor(diffMin / 60)}小时前`
  return d.toLocaleDateString('zh-CN')
}

onMounted(loadPage)
</script>
