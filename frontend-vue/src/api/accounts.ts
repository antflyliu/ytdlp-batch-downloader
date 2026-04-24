import request from './request'

export default {
  list() {
    return request({ url: '/api/accounts', method: 'get' })
  },
  create(data: object) {
    return request({ url: '/api/accounts', method: 'post', data })
  },
  update(id: number, data: object) {
    return request({ url: `/api/accounts/${id}/update`, method: 'post', data })
  },
  delete(id: number) {
    return request({ url: `/api/accounts/${id}`, method: 'delete' })
  },
  scan(accountId: number, autoDownload = true) {
    return request({ url: '/api/accounts/scan', method: 'post', data: { account_id: accountId, auto_download: autoDownload } })
  },
  routingPreview(accountId: number) {
    return request({ url: '/api/routing-preview', method: 'get', params: { account_id: accountId } })
  },
  listApiKeys() {
    return request({ url: '/api/api-keys', method: 'get' })
  },
  listProxyPools() {
    return request({ url: '/api/proxy-pools', method: 'get' })
  },
  // Scheduler controls
  schedulerStart() {
    return request({ url: '/api/scheduler/start', method: 'post' })
  },
  schedulerStop() {
    return request({ url: '/api/scheduler/stop', method: 'post' })
  },
  schedulerReload() {
    return request({ url: '/api/scheduler/reload', method: 'post' })
  },
}