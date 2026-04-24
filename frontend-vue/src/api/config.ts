import request from '@/api/request'

export interface AppConfig {
  // Notify
  feishu_webhook?: string
  dingtalk_webhook?: string
  dingtalk_secret_global?: string
  wecom_webhook?: string
  telegram_bot_token?: string
  telegram_chat_id?: string

  // API & Scan
  default_api_key?: string
  quota_budget?: number
  quota_timezone?: string
  quota_alert_thresholds?: string
  channel_meta_health_enable?: boolean
  channel_meta_health_interval_hours?: number
  channel_meta_ttl_days?: number
  notify_on_scan_error?: boolean
  scan_error_cooldown?: number
  scan_jitter?: number

  // Download
  download_path?: string
  cookies_file?: string
  sub_langs?: string
  enable_aria2?: boolean

  // AI Clip
  llm_provider?: string
  llm_api_key?: string
  llm_model?: string
  llm_base_url?: string
  llm_category?: string
  llm_min_score?: number
  clip_embed_thumbnail?: boolean
  clip_embed_subtitle?: boolean
  clip_adapt_aspect_ratio?: boolean

  // Dynamic Proxy
  dyn_proxy_enable?: boolean
  dyn_proxy_new_account?: boolean
  dyn_proxy_existing_account?: boolean
  dyn_proxy_sticky_minutes?: number
  proxy_protocol_order?: string
  risk_free_proxy_auto?: boolean
  risk_free_proxy_manual?: boolean
  risk_cookie_no_free_proxy?: boolean
  risk_auto_direct_fallback?: boolean
  risk_manual_direct_fallback?: boolean
  mask_proxy_logs?: boolean

  // Proxy Sniffer
  proxy_sniffer_enabled?: boolean
  proxy_sniffer_port?: number
  proxy_sniffer_system_proxy?: boolean
}

export interface ProxyStatus {
  running: boolean
  port?: number
  ca_cert_installed?: boolean
}

export default {
  get() {
    return request<AppConfig>({
      url: '/api/config',
      method: 'get',
    })
  },

  save(data: AppConfig) {
    return request<void>({
      url: '/api/config',
      method: 'post',
      data,
    })
  },

  // Proxy sniffer endpoints
  getProxyStatus() {
    return request<ProxyStatus>({
      url: '/api/proxy/status',
      method: 'get',
    })
  },

  enableProxy() {
    return request<void>({
      url: '/api/proxy/enable',
      method: 'post',
    })
  },

  disableProxy() {
    return request<void>({
      url: '/api/proxy/disable',
      method: 'post',
    })
  },

  installCert() {
    return request<void>({
      url: '/api/proxy/cert/install',
      method: 'post',
    })
  },

  setSystemProxy(enable: boolean) {
    return request<void>({
      url: '/api/proxy/system-proxy',
      method: 'post',
      data: { enable },
    })
  },

  // API Keys
  listApiKeys() {
    return request<{ id: number; name: string }[]>({
      url: '/api/api-keys',
      method: 'get',
    })
  },

  // Accounts for filter dropdown
  listAccounts() {
    return request<{ id: number; name: string }[]>({
      url: '/api/accounts',
      method: 'get',
    })
  },
}
