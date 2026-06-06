<template>
  <div class="rss-page">
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('rssPipeline.title') }}</div>
        <div class="page-desc">{{ t('rssPipeline.desc') }}</div>
      </div>
      <div class="page-actions">
        <NButton tertiary :loading="loading" @click="loadAll">{{ t('common.refresh') }}</NButton>
        <NButton tertiary @click="exportOpml">{{ t('rssPipeline.exportOpml') }}</NButton>
      </div>
    </div>

    <div class="rss-grid">
      <section class="card rss-panel rss-panel--feeds">
        <div class="card-title">{{ t('rssPipeline.feeds') }}</div>
        <NAlert v-if="feedsError" type="warning" :bordered="false">
          {{ feedsError }}
        </NAlert>
        <NForm class="rss-form" :model="feedDraft" label-placement="top">
          <NFormItem :label="t('rssPipeline.feedUrl')">
            <NInput v-model:value="feedDraft.feed_url" placeholder="https://example.com/feed.xml" />
          </NFormItem>
          <div class="rss-form-row">
            <NFormItem :label="t('rssPipeline.feedTitle')">
              <NInput v-model:value="feedDraft.title" />
            </NFormItem>
            <NFormItem :label="t('rssPipeline.category')">
              <NInput v-model:value="feedDraft.category" />
            </NFormItem>
          </div>
          <div class="rss-form-actions">
            <NButton type="primary" :loading="saving" @click="saveFeed">{{ t('rssPipeline.addFeed') }}</NButton>
            <NFormItem class="rss-interval-field" :label="t('rssPipeline.fetchIntervalMinutes')">
              <NInputNumber v-model:value="feedDraft.fetch_interval_minutes" :min="5" :max="1440" />
            </NFormItem>
          </div>
        </NForm>

        <div class="rss-list">
          <button
            type="button"
            class="rss-feed"
            :class="{ 'rss-feed--active': selectedFeedId === undefined }"
            :aria-pressed="selectedFeedId === undefined"
            @click="selectFeed(undefined)"
          >
            <span>
              <strong>{{ t('rssPipeline.allFeeds') }}</strong>
              <small>{{ t('rssPipeline.allFeedsDesc') }}</small>
            </span>
            <NTag :bordered="false">{{ feeds.length }}</NTag>
          </button>
          <button
            v-for="feed in feeds"
            :key="feed.id"
            type="button"
            class="rss-feed"
            :class="{ 'rss-feed--active': selectedFeedId === feed.id }"
            :aria-pressed="selectedFeedId === feed.id"
            @click="selectFeed(feed.id)"
          >
            <span>
              <strong>{{ feed.title }}</strong>
              <small>{{ feed.category || t('rssPipeline.uncategorized') }}</small>
            </span>
            <NTag :type="feed.last_fetch_status === 'error' ? 'error' : feed.last_fetch_status === 'ok' ? 'success' : 'default'" :bordered="false">
              {{ statusLabel(feed.last_fetch_status) }}
            </NTag>
          </button>
        </div>
      </section>

      <section class="card rss-panel rss-panel--items">
        <div class="rss-toolbar">
          <div class="card-title">{{ t('rssPipeline.items') }}</div>
          <div class="rss-toolbar-actions">
            <NButton tertiary :disabled="!selectedFeedId" :loading="refreshingFeed" @click="refreshSelected">
              {{ t('rssPipeline.refreshFeed') }}
            </NButton>
            <NPopconfirm
              :positive-text="t('common.delete')"
              :negative-text="t('common.cancel')"
              @positive-click="deleteSelected"
            >
              <template #trigger>
                <NButton tertiary :disabled="!selectedFeedId" :loading="deletingFeed">
                  {{ t('common.delete') }}
                </NButton>
              </template>
              {{ t('rssPipeline.deleteConfirm') }}
            </NPopconfirm>
          </div>
        </div>

        <NAlert v-if="itemsError" type="warning" :bordered="false">
          {{ itemsError }}
        </NAlert>
        <div v-if="!items.length" class="rss-empty">{{ t('rssPipeline.emptyItems') }}</div>
        <div v-else class="rss-items">
          <article v-for="item in items" :key="item.id" class="rss-item">
            <div class="rss-item__main">
              <div class="rss-item__title">{{ item.title }}</div>
              <div class="rss-item__meta">
                <span>{{ item.feed_title }}</span>
                <span v-if="item.published_at">{{ formatDate(item.published_at) }}</span>
              </div>
              <p>{{ item.summary }}</p>
              <div v-if="expandedItemId === item.id" class="rss-item__preview">
                {{ previewText(item) }}
              </div>
            </div>
            <div class="rss-item__actions">
              <NButton size="small" tertiary @click="toggleItemPreview(item.id)">
                {{ expandedItemId === item.id ? t('rssPipeline.collapsePreview') : t('rssPipeline.expandPreview') }}
              </NButton>
              <NButton size="small" tertiary :disabled="!item.link" @click="openLink(item.link)">
                {{ t('rssPipeline.openOriginal') }}
              </NButton>
              <NButton size="small" type="primary" :loading="generatingId === item.id" @click="generateArticle(item)">
                {{ item.article_task_id ? t('rssPipeline.generated') : t('rssPipeline.generateArticle') }}
              </NButton>
            </div>
          </article>
          <div class="rss-pagination">
            <NButton tertiary :disabled="!hasMoreItems" :loading="loadingMore" @click="loadMoreItems">
              {{ hasMoreItems ? t('rssPipeline.loadMore') : t('rssPipeline.noMoreItems') }}
            </NButton>
          </div>
        </div>
      </section>
    </div>

    <section class="card rss-panel">
      <div class="card-title">{{ t('rssPipeline.importOpml') }}</div>
      <NInput v-model:value="opmlText" type="textarea" :rows="5" placeholder="<opml version=&quot;2.0&quot;>..." />
      <div class="rss-form-actions">
        <NButton type="primary" :loading="importing" @click="importOpml">{{ t('rssPipeline.importOpml') }}</NButton>
      </div>
      <NInput v-if="exportedOpml" v-model:value="exportedOpml" type="textarea" :rows="5" readonly />
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'
import {
  deleteRssFeed,
  exportRssOpml,
  generateRssArticle,
  importRssOpml,
  listRssFeeds,
  listRssItems,
  refreshRssFeed,
  saveRssFeed,
  type RssFeed,
  type RssItem,
} from '@/api/rss'

const { t } = useI18n()
const message = useMessage()

const feeds = ref<RssFeed[]>([])
const items = ref<RssItem[]>([])
const selectedFeedId = ref<number | undefined>()
const loading = ref(false)
const saving = ref(false)
const refreshingFeed = ref(false)
const importing = ref(false)
const deletingFeed = ref(false)
const loadingMore = ref(false)
const generatingId = ref<number | null>(null)
const expandedItemId = ref<number | null>(null)
const feedsError = ref('')
const itemsError = ref('')
const pageSize = 40
const itemOffset = ref(0)
const hasMoreItems = ref(false)
const opmlText = ref('')
const exportedOpml = ref('')

const feedDraft = reactive({
  title: '',
  feed_url: '',
  category: '',
  fetch_interval_minutes: 60,
})

const loadFeeds = async () => {
  try {
    feedsError.value = ''
    const { data } = await listRssFeeds()
    feeds.value = data.feeds || []
  } catch (error: any) {
    feedsError.value = error?.response?.data?.error || t('rssPipeline.loadFeedsFailed')
  }
}

const loadItems = async (options: { append?: boolean } = {}) => {
  try {
    itemsError.value = ''
    const offset = options.append ? itemOffset.value : 0
    const { data } = await listRssItems({ feed_id: selectedFeedId.value, limit: pageSize, offset })
    const nextItems = data.items || []
    items.value = options.append ? [...items.value, ...nextItems] : nextItems
    itemOffset.value = offset + nextItems.length
    hasMoreItems.value = nextItems.length === pageSize
  } catch (error: any) {
    itemsError.value = error?.response?.data?.error || t('rssPipeline.loadItemsFailed')
    if (!options.append) {
      items.value = []
      hasMoreItems.value = false
      itemOffset.value = 0
    }
  }
}

const loadAll = async () => {
  loading.value = true
  try {
    await loadFeeds()
    await loadItems()
  } finally {
    loading.value = false
  }
}

const selectFeed = async (feedId?: number) => {
  selectedFeedId.value = feedId
  expandedItemId.value = null
  await loadItems()
}

const saveFeed = async () => {
  if (!feedDraft.feed_url.trim()) {
    message.error(t('rssPipeline.feedUrlRequired'))
    return
  }
  saving.value = true
  try {
    await saveRssFeed({ ...feedDraft })
    feedDraft.title = ''
    feedDraft.feed_url = ''
    feedDraft.category = ''
    await loadAll()
    message.success(t('rssPipeline.feedSaved'))
  } catch (error: any) {
    message.error(error?.response?.data?.error || t('rssPipeline.feedSaveFailed'))
  } finally {
    saving.value = false
  }
}

const refreshSelected = async () => {
  if (!selectedFeedId.value) return
  refreshingFeed.value = true
  try {
    const { data } = await refreshRssFeed(selectedFeedId.value)
    await loadAll()
    message.success(t('rssPipeline.refreshDone', { count: data.stored }))
  } catch (error: any) {
    message.error(error?.response?.data?.error || t('rssPipeline.refreshFailed'))
  } finally {
    refreshingFeed.value = false
  }
}

const deleteSelected = async () => {
  if (!selectedFeedId.value) return
  deletingFeed.value = true
  try {
    await deleteRssFeed(selectedFeedId.value)
    selectedFeedId.value = undefined
    expandedItemId.value = null
    await loadAll()
    message.success(t('rssPipeline.feedDeleted'))
  } catch (error: any) {
    message.error(error?.response?.data?.error || t('rssPipeline.feedDeleteFailed'))
  } finally {
    deletingFeed.value = false
  }
}

const loadMoreItems = async () => {
  if (!hasMoreItems.value) return
  loadingMore.value = true
  try {
    await loadItems({ append: true })
  } finally {
    loadingMore.value = false
  }
}

const toggleItemPreview = (itemId: number) => {
  expandedItemId.value = expandedItemId.value === itemId ? null : itemId
}

const generateArticle = async (item: RssItem) => {
  generatingId.value = item.id
  try {
    const { data } = await generateRssArticle(item.id)
    await loadItems()
    message.success(t('rssPipeline.articleTaskCreated', { taskId: data.task_id }))
  } catch (error: any) {
    message.error(error?.response?.data?.error || t('rssPipeline.articleTaskFailed'))
  } finally {
    generatingId.value = null
  }
}

const importOpml = async () => {
  if (!opmlText.value.trim()) return
  importing.value = true
  try {
    const { data } = await importRssOpml(opmlText.value)
    await loadAll()
    message.success(t('rssPipeline.importDone', { count: data.imported }))
  } catch (error: any) {
    message.error(error?.response?.data?.error || t('rssPipeline.importFailed'))
  } finally {
    importing.value = false
  }
}

const exportOpml = async () => {
  try {
    const { data } = await exportRssOpml()
    exportedOpml.value = data.opml
  } catch (error: any) {
    message.error(error?.response?.data?.error || t('rssPipeline.exportFailed'))
  }
}

const openLink = (link?: string) => {
  if (!link) return
  window.open(link, '_blank', 'noopener,noreferrer')
}

const formatDate = (value: string) => {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

const statusLabel = (status?: string | null) => {
  if (status === 'ok') return t('rssPipeline.statusOk')
  if (status === 'error') return t('rssPipeline.statusError')
  return t('rssPipeline.statusNew')
}

const stripHtml = (value?: string) => {
  const text = value || ''
  if (!text) return ''
  const doc = new DOMParser().parseFromString(text, 'text/html')
  return (doc.body.textContent || '').replace(/\s+/g, ' ').trim()
}

const previewText = (item: RssItem) => {
  return stripHtml(item.content_html) || item.summary || t('rssPipeline.noSummary')
}

onMounted(loadAll)
</script>

<style scoped>
.rss-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
}

.page-header,
.rss-toolbar,
.rss-form-actions,
.rss-item__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
}

.page-desc,
.rss-item__meta,
.rss-feed small {
  color: var(--text-muted);
}

.page-actions,
.rss-toolbar-actions {
  display: flex;
  gap: 8px;
}

.rss-grid {
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.card {
  border: 1px solid var(--border-cream);
  border-radius: 8px;
  background: var(--surface);
  padding: 16px;
}

.card-title {
  font-size: 15px;
  font-weight: 700;
}

.rss-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.rss-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.rss-interval-field {
  margin-bottom: 0;
  min-width: 150px;
}

.rss-list,
.rss-items {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rss-feed {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  padding: 10px;
  text-align: left;
  cursor: pointer;
}

.rss-feed:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.rss-feed span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.rss-feed strong,
.rss-item__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rss-feed--active {
  border-color: var(--accent);
  background: var(--accent-dim);
}

.rss-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}

.rss-item__main {
  min-width: 0;
}

.rss-item__title {
  font-weight: 700;
}

.rss-item__meta {
  display: flex;
  gap: 10px;
  margin-top: 4px;
  font-size: 12px;
}

.rss-item p {
  display: -webkit-box;
  margin: 8px 0 0;
  overflow: hidden;
  color: var(--text-muted);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.rss-item__preview {
  margin-top: 10px;
  border: 1px solid var(--border-medium);
  border-radius: 8px;
  background: var(--surface2);
  color: var(--text-muted);
  line-height: 1.55;
  max-height: 180px;
  overflow: auto;
  padding: 10px;
  white-space: pre-wrap;
}

.rss-item__actions {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.rss-pagination {
  display: flex;
  justify-content: center;
  padding-top: 4px;
}

.rss-empty {
  border: 1px dashed var(--border-medium);
  border-radius: 8px;
  color: var(--text-muted);
  padding: 28px;
  text-align: center;
}

@media (max-width: 900px) {
  .rss-grid,
  .rss-item {
    grid-template-columns: 1fr;
  }

  .page-header,
  .rss-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
