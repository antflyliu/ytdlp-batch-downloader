// ── Global Config & API Keys ─────────────────────────────────────────
// System config modal and YouTube API key management.

import { api } from '../api.js';
import { esc } from '../utils/format.js';
import { toast, openModal, closeModal, showAppConfirm } from './ui.js';
import { setGConfig } from './state.js';
import { I18n } from '../../static/js/i18n.js';

const el = (id) => document.getElementById(id);

// ── Global Config ────────────────────────────────────────────────────

export async function openConfig() {
  const cfg = await api('GET', '/config');
  setGConfig(cfg);

  let e;

  e = el('cfgFeishu'); if (e) e.value = cfg.global_feishu_url || '';
  e = el('cfgDingtalk'); if (e) e.value = cfg.global_dingtalk_url || '';
  e = el('cfgDingtalkSecret'); if (e) e.value = cfg.global_dingtalk_sign_secret || '';
  e = el('cfgWecom'); if (e) e.value = cfg.global_wecom_url || '';
  e = el('cfgTelegramToken'); if (e) e.value = cfg.global_telegram_token || '';
  e = el('cfgTelegramChatId'); if (e) e.value = cfg.global_telegram_chat_id || '';
  e = el('cfgQuotaBudget'); if (e) e.value = cfg.quota_budget_per_day || 8000;
  e = el('cfgQuotaUsageTimezone'); if (e) e.value = cfg.quota_usage_timezone || 'local';
  e = el('cfgChannelMetaMaxAge'); if (e) e.value = cfg.channel_meta_max_age_days != null ? cfg.channel_meta_max_age_days : 30;
  e = el('cfgNotifyOnScanError'); if (e) e.checked = !!cfg.notify_on_scan_error;
  e = el('cfgScanErrorCooldown'); if (e) e.value = cfg.scan_error_notify_cooldown_seconds != null ? cfg.scan_error_notify_cooldown_seconds : 300;
  e = el('cfgScanJitter'); if (e) e.value = cfg.scan_jitter_seconds != null ? cfg.scan_jitter_seconds : 0;
  e = el('cfgQuotaAlertThresholds'); if (e) {
    const t = cfg.quota_alert_thresholds;
    e.value = Array.isArray(t) && t.length ? t.join(',') : '80,90,100';
  }
  e = el('cfgChannelMetaHealthEnabled'); if (e) e.checked = cfg.channel_meta_health_check_enabled !== false;
  e = el('cfgChannelMetaHealthInterval'); if (e) e.value = cfg.channel_meta_health_check_interval_hours != null ? cfg.channel_meta_health_check_interval_hours : 24;
  e = el('cfgNotifyChannelMetaMismatch'); if (e) e.checked = cfg.notify_on_channel_meta_mismatch !== false;
  e = el('cfgCookiesFile'); if (e) e.value = cfg.download_cookies_file || '';
  e = el('cfgDownloadPath'); if (e) e.value = cfg.download_output_path || '';
  e = el('cfgEnableAria2'); if (e) e.checked = !!cfg.enable_aria2;
  e = el('cfgSubLangs'); if (e) e.value = cfg.default_sub_langs || 'zh-Hans,en';

  // AI 视频切片配置
  e = el('cfgLlmProvider'); if (e) e.value = cfg.llm_provider || 'qwen';
  e = el('cfgLlmApiKey'); if (e) e.value = cfg.llm_api_key || '';
  e = el('cfgLlmModel'); if (e) e.value = cfg.llm_model || '';
  e = el('cfgLlmBaseUrl'); if (e) e.value = cfg.llm_base_url || '';
  e = el('cfgLlmMinScore'); if (e) e.value = cfg.llm_min_score != null ? cfg.llm_min_score : 7.0;
  e = el('cfgLlmCategory'); if (e) e.value = cfg.llm_category || 'knowledge';
  e = el('cfgClipEmbedThumbnail'); if (e) e.checked = cfg.clip_embed_thumbnail !== false;
  e = el('cfgClipEmbedSubtitle'); if (e) e.checked = cfg.clip_embed_subtitle !== false;
  e = el('cfgClipAdaptAspectRatio'); if (e) e.checked = cfg.clip_adapt_aspect_ratio !== false;

  // 系统默认动态代理配置
  e = el('cfg_system_dynamic_proxy_enabled'); if (e) e.checked = !!cfg.system_dynamic_proxy_enabled;
  e = el('cfg_apply_dynamic_proxy_to_new_accounts'); if (e) e.checked = cfg.apply_dynamic_proxy_to_new_accounts !== false;
  e = el('cfg_apply_dynamic_proxy_to_existing_accounts'); if (e) e.checked = !!cfg.apply_dynamic_proxy_to_existing_accounts;
  e = el('cfg_allow_free_proxy'); if (e) e.checked = cfg.allow_free_proxy !== false;
  e = el('cfg_allow_free_proxy_for_auto_download'); if (e) e.checked = !!cfg.allow_free_proxy_for_auto_download;
  e = el('cfg_allow_free_proxy_with_cookies'); if (e) e.checked = !!cfg.allow_free_proxy_with_cookies;
  e = el('cfg_manual_direct_fallback'); if (e) e.checked = cfg.manual_direct_fallback !== false;
  e = el('cfg_auto_direct_fallback'); if (e) e.checked = !!cfg.auto_direct_fallback;
  const protoOrder = cfg.default_proxy_protocol_order;
  if (Array.isArray(protoOrder)) {
    e = el('cfg_default_proxy_protocol_order'); if (e) e.value = protoOrder.join(',');
  } else {
    e = el('cfg_default_proxy_protocol_order'); if (e) e.value = protoOrder || 'http,https,socks5,socks4';
  }
  e = el('cfg_default_session_mode'); if (e) e.value = cfg.default_session_mode || 'sticky';
  e = el('cfg_default_sticky_minutes'); if (e) e.value = cfg.default_sticky_minutes || 10;
  e = el('cfg_mask_proxy_in_logs'); if (e) e.checked = cfg.mask_proxy_in_logs !== false;

  await refreshApiKeySelectors();
  e = el('cfgDefaultApiKey');
  if (e) e.value = cfg.default_api_key_id || '';
}

export async function saveConfig() {
  /** 配置拆为多页后，当前页可能没有全部字段；先 GET 再合并，避免用空值覆盖服务端。 */
  const snapshot = await api('GET', '/config');
  setGConfig(snapshot);
  const S = snapshot;

  const v = (id) => { const e = el(id); return e ? e.value.trim() : ''; };
  const c = (id) => { const e = el(id); return e ? e.checked : false; };
  const n = (id) => { const e = el(id); return e ? parseInt(e.value, 10) || 8000 : 8000; };

  const body = {
    global_feishu_url: el('cfgFeishu') ? v('cfgFeishu') : (S.global_feishu_url ?? ''),
    global_dingtalk_url: el('cfgDingtalk') ? v('cfgDingtalk') : (S.global_dingtalk_url ?? ''),
    global_dingtalk_sign_secret: el('cfgDingtalkSecret') ? (v('cfgDingtalkSecret') || '') : (S.global_dingtalk_sign_secret ?? ''),
    global_wecom_url: el('cfgWecom') ? v('cfgWecom') : (S.global_wecom_url ?? ''),
    global_telegram_token: el('cfgTelegramToken') ? v('cfgTelegramToken') : (S.global_telegram_token ?? ''),
    global_telegram_chat_id: el('cfgTelegramChatId') ? v('cfgTelegramChatId') : (S.global_telegram_chat_id ?? ''),
    quota_budget_per_day: el('cfgQuotaBudget') ? n('cfgQuotaBudget') : (typeof S.quota_budget_per_day === 'number' ? S.quota_budget_per_day : 8000),
    quota_usage_timezone: (() => {
      const e = el('cfgQuotaUsageTimezone');
      if (e) return e.value;
      return S.quota_usage_timezone || 'local';
    })(),
    channel_meta_max_age_days: (() => {
      const e = el('cfgChannelMetaMaxAge');
      if (e) {
        const x = parseInt(e.value, 10);
        return Number.isNaN(x) ? 30 : x;
      }
      const x = S.channel_meta_max_age_days;
      return typeof x === 'number' && !Number.isNaN(x) ? x : 30;
    })(),
    notify_on_scan_error: el('cfgNotifyOnScanError') ? c('cfgNotifyOnScanError') : !!S.notify_on_scan_error,
    scan_error_notify_cooldown_seconds: (() => {
      const e = el('cfgScanErrorCooldown');
      if (e) return parseInt(e.value, 10) || 300;
      const x = S.scan_error_notify_cooldown_seconds;
      return typeof x === 'number' ? x : 300;
    })(),
    scan_jitter_seconds: (() => {
      const e = el('cfgScanJitter');
      if (e) return parseInt(e.value, 10) || 0;
      const x = S.scan_jitter_seconds;
      return typeof x === 'number' ? x : 0;
    })(),
    quota_alert_thresholds: (() => {
      const e = el('cfgQuotaAlertThresholds');
      if (e) {
        if (!e.value.trim()) return [80, 90, 100];
        const arr = e.value.split(/[,，\s]+/).map(s => parseInt(s.trim(), 10)).filter(n => !Number.isNaN(n) && n >= 1 && n <= 100);
        return arr.length ? arr : [80, 90, 100];
      }
      const t = S.quota_alert_thresholds;
      return Array.isArray(t) && t.length ? t : [80, 90, 100];
    })(),
    channel_meta_health_check_enabled: el('cfgChannelMetaHealthEnabled') ? c('cfgChannelMetaHealthEnabled') : S.channel_meta_health_check_enabled !== false,
    channel_meta_health_check_interval_hours: (() => {
      const e = el('cfgChannelMetaHealthInterval');
      if (e) {
        const x = parseInt(e.value, 10);
        return Number.isNaN(x) || x < 1 ? 24 : x;
      }
      const x = S.channel_meta_health_check_interval_hours;
      return typeof x === 'number' && !Number.isNaN(x) && x >= 1 ? x : 24;
    })(),
    notify_on_channel_meta_mismatch: el('cfgNotifyChannelMetaMismatch') ? c('cfgNotifyChannelMetaMismatch') : S.notify_on_channel_meta_mismatch !== false,
    download_cookies_file: el('cfgCookiesFile') ? v('cfgCookiesFile') : (S.download_cookies_file ?? ''),
    download_output_path: el('cfgDownloadPath') ? v('cfgDownloadPath') : (S.download_output_path ?? ''),
    enable_aria2: el('cfgEnableAria2') ? c('cfgEnableAria2') : !!S.enable_aria2,
    default_sub_langs: el('cfgSubLangs') ? (v('cfgSubLangs') || 'zh-Hans,en') : (S.default_sub_langs || 'zh-Hans,en'),
    default_api_key_id: el('cfgDefaultApiKey') ? (v('cfgDefaultApiKey') || null) : (S.default_api_key_id ?? null),

    llm_provider: (() => {
      const e = el('cfgLlmProvider');
      if (e) return e.value;
      return S.llm_provider || 'qwen';
    })(),
    llm_api_key: el('cfgLlmApiKey') ? v('cfgLlmApiKey') : (S.llm_api_key ?? ''),
    llm_model: el('cfgLlmModel') ? v('cfgLlmModel') : (S.llm_model ?? ''),
    llm_base_url: el('cfgLlmBaseUrl') ? v('cfgLlmBaseUrl') : (S.llm_base_url ?? ''),
    llm_min_score: (() => {
      const e = el('cfgLlmMinScore');
      if (e) return parseFloat(e.value) || 7.0;
      const x = S.llm_min_score;
      return typeof x === 'number' && !Number.isNaN(x) ? x : 7.0;
    })(),
    llm_category: (() => {
      const e = el('cfgLlmCategory');
      if (e) return e.value;
      return S.llm_category || 'knowledge';
    })(),
    clip_embed_thumbnail: el('cfgClipEmbedThumbnail') ? c('cfgClipEmbedThumbnail') : S.clip_embed_thumbnail !== false,
    clip_embed_subtitle: el('cfgClipEmbedSubtitle') ? c('cfgClipEmbedSubtitle') : S.clip_embed_subtitle !== false,
    clip_adapt_aspect_ratio: el('cfgClipAdaptAspectRatio') ? c('cfgClipAdaptAspectRatio') : S.clip_adapt_aspect_ratio !== false,

    system_dynamic_proxy_enabled: el('cfg_system_dynamic_proxy_enabled') ? c('cfg_system_dynamic_proxy_enabled') : !!S.system_dynamic_proxy_enabled,
    apply_dynamic_proxy_to_new_accounts: el('cfg_apply_dynamic_proxy_to_new_accounts') ? c('cfg_apply_dynamic_proxy_to_new_accounts') : S.apply_dynamic_proxy_to_new_accounts !== false,
    apply_dynamic_proxy_to_existing_accounts: el('cfg_apply_dynamic_proxy_to_existing_accounts') ? c('cfg_apply_dynamic_proxy_to_existing_accounts') : !!S.apply_dynamic_proxy_to_existing_accounts,
    allow_free_proxy: el('cfg_allow_free_proxy') ? c('cfg_allow_free_proxy') : S.allow_free_proxy !== false,
    allow_free_proxy_for_auto_download: el('cfg_allow_free_proxy_for_auto_download') ? c('cfg_allow_free_proxy_for_auto_download') : !!S.allow_free_proxy_for_auto_download,
    allow_free_proxy_with_cookies: el('cfg_allow_free_proxy_with_cookies') ? c('cfg_allow_free_proxy_with_cookies') : !!S.allow_free_proxy_with_cookies,
    manual_direct_fallback: el('cfg_manual_direct_fallback') ? c('cfg_manual_direct_fallback') : S.manual_direct_fallback !== false,
    auto_direct_fallback: el('cfg_auto_direct_fallback') ? c('cfg_auto_direct_fallback') : !!S.auto_direct_fallback,
    default_proxy_protocol_order: (() => {
      const e = el('cfg_default_proxy_protocol_order');
      if (e) return e.value.split(',').map(s => s.trim()).filter(Boolean);
      const p = S.default_proxy_protocol_order;
      if (Array.isArray(p)) return p;
      if (typeof p === 'string') return p.split(',').map(s => s.trim()).filter(Boolean);
      return ['http', 'https', 'socks5', 'socks4'];
    })(),
    default_session_mode: (() => {
      const e = el('cfg_default_session_mode');
      if (e) return e.value;
      return S.default_session_mode || 'sticky';
    })(),
    default_sticky_minutes: (() => {
      const e = el('cfg_default_sticky_minutes');
      if (e) return parseInt(e.value, 10) || 10;
      const x = S.default_sticky_minutes;
      return typeof x === 'number' && !Number.isNaN(x) ? x : 10;
    })(),
    mask_proxy_in_logs: el('cfg_mask_proxy_in_logs') ? c('cfg_mask_proxy_in_logs') : S.mask_proxy_in_logs !== false,
  };
  const r = await api('POST', '/config', body);
  if (r.ok) { toast(I18n.t('apiKeysUi.saveConfigOk'), 'ok'); closeModal('modalConfig'); }
  else toast(I18n.t('apiKeysUi.saveConfigFail'), 'err');
}

// ── API Keys ────────────────────────────────────────────────────────

export async function openApiKeys() {
  await loadApiKeysList();
}

export async function loadApiKeysList() {
  const keys = await api('GET', '/api-keys');
  const listEl = el('apiKeysList');
  if (!listEl) return;
  if (!keys || !Array.isArray(keys)) {
    listEl.innerHTML = `
      <div class="ak-empty">
        <div class="ak-empty-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
          </svg>
        </div>
        <div class="ak-empty-title">${esc(I18n.t('apiKeysUi.emptyLoadTitle'))}</div>
        <div class="ak-empty-desc">${esc(I18n.t('apiKeysUi.emptyLoadDesc'))}</div>
        <button class="btn btn-primary btn-sm" onclick="_promptToken();loadApiKeysList()">${esc(I18n.t('apiKeysUi.emptyReload'))}</button>
      </div>`;
    return;
  }
  if (keys.length === 0) {
    listEl.innerHTML = `
      <div class="ak-empty">
        <div class="ak-empty-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
          </svg>
        </div>
        <div class="ak-empty-title">${esc(I18n.t('apiKeysUi.emptyNoKeysTitle'))}</div>
        <div class="ak-empty-desc">${esc(I18n.t('apiKeysUi.emptyNoKeysDesc'))}</div>
        <button class="btn btn-primary btn-sm" onclick="window.openAddApiKey()">${esc(I18n.t('apiKeysUi.emptyAddFirst'))}</button>
      </div>`;
    return;
  }
  listEl.innerHTML = keys.map(k => {
    const used = k.quota_used || 0;
    const quota = k.daily_quota;
    const pct = quota > 0 ? Math.min(Math.round(used / quota * 100), 100) : 0;
    const remaining = Math.max(quota - used, 0);
    const color = pct >= 90 ? 'var(--error)' : pct >= 70 ? 'var(--warning)' : 'var(--accent)';

    const R = 22, C = 2 * Math.PI * R;
    const dashFill = (pct / 100) * C;
    const dashGap = C - dashFill;
    const cx = 28, cy = 28;

    return `<div class="ak-card">
      <div class="ak-ring">
        <svg viewBox="0 0 56 56">
          <circle class="ak-ring-bg" cx="${cx}" cy="${cy}" r="${R}"/>
          <circle class="ak-ring-progress" cx="${cx}" cy="${cy}" r="${R}"
            stroke="${color}"
            stroke-dasharray="${dashFill.toFixed(1)} ${dashGap.toFixed(1)}"/>
        </svg>
        <div class="ak-ring-text">
          <span class="ak-ring-pct" style="color:${color}">${pct}</span>
          <span class="ak-ring-label">%</span>
        </div>
      </div>
      <div class="ak-info">
        <div class="ak-name-row">
          <span class="ak-name">${esc(k.name)}</span>
          <span class="ak-status ${k.is_active ? 'active' : 'inactive'}">${k.is_active ? esc(I18n.t('apiKeysUi.statusOn')) : esc(I18n.t('apiKeysUi.statusOff'))}</span>
        </div>
        <div class="ak-key">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/><path d="M12 8v4l2 2"/>
          </svg>
          ${esc(k.key_value)}
        </div>
        <div class="ak-quota-bar">
          <div class="ak-quota-fill" style="width:${pct}%;background:${color}"></div>
        </div>
        <div class="ak-quota-stats">
          <span>${esc(I18n.t('apiKeysUi.quotaUsed'))} <strong class="used">${used.toLocaleString()}</strong></span>
          <span>${esc(I18n.t('apiKeysUi.quotaLimit'))} <strong>${quota.toLocaleString()}</strong></span>
          <span>${esc(I18n.t('apiKeysUi.quotaRemaining'))} <strong class="remaining">${remaining.toLocaleString()}</strong></span>
          <span>${esc(I18n.t('apiKeysUi.scans'))} <strong>${k.scans_done || 0}</strong> ${esc(I18n.t('apiKeysUi.times'))}</span>
        </div>
      </div>
      <div class="ak-actions">
        <button class="btn-sm" onclick="window.openEditApiKey(${k.id})" title="${esc(I18n.t('apiKeysUi.editTitle'))}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
        </button>
        <button class="btn-sm danger" onclick="window.deleteApiKey(${k.id})" title="${esc(I18n.t('apiKeysUi.deleteTitle'))}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6l-1 14H6L5 6"/>
            <path d="M10 11v6M14 11v6"/>
            <path d="M9 6V4h6v2"/>
          </svg>
        </button>
      </div>
    </div>`;
  }).join('');
}

export function openAddApiKey() {
  if (!el('modalApiKeyForm')) return;
  const set = (id, v) => { const e = el(id); if (e) e.value = v; };
  const setCb = (id, v) => { const e = el(id); if (e) e.checked = v; };
  const setText = (id, v) => { const e = el(id); if (e) e.textContent = v; };
  setText('modalApiKeyFormTitle', I18n.t('apiKeyForm.addTitle'));
  set('akId', ''); set('akName', ''); set('akValue', '');
  const akv = el('akValue'); if (akv) { akv.readOnly = false; akv.style.opacity = '1'; }
  setText('akValueHint', I18n.t('apiKeyForm.keyValueHint'));
  set('akQuota', '10000'); setCb('akActive', true);
  openModal('modalApiKeyForm');
}

export async function openEditApiKey(id) {
  if (!el('modalApiKeyForm')) return;
  const keys = await api('GET', '/api-keys');
  const k = keys && keys.find(x => x.id === id);
  if (!k) return toast(I18n.t('apiKeysUi.toastNotFound'), 'err');
  const set = (eid, v) => { const e = el(eid); if (e) e.value = v; };
  const setCb = (eid, v) => { const e = el(eid); if (e) e.checked = v; };
  const setText = (eid, v) => { const e = el(eid); if (e) e.textContent = v; };
  setText('modalApiKeyFormTitle', I18n.t('apiKeyForm.editTitle'));
  set('akId', k.id); set('akName', k.name); set('akValue', k.key_value);
  const akv = el('akValue'); if (akv) { akv.readOnly = true; akv.style.opacity = '0.5'; }
  setText('akValueHint', I18n.t('apiKeyForm.keyValueHintEdit'));
  set('akQuota', k.daily_quota); setCb('akActive', k.is_active);
  openModal('modalApiKeyForm');
}

export async function saveApiKey() {
  if (!el('modalApiKeyForm')) return;
  const id = el('akId')?.value ?? '';
  const name = el('akName')?.value.trim() ?? '';
  if (!name) { toast(I18n.t('apiKeysUi.toastNameRequired'), 'err'); return; }
  const body = {
    name,
    daily_quota: parseInt(el('akQuota')?.value, 10) || 10000,
    is_active: !!el('akActive')?.checked,
  };
  if (id) {
    body.key_value = el('akValue')?.value.trim() || undefined;
  } else {
    const keyVal = el('akValue')?.value.trim() ?? '';
    if (!keyVal) { toast(I18n.t('apiKeysUi.toastKeyRequired'), 'err'); return; }
    body.key_value = keyVal;
  }
  let r;
  if (id) r = await api('POST', `/api-keys/${id}`, body);
  else r = await api('POST', '/api-keys', body);
  if (r.error) { toast(r.error, 'err'); return; }
  toast(I18n.t('apiKeysUi.toastSaved'), 'ok');
  closeModal('modalApiKeyForm');
  await loadApiKeysList();
  await refreshApiKeySelectors();
}

export async function deleteApiKey(id) {
  const keys = await api('GET', '/api-keys');
  const k = keys && keys.find(x => x.id === id);
  if (!k) return toast(I18n.t('apiKeysUi.toastNotFound'), 'err');
  const ok = await showAppConfirm({
    title: I18n.t('apiKeysUi.deleteConfirmTitle').replace('{name}', k.name),
    message: I18n.t('apiKeysUi.deleteConfirmMsg'),
    confirmText: I18n.t('apiKeysUi.deleteConfirmBtn'),
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('DELETE', `/api-keys/${id}`);
  if (r.error) { toast(r.error, 'err'); return; }
  if (r.affected_accounts && r.affected_accounts.length > 0) {
    toast(I18n.t('apiKeysUi.toastDeletedWithAccounts').replace('{n}', String(r.affected_accounts.length)), 'ok');
  } else {
    toast(I18n.t('apiKeysUi.toastDeleted'), 'ok');
  }
  await loadApiKeysList();
  await refreshApiKeySelectors();
}

// Shared API key selector refresh — re-exported from accounts
export { refreshApiKeySelectors } from './accounts.js';

window.init_api_keys_page = openApiKeys;
window.init_settings_page = openConfig;
window.init_settings_notify_page = openConfig;
window.init_settings_api_page = openConfig;
window.init_settings_download_page = openConfig;
window.init_settings_ai_page = openConfig;
window.init_settings_dynamic_page = openConfig;
