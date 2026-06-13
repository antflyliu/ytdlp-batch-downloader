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
  whisper_provider?: string
  whisper_base_url?: string
  whisper_api_key?: string
  whisper_model?: string
  whisper_compute_type?: string
  whisper_device?: string
  whisper_chunk_seconds?: number
  whisper_language?: string
  article_output_dir?: string
  article_tools_path?: string
  article_default_target_lang?: string
  article_target_lang?: string
  article_subtitle_languages?: string
  article_subtitle_proxy?: string
  article_subtitle_proxy_mode?: string
  article_subtitle_proxy_pool_id?: number | null
  article_author?: string
  gmail_oauth_client_id?: string
  gmail_oauth_client_secret?: string
  gmail_oauth_redirect_uri?: string
  gmail_oauth_scopes?: string
  email_analysis_rules?: Record<string, unknown>
  article_wechat_prompt_role?: string
  article_wechat_prompt_reader_persona?: string
  article_wechat_prompt_style?: string
  article_wechat_prompt_max_chars?: number
  article_llm_optimize_model?: string
  article_llm_summary_model?: string
  article_llm_translate_model?: string
  comfyui_url?: string
  comfyui_api_key?: string
  runninghub_url?: string
  runninghub_api_key?: string
  tts_provider?: string
  local_tts_url?: string
  video_gen_output_dir?: string
  voice_provider?: string
  voice_fallback_order?: string
  voice_flow_defaults_json?: string
  voice_output_dir?: string
  voice_require_disclosure?: boolean
  voice_allow_reference_clone?: boolean
  voice_allow_prompt_transcript_clone?: boolean
  voice_max_text_chars?: number
  transcription_provider?: string
  openai_speech_base_url?: string
  openai_speech_api_key?: string
  openai_speech_model?: string
  openai_speech_voice?: string
  azure_speech_region?: string
  azure_speech_endpoint?: string
  azure_speech_api_key?: string
  azure_speech_voice?: string
  azure_speech_output_format?: string
  minimax_speech_base_url?: string
  minimax_speech_api_key?: string
  minimax_speech_model?: string
  minimax_speech_voice?: string
  voxcpm_base_url?: string
  voxcpm_api_key?: string
  voxcpm_model?: string
  voxcpm_default_voice?: string
  voxcpm_default_control_instruction?: string
  vibevoice_tts_base_url?: string
  vibevoice_tts_api_key?: string
  vibevoice_tts_model?: string
  vibevoice_tts_voice?: string
  vibevoice_asr_base_url?: string
  vibevoice_asr_api_key?: string
  vibevoice_asr_model?: string
  video_gen_default_template?: string
  video_gen_default_scene_count?: number
  default_template?: string
  default_scene_count?: number
  video_gen_prompt_prefix?: string
  image_generation_provider?: string
  image_generation_fallback_order?: string
  image_generation_timeout_seconds?: number
  minimax_api_key?: string
  minimax_base_url?: string
  minimax_image_model?: string
  openai_api_key?: string
  openai_base_url?: string
  openai_image_model?: string
  openai_image_size?: string
  openai_image_quality?: string
  gemini_api_key?: string
  gemini_base_url?: string
  gemini_image_model?: string
  wechat_app_id?: string
  wechat_app_secret?: string
  wechat_api_proxy_url?: string
  wechat_api_proxy_token?: string
  wechat_default_author?: string
  wechat_default_theme?: string
  wechat_default_color?: string
  wechat_markdown_renderer?: string
  wechat_baoyu_markdown_to_html_script?: string
  wechat_baoyu_ai_cover?: boolean
  wechat_baoyu_layout_modules?: boolean
  wechat_baoyu_timeout?: number
  wechat_need_open_comment?: boolean
  wechat_only_fans_can_comment?: boolean
  wechat_exporter_base_url?: string
  wechat_exporter_auth_key?: string
  wechat_collection_output_dir?: string
  wechat_collection_default_format?: string
  wechat_collection_delay_seconds?: number
  wechat_collection_max_articles?: number

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

  // Proxy pools
  listProxyPools() {
    return request<{ id: number; name: string }[]>({
      url: '/api/proxy-pools',
      method: 'get',
    })
  },
}
