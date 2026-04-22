import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface MediaInfo {
  Id: string
  Url: string
  UrlSign: string
  CoverUrl?: string
  Size: number
  Domain: string
  Classify: string  // video/audio/image
  Suffix: string
  SavePath?: string
  Status: string
  DecodeKey?: string
  Description?: string
  ContentType?: string
  OtherData?: Record<string, string>
}

export const useResourceStore = defineStore('resource', () => {
  const resources = ref<MediaInfo[]>([])
  const downloadQueue = ref<MediaInfo[]>([])
  const isLoading = ref(false)
  const filter = ref<'all' | 'video' | 'audio' | 'image'>('all')

  const filteredResources = computed(() => {
    if (filter.value === 'all') return resources.value
    return resources.value.filter(r => r.Classify === filter.value)
  })

  const addResources = (newItems: MediaInfo[]) => {
    // Avoid duplicates by UrlSign
    const existingSigns = new Set(resources.value.map(r => r.UrlSign))
    const unique = newItems.filter(item => !existingSigns.has(item.UrlSign))
    resources.value.push(...unique)
    // Cap at 2000 to prevent reactive degradation
    if (resources.value.length > 2000) {
      resources.value.splice(0, resources.value.length - 2000)
    }
    saveToStorage()
  }

  const removeResource = (urlSign: string) => {
    resources.value = resources.value.filter(r => r.UrlSign !== urlSign)
    saveToStorage()
  }

  const setFilter = (f: typeof filter.value) => {
    filter.value = f
  }

  // Download queue operations
  const enqueueDownload = (item: MediaInfo) => {
    downloadQueue.value.push(item)
    saveQueueToStorage()
  }

  const dequeueDownload = () => {
    const item = downloadQueue.value.shift()
    saveQueueToStorage()
    return item
  }

  const removeFromQueue = (urlSign: string) => {
    downloadQueue.value = downloadQueue.value.filter(i => i.UrlSign !== urlSign)
    saveQueueToStorage()
  }

  // localStorage persistence
  const STORAGE_KEY = 'resources_v1'
  const QUEUE_KEY = 'download_queue_v1'

  const saveToStorage = () => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(resources.value))
    } catch (e) {
      console.error('[resourceStore] Failed to save to localStorage:', e)
    }
  }

  const loadFromStorage = () => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        resources.value = JSON.parse(stored)
      }
    } catch (e) {
      console.error('[resourceStore] Failed to load from localStorage:', e)
      resources.value = []
    }
  }

  const saveQueueToStorage = () => {
    try {
      localStorage.setItem(QUEUE_KEY, JSON.stringify(downloadQueue.value))
    } catch (e) {
      console.error('[resourceStore] Failed to save queue to localStorage:', e)
    }
  }

  const loadQueueFromStorage = () => {
    try {
      const stored = localStorage.getItem(QUEUE_KEY)
      if (stored) {
        downloadQueue.value = JSON.parse(stored)
      }
    } catch (e) {
      console.error('[resourceStore] Failed to load queue from localStorage:', e)
      downloadQueue.value = []
    }
  }

  // Auto-load from localStorage on store creation
  loadFromStorage()
  loadQueueFromStorage()

  return {
    resources, downloadQueue, isLoading, filter,
    filteredResources, addResources, removeResource, setFilter,
    enqueueDownload, dequeueDownload, removeFromQueue,
    saveToStorage, loadFromStorage, loadQueueFromStorage
  }
})