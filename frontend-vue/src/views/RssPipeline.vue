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

    <div class="rss-workbench">
      <aside class="rss-sidebar-stack">
        <NCard class="rss-card rss-feeds-card" :title="t('rssPipeline.feeds')">
          <template #header-extra>
            <NTag size="small" :bordered="false">{{ feeds.length }}</NTag>
          </template>

          <div class="rss-panel">
            <NAlert v-if="feedsError" type="warning" :bordered="false">
              {{ feedsError }}
            </NAlert>
            <NForm class="rss-form" :model="feedDraft" label-placement="top">
              <NFormItem :label="t('rssPipeline.feedUrl')">
                <NInput v-model:value="feedDraft.feed_url" placeholder="https://example.com/feed.xml" clearable />
              </NFormItem>
              <div class="rss-form-row">
                <NFormItem :label="t('rssPipeline.feedTitle')">
                  <NInput v-model:value="feedDraft.title" clearable />
                </NFormItem>
                <NFormItem :label="t('rssPipeline.category')">
                  <NInput v-model:value="feedDraft.category" clearable />
                </NFormItem>
              </div>
              <div class="rss-form-actions">
                <NButton type="primary" :loading="saving" @click="saveFeed">{{ t('rssPipeline.addFeed') }}</NButton>
                <NFormItem class="rss-interval-field" :label="t('rssPipeline.fetchIntervalMinutes')">
                  <NInputNumber v-model:value="feedDraft.fetch_interval_minutes" :min="5" :max="1440" />
                </NFormItem>
              </div>
            </NForm>

            <div class="rss-list-frame">
              <div class="rss-list">
                <button
                  type="button"
                  class="rss-feed"
                  :class="{ 'rss-feed--active': selectedFeedId === undefined }"
                  :aria-pressed="selectedFeedId === undefined"
                  @click="selectFeed(undefined)"
                >
                  <span class="rss-feed__body">
                    <strong>{{ t('rssPipeline.allFeeds') }}</strong>
                    <small>{{ t('rssPipeline.allFeedsDesc') }}</small>
                  </span>
                  <NTag class="rss-feed__tag" :bordered="false">{{ feeds.length }}</NTag>
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
                  <span class="rss-feed__body">
                    <strong>{{ feed.title }}</strong>
                    <small>{{ feed.category || t('rssPipeline.uncategorized') }}</small>
                  </span>
                  <NTag class="rss-feed__tag" :type="feed.last_fetch_status === 'error' ? 'error' : feed.last_fetch_status === 'ok' ? 'success' : 'default'" :bordered="false">
                    {{ statusLabel(feed.last_fetch_status) }}
                  </NTag>
                </button>
              </div>
            </div>
          </div>
        </NCard>

        <NCard class="rss-card rss-catalog-card" :title="t('rssPipeline.catalogTitle')">
          <template #header-extra>
            <NButton text size="small" :loading="catalogSyncing" @click="syncCatalog">
              {{ t('rssPipeline.catalogSync') }}
            </NButton>
          </template>

          <div class="rss-catalog-stack">
            <NAlert v-if="catalogError" type="warning" :bordered="false">
              {{ catalogError }}
            </NAlert>

            <div class="rss-catalog-stats">
              <NTag size="small" :bordered="false">{{ t('rssPipeline.catalogFeeds', { count: catalogSummary?.feed_count || 0 }) }}</NTag>
              <NTag size="small" :bordered="false" type="success">{{ t('rssPipeline.catalogValid', { count: catalogSummary?.valid_count || 0 }) }}</NTag>
              <NTag size="small" :bordered="false">{{ t('rssPipeline.catalogRoutes', { count: catalogSummary?.route_count || 0 }) }}</NTag>
            </div>

            <div class="rss-catalog-controls">
              <NInput v-model:value="catalogSearch" :placeholder="t('rssPipeline.catalogSearch')" clearable />
              <NSelect v-model:value="catalogCategory" :options="catalogCategoryOptions" size="small" />
              <NInput v-model:value="rsshubBase" :placeholder="t('rssPipeline.rsshubBase')" clearable />
            </div>

            <div class="rss-catalog-actions">
              <NButton
                type="primary"
                size="small"
                :disabled="!selectedCatalogIds.length"
                :loading="catalogImporting"
                @click="importSelectedCatalog"
              >
                {{ t('rssPipeline.catalogImportSelected', { count: selectedCatalogIds.length }) }}
              </NButton>
              <span>{{ catalogSourceLabel }}</span>
            </div>

            <div class="rss-catalog-list-frame">
              <NEmpty v-if="!catalogLoading && !filteredCatalogEntries.length" :description="t('rssPipeline.catalogEmpty')" />
              <div v-else class="rss-catalog-list">
                <button
                  v-for="entry in filteredCatalogEntries"
                  :key="entry.id"
                  type="button"
                  class="rss-catalog-entry"
                  :class="{ 'rss-catalog-entry--imported': entry.imported }"
                  @click="applyCatalogEntry(entry)"
                >
                  <span class="rss-catalog-entry__check" @click.stop>
                    <NCheckbox
                      v-if="entry.entry_type === 'feed'"
                      :checked="selectedCatalogIds.includes(entry.id)"
                      :disabled="entry.imported"
                      @update:checked="(checked) => toggleCatalogEntry(entry.id, checked)"
                    />
                    <span v-else class="rss-catalog-entry__route">R</span>
                  </span>
                  <span class="rss-catalog-entry__body">
                    <strong>{{ entry.title }}</strong>
                    <small>{{ entry.entry_type === 'feed' ? entry.feed_url : entry.route_template }}</small>
                  </span>
                  <NTag
                    class="rss-catalog-entry__tag"
                    size="small"
                    :type="catalogEntryTagType(entry)"
                    :bordered="false"
                  >
                    {{ catalogStatusLabel(entry) }}
                  </NTag>
                </button>
              </div>
            </div>
          </div>
        </NCard>

        <NCard class="rss-card rss-opml-card" :title="t('rssPipeline.importOpml')">
          <template #header-extra>
            <NButton text size="small" @click="exportOpml">{{ t('rssPipeline.exportOpml') }}</NButton>
          </template>

          <div class="rss-opml-stack">
            <NInput v-model:value="opmlText" type="textarea" :rows="5" placeholder="<opml version=&quot;2.0&quot;>..." />
            <div class="rss-form-actions rss-form-actions--end">
              <NButton type="primary" :loading="importing" @click="importOpml">{{ t('rssPipeline.importOpml') }}</NButton>
            </div>
            <NInput v-if="exportedOpml" v-model:value="exportedOpml" type="textarea" :rows="5" readonly />
          </div>
        </NCard>
      </aside>

      <NCard class="rss-card rss-items-card" :title="t('rssPipeline.items')">
        <template #header-extra>
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
        </template>

        <div class="rss-items-panel">
          <NAlert v-if="itemsError" type="warning" :bordered="false">
            {{ itemsError }}
          </NAlert>
          <div v-if="!items.length" class="rss-empty">
            <NEmpty :description="t('rssPipeline.emptyItems')" />
          </div>
          <div v-else class="rss-items-frame">
            <div class="rss-items">
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
          </div>
        </div>
      </NCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NTag,
  useMessage,
} from 'naive-ui'
import {
  deleteRssFeed,
  exportRssOpml,
  generateRssArticle,
  importRssCatalogEntries,
  importRssOpml,
  listRssCatalog,
  listRssFeeds,
  listRssItems,
  refreshRssFeed,
  saveRssFeed,
  syncRssCatalog,
  type RssCatalogEntry,
  type RssCatalogSummary,
  type RssFeed,
  type RssItem,
} from '@/api/rss'

const { t } = useI18n()
const message = useMessage()

const feeds = ref<RssFeed[]>([])
const items = ref<RssItem[]>([])
const catalogEntries = ref<RssCatalogEntry[]>([])
const catalogSummary = ref<RssCatalogSummary | null>(null)
const selectedCatalogIds = ref<number[]>([])
const selectedFeedId = ref<number | undefined>()
const loading = ref(false)
const saving = ref(false)
const refreshingFeed = ref(false)
const importing = ref(false)
const catalogLoading = ref(false)
const catalogSyncing = ref(false)
const catalogImporting = ref(false)
const deletingFeed = ref(false)
const loadingMore = ref(false)
const generatingId = ref<number | null>(null)
const expandedItemId = ref<number | null>(null)
const feedsError = ref('')
const itemsError = ref('')
const catalogError = ref('')
const pageSize = 40
const itemOffset = ref(0)
const hasMoreItems = ref(false)
const opmlText = ref('')
const exportedOpml = ref('')
const catalogSearch = ref('')
const catalogCategory = ref('__all__')
const rsshubBase = ref('https://rsshub.app')

const feedDraft = reactive({
  title: '',
  feed_url: '',
  category: '',
  fetch_interval_minutes: 60,
})

const catalogCategoryOptions = computed(() => [
  { label: t('rssPipeline.catalogAllCategories'), value: '__all__' },
  ...((catalogSummary.value?.categories || []) as string[]).map((category) => ({ label: category, value: category })),
])

const filteredCatalogEntries = computed(() => {
  const query = catalogSearch.value.trim().toLocaleLowerCase()
  return catalogEntries.value.filter((entry) => {
    if (catalogCategory.value !== '__all__' && entry.category !== catalogCategory.value) return false
    if (!query) return true
    return [entry.title, entry.category, entry.feed_url, entry.route_template, entry.description]
      .filter(Boolean)
      .some((value) => String(value).toLocaleLowerCase().includes(query))
  })
})

const catalogSourceLabel = computed(() => {
  const source = catalogSummary.value?.source
  if (!source?.last_synced_at) return t('rssPipeline.catalogNotSynced')
  return t('rssPipeline.catalogSyncedAt', { time: formatDate(source.last_synced_at) })
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

const loadCatalog = async () => {
  catalogLoading.value = true
  try {
    catalogError.value = ''
    const { data } = await listRssCatalog({ available: false })
    catalogEntries.value = data.entries || []
    catalogSummary.value = data.summary || null
    const importedIds = new Set(catalogEntries.value.filter((entry) => entry.imported).map((entry) => entry.id))
    selectedCatalogIds.value = selectedCatalogIds.value.filter((id) => !importedIds.has(id))
  } catch (error: any) {
    catalogError.value = error?.response?.data?.error || t('rssPipeline.catalogLoadFailed')
  } finally {
    catalogLoading.value = false
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
    await loadCatalog()
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

const syncCatalog = async () => {
  catalogSyncing.value = true
  try {
    catalogError.value = ''
    const { data } = await syncRssCatalog()
    catalogSummary.value = data.summary || null
    await loadCatalog()
    message.success(t('rssPipeline.catalogSyncDone', { count: catalogSummary.value?.total || 0 }))
  } catch (error: any) {
    const errorText = error?.response?.data?.error || t('rssPipeline.catalogSyncFailed')
    catalogError.value = errorText
    message.error(errorText)
  } finally {
    catalogSyncing.value = false
  }
}

const toggleCatalogEntry = (entryId: number, checked: boolean) => {
  const next = new Set(selectedCatalogIds.value)
  if (checked) {
    next.add(entryId)
  } else {
    next.delete(entryId)
  }
  selectedCatalogIds.value = Array.from(next)
}

const importSelectedCatalog = async () => {
  if (!selectedCatalogIds.value.length) return
  catalogImporting.value = true
  try {
    const { data } = await importRssCatalogEntries(selectedCatalogIds.value, feedDraft.fetch_interval_minutes)
    selectedCatalogIds.value = []
    await loadFeeds()
    await loadCatalog()
    message.success(t('rssPipeline.catalogImportDone', { count: data.imported }))
  } catch (error: any) {
    message.error(error?.response?.data?.error || t('rssPipeline.catalogImportFailed'))
  } finally {
    catalogImporting.value = false
  }
}

const applyCatalogEntry = (entry: RssCatalogEntry) => {
  if (entry.entry_type === 'feed') {
    if (!entry.feed_url) return
    feedDraft.feed_url = entry.feed_url
    feedDraft.title = entry.title
    feedDraft.category = entry.category || ''
    return
  }
  if (!entry.route_template) return
  feedDraft.feed_url = `${rsshubBase.value.replace(/\/+$/, '')}${entry.route_template}`
  feedDraft.title = entry.title
  feedDraft.category = entry.category || ''
  message.info(t('rssPipeline.routeTemplateApplied'))
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

const catalogStatusLabel = (entry: RssCatalogEntry) => {
  if (entry.imported) return t('rssPipeline.catalogImported')
  if (entry.entry_type === 'rsshub_route') return t('rssPipeline.catalogTemplate')
  if (entry.status_limited) return t('rssPipeline.catalogLimited')
  if (entry.status_valid === true) return t('rssPipeline.catalogAvailable')
  if (entry.status_valid === false) return t('rssPipeline.catalogUnavailable')
  return t('rssPipeline.statusNew')
}

const catalogEntryTagType = (entry: RssCatalogEntry) => {
  if (entry.imported) return 'success'
  if (entry.status_limited) return 'warning'
  if (entry.status_valid === false) return 'error'
  return entry.entry_type === 'rsshub_route' ? 'default' : 'success'
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
  max-width: 100%;
  min-width: 0;
  overflow-x: hidden;
}

.page-header,
.rss-form-actions,
.rss-item__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.page-title {
  color: var(--text);
  font-family: var(--font);
  font-size: 32px;
  font-weight: 500;
  line-height: 1.15;
}

.page-desc,
.rss-item__meta,
.rss-feed small,
.rss-catalog-entry small,
.rss-catalog-actions span {
  color: var(--text-muted);
}

.page-actions,
.rss-toolbar-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  max-width: 100%;
  min-width: 0;
}

.rss-workbench {
  display: grid;
  grid-template-columns: minmax(340px, 0.72fr) minmax(0, 1.28fr);
  gap: 16px;
  align-items: stretch;
  max-width: 100%;
  min-width: 0;
}

.rss-sidebar-stack {
  display: flex;
  max-width: 100%;
  min-width: 0;
  flex-direction: column;
  gap: 16px;
}

.rss-card {
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
  border-radius: 20px;
  box-shadow: var(--shadow-whisper);
}

.rss-card :deep(.n-card-header) {
  align-items: center;
  min-height: 64px;
  min-width: 0;
}

.rss-card :deep(.n-card-header__main) {
  color: var(--text);
  font-size: 16px;
  font-weight: 700;
  min-width: 0;
}

.rss-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 100%;
  min-height: 0;
  min-width: 0;
}

.rss-items-card {
  min-height: clamp(620px, 74vh, 820px);
}

.rss-items-card :deep(.n-card__content) {
  height: calc(clamp(620px, 74vh, 820px) - 64px);
  display: flex;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
}

.rss-feeds-card :deep(.n-card__content),
.rss-catalog-card :deep(.n-card__content),
.rss-opml-card :deep(.n-card__content) {
  display: flex;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
}

.rss-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  min-width: 0;
}

.rss-interval-field {
  margin-bottom: 0;
  min-width: 150px;
}

.rss-interval-field :deep(.n-input-number) {
  width: 100%;
}

.rss-page :deep(.n-form),
.rss-page :deep(.n-form-item),
.rss-page :deep(.n-input),
.rss-page :deep(.n-input-number),
.rss-page :deep(.n-select),
.rss-page :deep(.n-button) {
  max-width: 100%;
  min-width: 0;
}

.rss-form-actions--end {
  justify-content: flex-end;
}

.rss-list-frame {
  max-height: clamp(260px, 35vh, 420px);
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.rss-catalog-list-frame {
  max-height: clamp(260px, 32vh, 390px);
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.rss-list,
.rss-items,
.rss-catalog-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 100%;
  min-width: 0;
}

.rss-items-panel,
.rss-opml-stack,
.rss-catalog-stack {
  display: flex;
  max-width: 100%;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
}

.rss-items-panel {
  height: 100%;
}

.rss-items-frame {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 6px;
  scrollbar-gutter: stable;
}

.rss-feed {
  display: flex;
  min-height: 70px;
  width: 100%;
  box-sizing: border-box;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 253, 248, 0.96) 0%, rgba(250, 249, 245, 0.98) 100%);
  color: inherit;
  padding: 14px;
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.rss-catalog-stats,
.rss-catalog-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.rss-catalog-controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(150px, 0.7fr);
  gap: 8px;
  min-width: 0;
}

.rss-catalog-controls :deep(.n-input):last-child {
  grid-column: 1 / -1;
}

.rss-catalog-entry {
  display: grid;
  width: 100%;
  box-sizing: border-box;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 253, 248, 0.96) 0%, rgba(250, 249, 245, 0.98) 100%);
  color: inherit;
  padding: 12px;
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.rss-catalog-entry:hover {
  border-color: rgba(201, 100, 66, 0.36);
  background: rgba(201, 100, 66, 0.07);
  box-shadow: var(--shadow-whisper);
  transform: translateY(-1px);
}

.rss-catalog-entry:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.rss-catalog-entry--imported {
  border-color: rgba(84, 150, 96, 0.32);
}

.rss-catalog-entry__body {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.rss-catalog-entry__body strong,
.rss-catalog-entry__body small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rss-catalog-entry__check {
  display: flex;
  align-items: center;
  justify-content: center;
}

.rss-catalog-entry__route {
  display: inline-flex;
  width: 22px;
  height: 22px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(201, 100, 66, 0.12);
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
}

.rss-catalog-entry__tag {
  flex: 0 0 auto;
  max-width: 100%;
}

.rss-feed:hover {
  border-color: rgba(201, 100, 66, 0.36);
  background: rgba(201, 100, 66, 0.07);
  box-shadow: var(--shadow-whisper);
  transform: translateY(-1px);
}

.rss-feed:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.rss-feed__body {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.rss-feed__tag {
  flex: 0 0 auto;
  max-width: 100%;
}

.rss-feed strong,
.rss-item__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rss-feed--active {
  border-color: rgba(201, 100, 66, 0.48);
  background: rgba(201, 100, 66, 0.07);
  box-shadow: 0 0 0 1px rgba(201, 100, 66, 0.16);
}

.rss-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(216px, auto);
  gap: 16px;
  box-sizing: border-box;
  align-items: start;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 253, 248, 0.96) 0%, rgba(250, 249, 245, 0.98) 100%);
  padding: 16px;
}

.rss-item__main {
  min-width: 0;
}

.rss-item__title {
  color: var(--text);
  font-size: 16px;
  font-weight: 700;
  line-height: 1.35;
}

.rss-item__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 4px;
  font-size: 12px;
}

.rss-item p {
  display: -webkit-box;
  margin: 8px 0 0;
  overflow: hidden;
  color: var(--text-muted);
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.rss-item__preview {
  margin-top: 10px;
  border: 1px solid var(--border-medium);
  border-radius: 12px;
  background: var(--surface2);
  color: var(--text-muted);
  line-height: 1.55;
  max-height: 180px;
  overflow: auto;
  padding: 10px;
  white-space: pre-wrap;
}

.rss-item__actions {
  align-self: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  min-width: 216px;
}

.rss-pagination {
  display: flex;
  justify-content: center;
  padding-top: 4px;
}

.rss-empty {
  display: flex;
  min-height: 320px;
  flex: 1 1 auto;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--border-medium);
  border-radius: 16px;
  background: rgba(255, 253, 248, 0.72);
  color: var(--text-muted);
  padding: 28px;
  text-align: center;
}

@media (max-width: 1180px) {
  .rss-item {
    grid-template-columns: 1fr;
  }

  .rss-item__actions {
    min-width: 0;
    justify-content: flex-start;
  }
}

@media (max-width: 960px) {
  .rss-workbench {
    grid-template-columns: 1fr;
  }

  .rss-items-card {
    min-height: 560px;
  }

  .rss-items-card :deep(.n-card__content) {
    height: 496px;
  }

  .page-header,
  .rss-toolbar-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .rss-list-frame {
    max-height: 320px;
  }

  .rss-catalog-list-frame {
    max-height: 320px;
  }
}

@media (max-width: 640px) {
  .rss-page {
    gap: 12px;
  }

  .rss-card {
    border-radius: 16px;
  }

  .rss-card :deep(.n-card-header) {
    min-height: 56px;
    padding: 16px 16px 10px;
  }

  .rss-card :deep(.n-card__content) {
    padding: 0 16px 16px;
  }

  .rss-form-row,
  .rss-catalog-controls {
    grid-template-columns: 1fr;
  }

  .rss-form-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .rss-form-actions--end {
    align-items: flex-end;
  }

  .rss-interval-field {
    min-width: 0;
  }

  .page-title {
    font-size: 26px;
  }

  .rss-feed,
  .rss-catalog-entry,
  .rss-item {
    border-radius: 14px;
    padding: 12px;
  }

  .rss-feed {
    align-items: flex-start;
  }

  .rss-feed__tag {
    align-self: center;
  }

  .rss-catalog-entry {
    grid-template-columns: 28px minmax(0, 1fr);
    align-items: start;
  }

  .rss-catalog-entry__tag {
    grid-column: 2;
    justify-self: start;
  }
}
</style>
