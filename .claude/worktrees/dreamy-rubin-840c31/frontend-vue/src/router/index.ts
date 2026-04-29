import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  // Dashboard — default home
  {
    path: '/',
    name: 'dashboard',
    meta: { keepAlive: true },
    component: () => import('@/views/Dashboard.vue'),
  },
  // Resource sniffer — migrated from /index
  {
    path: '/resources',
    name: 'resources',
    meta: { keepAlive: true },
    component: () => import('@/views/ResourceIndex.vue'),
  },
  // Other nav pages (placeholder stubs)
  {
    path: '/accounts',
    name: 'accounts',
    meta: { keepAlive: false },
    component: () => import('@/views/Accounts.vue'),
  },
  // Batch download
  {
    path: '/batch-download',
    name: 'batchDownload',
    meta: { keepAlive: false },
    component: () => import('@/views/BatchDownload.vue'),
  },
  {
    path: '/api-keys',
    name: 'apiKeys',
    meta: { keepAlive: false },
    component: () => import('@/views/ApiKeys.vue'),
  },
  {
    path: '/proxy-pools',
    name: 'proxyPools',
    meta: { keepAlive: false },
    component: () => import('@/views/ProxyPools.vue'),
  },
  {
    path: '/dynamic-providers',
    name: 'dynamicProviders',
    meta: { keepAlive: false },
    component: () => import('@/views/DynamicProviders.vue'),
  },
  {
    path: '/clip-history',
    name: 'clipHistory',
    meta: { keepAlive: false },
    component: () => import('@/views/ClipHistory.vue'),
  },
  // Settings hub — parent container
  {
    path: '/settings-hub',
    name: 'settingsHub',
    meta: { keepAlive: false },
    component: () => import('@/components/layout/PageContent.vue'),
    redirect: '/settings-hub/notify',
    children: [
      {
        path: '/settings-hub',
        redirect: '/settings-hub/notify',
      },
      {
        path: '/settings-hub/notify',
        name: 'settingsNotify',
        meta: { keepAlive: false },
        component: () => import('@/views/settings/NotifySettings.vue'),
      },
      {
        path: '/settings-hub/api',
        name: 'settingsApi',
        meta: { keepAlive: false },
        component: () => import('@/views/settings/ApiSettings.vue'),
      },
      {
        path: '/settings-hub/download',
        name: 'settingsDownload',
        meta: { keepAlive: false },
        component: () => import('@/views/settings/DownloadSettings.vue'),
      },
      {
        path: '/settings-hub/ai',
        name: 'settingsAi',
        meta: { keepAlive: false },
        component: () => import('@/views/settings/AiSettings.vue'),
      },
      {
        path: '/settings-hub/dynamic',
        name: 'settingsDynamic',
        meta: { keepAlive: false },
        component: () => import('@/views/settings/DynamicProxySettings.vue'),
      },
      {
        path: '/settings-hub/proxy',
        name: 'settingsProxy',
        meta: { keepAlive: false },
        component: () => import('@/views/settings/ProxySnifferSettings.vue'),
      },
    ],
  },
  // Legacy redirect: /index -> /resources
  {
    path: '/index',
    redirect: '/resources',
  },
  // Legacy /setting -> settings-hub
  {
    path: '/setting',
    redirect: '/settings-hub',
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
