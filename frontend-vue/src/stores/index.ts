import { defineStore } from 'pinia'

export const useIndexStore = defineStore('index', () => {
  const baseUrl = window.$baseUrl || import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000'

  const appInfo = {
    AppName: 'ResDownloader',
    Version: import.meta.env.VITE_APP_VERSION || '1.0.0',
    Description: 'Resource downloader',
    Copyright: 'Copyright (c) ResDownloader',
  }

  return {
    appInfo,
    baseUrl,
  }
})
