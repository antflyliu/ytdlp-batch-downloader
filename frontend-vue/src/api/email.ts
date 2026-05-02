import request from '@/api/request'

export interface EmailAccount {
  id: number
  provider: 'gmail' | 'imap' | string
  display_name: string
  email_address: string
  status?: string
  gmail_client_id?: string | null
  gmail_scope?: string[]
  imap_host?: string | null
  imap_port?: number | null
  imap_security?: string | null
  imap_username?: string | null
  smtp_host?: string | null
  smtp_port?: number | null
  smtp_security?: string | null
  smtp_username?: string | null
  sync_mode?: string | null
  poll_interval_seconds?: number | null
  include_spam_trash?: boolean
  max_messages_per_sync?: number | null
  last_sync_at?: string | null
  last_error?: string | null
  has_gmail_client_secret?: boolean
  has_gmail_refresh_token?: boolean
  has_imap_password?: boolean
  has_smtp_password?: boolean
  created_at?: string
  updated_at?: string
}

export interface EmailAccountPayload {
  provider: string
  display_name: string
  email_address: string
  status?: string
  gmail_client_id?: string
  gmail_client_secret?: string
  gmail_refresh_token?: string
  gmail_scope?: string[]
  imap_host?: string
  imap_port?: number
  imap_security?: string
  imap_username?: string
  imap_password?: string
  smtp_host?: string
  smtp_port?: number
  smtp_security?: string
  smtp_username?: string
  smtp_password?: string
  sync_mode?: string
  poll_interval_seconds?: number
  include_spam_trash?: boolean
  max_messages_per_sync?: number
}

export interface GmailOAuthStatus {
  configured: boolean
  client_id_configured: boolean
  client_secret_configured: boolean
  redirect_uri: string
  scopes: string[]
  account_id?: number
  email_address?: string
  has_refresh_token?: boolean
  account_scopes?: string[]
  read_authorized?: boolean
  send_authorized?: boolean
  authorized?: boolean
}

export interface GmailOAuthStartPayload {
  account_id?: number | null
  base_url?: string
  return_to?: string
}

export interface GmailSendPayload {
  account_id: number
  to: string
  subject: string
  body: string
}

export interface EmailMessage {
  id: number
  account_id: number
  provider?: string
  provider_message_id?: string
  provider_thread_id?: string | null
  rfc_message_id?: string | null
  subject?: string | null
  from_addr?: string | null
  to_addr?: string | null
  cc_addr?: string | null
  received_at?: string | null
  sent_at?: string | null
  snippet?: string | null
  body_text?: string | null
  body_markdown_path?: string | null
  raw_mime_path?: string | null
  html_body_path?: string | null
  body_hash?: string | null
  dedupe_key?: string | null
  classification?: Record<string, any>
  cleaning_report?: Record<string, any>
  processing_status?: string | null
  source_url?: string | null
  error?: string | null
  attachments?: EmailAttachment[]
  created_at?: string
  updated_at?: string
}

export interface EmailAttachment {
  id?: number
  filename?: string | null
  content_type?: string | null
  size?: number | null
  content_id?: string | null
  disposition?: string | null
}

export interface GenerateVariantsPayload {
  platforms?: string[]
  target_lang?: string
  article_task_id?: string
}

export interface BatchGeneratePayload {
  message_ids: number[]
  platforms?: string[]
  target_lang?: string
}

export interface ContentTarget {
  id: number
  platform: string
  display_name: string
  enabled?: boolean
  output_contract?: Record<string, any>
  prompt_profile?: Record<string, any>
  publish_mode?: string | null
  created_at?: string
  updated_at?: string
}

export interface ContentTargetPayload {
  display_name?: string
  enabled?: boolean
  output_contract?: Record<string, any>
  prompt_profile?: Record<string, any>
  publish_mode?: string
}

export interface ContentVariant {
  id: number
  source_type: string
  source_id: string
  article_task_id?: string | null
  target_id?: number | null
  platform: string
  title?: string | null
  summary?: string | null
  body_path?: string | null
  body?: string | null
  metadata?: Record<string, any>
  quality?: Record<string, any>
  status?: string | null
  created_at?: string
  updated_at?: string
}

export interface ContentVariantPayload {
  title?: string
  summary?: string
  body?: string
  status?: string
  metadata?: Record<string, any>
  quality?: Record<string, any>
}

export default {
  listAccounts() {
    return request<EmailAccount[]>({
      url: '/api/email/accounts',
      method: 'get',
    })
  },

  createAccount(data: EmailAccountPayload) {
    return request<Record<string, unknown>>({
      url: '/api/email/accounts',
      method: 'post',
      data,
    })
  },

  updateAccount(id: number, data: EmailAccountPayload) {
    return request<Record<string, unknown>>({
      url: `/api/email/accounts/${id}/update`,
      method: 'post',
      data,
    })
  },

  deleteAccount(id: number) {
    return request<Record<string, unknown>>({
      url: `/api/email/accounts/${id}`,
      method: 'delete',
    })
  },

  testAccount(id: number) {
    return request<Record<string, unknown>>({
      url: `/api/email/accounts/${id}/test`,
      method: 'post',
    })
  },

  pauseAccount(id: number) {
    return request<Record<string, unknown>>({
      url: `/api/email/accounts/${id}/pause`,
      method: 'post',
    })
  },

  resumeAccount(id: number) {
    return request<Record<string, unknown>>({
      url: `/api/email/accounts/${id}/resume`,
      method: 'post',
    })
  },

  syncNow(id: number, data?: { max_messages?: number }) {
    return request<Record<string, unknown>>({
      url: `/api/email/accounts/${id}/sync`,
      method: 'post',
      data,
    })
  },

  gmailOAuthStatus(params?: { account_id?: number | null }) {
    return request<GmailOAuthStatus>({
      url: '/api/email/auth/gmail/status',
      method: 'get',
      params,
    })
  },

  startGmailOAuth(data: GmailOAuthStartPayload) {
    return request<Record<string, unknown>>({
      url: '/api/email/auth/gmail/start',
      method: 'post',
      data,
    })
  },

  sendGmail(data: GmailSendPayload) {
    return request<Record<string, unknown>>({
      url: '/api/email/gmail/send',
      method: 'post',
      data,
    })
  },

  listMessages(params?: {
    account_id?: number | null
    status?: string | null
    q?: string | null
    limit?: number
    offset?: number
  }) {
    return request<Record<string, unknown>>({
      url: '/api/email/messages',
      method: 'get',
      params,
    })
  },

  getMessage(id: number) {
    return request<Record<string, unknown>>({
      url: `/api/email/messages/${id}`,
      method: 'get',
    })
  },

  cleanMessage(id: number) {
    return request<Record<string, unknown>>({
      url: `/api/email/messages/${id}/clean`,
      method: 'post',
    })
  },

  classifyMessage(id: number) {
    return request<Record<string, unknown>>({
      url: `/api/email/messages/${id}/classify`,
      method: 'post',
    })
  },

  ignoreMessage(id: number) {
    return request<Record<string, unknown>>({
      url: `/api/email/messages/${id}/ignore`,
      method: 'post',
    })
  },

  generateVariants(id: number, data?: GenerateVariantsPayload) {
    return request<Record<string, unknown>>({
      url: `/api/email/messages/${id}/generate`,
      method: 'post',
      data,
    })
  },

  batchGenerate(data: BatchGeneratePayload) {
    return request<Record<string, unknown>>({
      url: '/api/email/messages/batch-generate',
      method: 'post',
      data,
    })
  },

  listTargets() {
    return request<Record<string, unknown>>({
      url: '/api/content/targets',
      method: 'get',
    })
  },

  updateTarget(id: number, data: ContentTargetPayload) {
    return request<Record<string, unknown>>({
      url: `/api/content/targets/${id}/update`,
      method: 'post',
      data,
    })
  },

  listVariants(params?: {
    source_type?: string | null
    source_id?: string | null
    platform?: string | null
    include_body?: boolean
  }) {
    return request<Record<string, unknown>>({
      url: '/api/content/variants',
      method: 'get',
      params,
    })
  },

  getVariant(id: number) {
    return request<Record<string, unknown>>({
      url: `/api/content/variants/${id}`,
      method: 'get',
    })
  },

  updateVariant(id: number, data: ContentVariantPayload) {
    return request<Record<string, unknown>>({
      url: `/api/content/variants/${id}/update`,
      method: 'post',
      data,
    })
  },

  exportVariant(id: number, data?: { format?: string }) {
    return request<Record<string, unknown>>({
      url: `/api/content/variants/${id}/export`,
      method: 'post',
      data,
    })
  },

  createWechatDraft(id: number) {
    return request<Record<string, unknown>>({
      url: `/api/content/variants/${id}/wechat-draft`,
      method: 'post',
    })
  },
}
