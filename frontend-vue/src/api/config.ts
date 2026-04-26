import request from '@/api/request'

export interface AppConfig {
  // Notify (snake_case, matching backend)
  global_feishu_url?: string
  global_dingtalk_url?: string
  global_dingtalk_sign_secret?: string
  global_wecom_url?: string
  global_telegram_token?: string
  global_telegram_chat_id?: string

  // API & Scan
  default_api_key_id?: string
  quota_budget_per_day?: number
  quota_usage_timezone?: string
  quota_alert_thresholds?: string
  channel_meta_health_check_enabled?: boolean
  channel_meta_health_check_interval_hours?: number
  channel_meta_max_age_days?: number
  notify_on_scan_error?: boolean
  scan_error_notify_cooldown_seconds?: number
  scan_jitter_seconds?: number

  // Download
  download_output_path?: string
  download_cookies_file?: string
  default_sub_langs?: string
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
  clip_thumbnail_quality?: number
  auto_clip_enabled?: boolean
  auto_clip_notify_enabled?: boolean

  // Dynamic Proxy
  system_dynamic_proxy_enabled?: boolean
  apply_dynamic_proxy_to_new_accounts?: boolean
  apply_dynamic_proxy_to_existing_accounts?: boolean
  default_sticky_minutes?: number
  default_proxy_protocol_order?: string
  allow_free_proxy_for_auto_download?: boolean
  allow_free_proxy?: boolean
  allow_free_proxy_with_cookies?: boolean
  auto_direct_fallback?: boolean
  manual_direct_fallback?: boolean
  mask_proxy_in_logs?: boolean

  // Proxy Sniffer
  proxy_sniffer_enabled?: boolean
  proxy_sniffer_port?: number
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
