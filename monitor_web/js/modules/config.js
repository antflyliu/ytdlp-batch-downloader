// ── Global Config & API Keys ─────────────────────────────────────────
// System config modal and YouTube API key management.

import { api } from '../api.js';
import { esc } from '../utils/format.js';
import { toast, openModal, closeModal, showAppConfirm } from './ui.js';
import { setGConfig } from './state.js';

const el = (id) => document.getElementById(id);

// ── Global Config ────────────────────────────────────────────────────

export async function openConfig() {
  if (!el('modalConfig')) return;
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
  e = el('cfgDefaultApiKey'); if (e) e.value = cfg.default_api_key_id || '';

  // AI 视频切片配置
  e = el('cfgLlmProvider'); if (e) e.value = cfg.llm_provider || 'qwen';
  e = el('cfgLlmApiKey'); if (e) e.value = cfg.llm_api_key || '';
  e = el('cfgLlmModel'); if (e) e.value = cfg.llm_model || '';
  e = el('cfgLlmBaseUrl'); if (e) e.value = cfg.llm_base_url || '';
  e = el('cfgLlmMinScore'); if (e) e.value = cfg.llm_min_score != null ? cfg.llm_min_score : 7.0;
  e = el('cfgLlmCategory'); if (e) e.value = cfg.llm_category || 'knowledge';

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
  openModal('modalConfig');
}

export async function saveConfig() {
  if (!el('modalConfig')) return;

  const v = (id) => { const e = el(id); return e ? e.value.trim() : ''; };
  const c = (id) => { const e = el(id); return e ? e.checked : false; };
  const n = (id) => { const e = el(id); return e ? parseInt(e.value, 10) || 8000 : 8000; };

  const body = {
    global_feishu_url: v('cfgFeishu'),
    global_dingtalk_url: v('cfgDingtalk'),
    global_dingtalk_sign_secret: v('cfgDingtalkSecret') || '',
    global_wecom_url: v('cfgWecom'),
    global_telegram_token: v('cfgTelegramToken'),
    global_telegram_chat_id: v('cfgTelegramChatId'),
    quota_budget_per_day: n('cfgQuotaBudget'),
    quota_usage_timezone: (() => { const e = el('cfgQuotaUsageTimezone'); return e ? e.value : 'local'; })(),
    channel_meta_max_age_days: (() => { const e = el('cfgChannelMetaMaxAge'); const v = e ? parseInt(e.value, 10) : 30; return Number.isNaN(v) ? 30 : v; })(),
    notify_on_scan_error: c('cfgNotifyOnScanError'),
    scan_error_notify_cooldown_seconds: (() => { const e = el('cfgScanErrorCooldown'); return e ? parseInt(e.value, 10) || 300 : 300; })(),
    scan_jitter_seconds: (() => { const e = el('cfgScanJitter'); return e ? parseInt(e.value, 10) || 0 : 0; })(),
    quota_alert_thresholds: (() => {
      const e = el('cfgQuotaAlertThresholds');
      if (!e || !e.value.trim()) return [80, 90, 100];
      const arr = e.value.split(/[,，\s]+/).map(s => parseInt(s.trim(), 10)).filter(n => !Number.isNaN(n) && n >= 1 && n <= 100);
      return arr.length ? arr : [80, 90, 100];
    })(),
    channel_meta_health_check_enabled: c('cfgChannelMetaHealthEnabled'),
    channel_meta_health_check_interval_hours: (() => {
      const e = el('cfgChannelMetaHealthInterval');
      const v = e ? parseInt(e.value, 10) : 24;
      return Number.isNaN(v) || v < 1 ? 24 : v;
    })(),
    notify_on_channel_meta_mismatch: c('cfgNotifyChannelMetaMismatch'),
    download_cookies_file: v('cfgCookiesFile'),
    download_output_path: v('cfgDownloadPath'),
    enable_aria2: c('cfgEnableAria2'),
    default_sub_langs: v('cfgSubLangs') || 'zh-Hans,en',
    default_api_key_id: v('cfgDefaultApiKey') || null,

    // AI 视频切片配置
    llm_provider: (() => { const e = el('cfgLlmProvider'); return e ? e.value : 'qwen'; })(),
    llm_api_key: v('cfgLlmApiKey'),
    llm_model: v('cfgLlmModel'),
    llm_base_url: v('cfgLlmBaseUrl'),
    llm_min_score: (() => { const e = el('cfgLlmMinScore'); return e ? parseFloat(e.value) || 7.0 : 7.0; })(),
    llm_category: (() => { const e = el('cfgLlmCategory'); return e ? e.value : 'knowledge'; })(),

    // 系统默认动态代理配置
    system_dynamic_proxy_enabled: c('cfg_system_dynamic_proxy_enabled'),
    apply_dynamic_proxy_to_new_accounts: c('cfg_apply_dynamic_proxy_to_new_accounts'),
    apply_dynamic_proxy_to_existing_accounts: c('cfg_apply_dynamic_proxy_to_existing_accounts'),
    allow_free_proxy: c('cfg_allow_free_proxy'),
    allow_free_proxy_for_auto_download: c('cfg_allow_free_proxy_for_auto_download'),
    allow_free_proxy_with_cookies: c('cfg_allow_free_proxy_with_cookies'),
    manual_direct_fallback: c('cfg_manual_direct_fallback'),
    auto_direct_fallback: c('cfg_auto_direct_fallback'),
    default_proxy_protocol_order: (() => { const e = el('cfg_default_proxy_protocol_order'); return e ? e.value.split(',').map(s => s.trim()).filter(Boolean) : []; })(),
    default_session_mode: (() => { const e = el('cfg_default_session_mode'); return e ? e.value : 'sticky'; })(),
    default_sticky_minutes: (() => { const e = el('cfg_default_sticky_minutes'); return e ? parseInt(e.value) || 10 : 10; })(),
    mask_proxy_in_logs: c('cfg_mask_proxy_in_logs'),
  };
  const r = await api('POST', '/config', body);
  if (r.ok) { toast('配置已保存', 'ok'); closeModal('modalConfig'); }
  else toast('保存失败', 'err');
}

// ── API Keys ────────────────────────────────────────────────────────

export async function openApiKeys() {
  openModal('modalApiKeys');
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
        <div class="ak-empty-title">无法加载 API Keys</div>
        <div class="ak-empty-desc">请确认 Token 已正确配置</div>
        <button class="btn btn-primary btn-sm" onclick="_promptToken();loadApiKeysList()">重新加载</button>
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
        <div class="ak-empty-title">暂无 API Key</div>
        <div class="ak-empty-desc">点击下方「新增 Key」添加第一个 YouTube API Key</div>
        <button class="btn btn-primary btn-sm" onclick="window.openAddApiKey()">+ 添加第一个 Key</button>
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
          <span class="ak-status ${k.is_active ? 'active' : 'inactive'}">${k.is_active ? '启用' : '禁用'}</span>
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
          <span>已用 <strong class="used">${used.toLocaleString()}</strong></span>
          <span>限额 <strong>${quota.toLocaleString()}</strong></span>
          <span>剩余 <strong class="remaining">${remaining.toLocaleString()}</strong></span>
          <span>扫描 <strong>${k.scans_done || 0}</strong> 次</span>
        </div>
      </div>
      <div class="ak-actions">
        <button class="btn-sm" onclick="window.openEditApiKey(${k.id})" title="编辑">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
        </button>
        <button class="btn-sm danger" onclick="window.deleteApiKey(${k.id})" title="删除">
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
  setText('modalApiKeyFormTitle', '新增 API Key');
  set('akId', ''); set('akName', ''); set('akValue', '');
  const akv = el('akValue'); if (akv) { akv.readOnly = false; akv.style.opacity = '1'; }
  setText('akValueHint', 'YouTube Data API v3 的实际 Key 值，安全存储于本地数据库');
  set('akQuota', '10000'); setCb('akActive', true);
  openModal('modalApiKeyForm');
}

export async function openEditApiKey(id) {
  if (!el('modalApiKeyForm')) return;
  const keys = await api('GET', '/api-keys');
  const k = keys && keys.find(x => x.id === id);
  if (!k) return toast('API Key 不存在', 'err');
  const set = (eid, v) => { const e = el(eid); if (e) e.value = v; };
  const setCb = (eid, v) => { const e = el(eid); if (e) e.checked = v; };
  const setText = (eid, v) => { const e = el(eid); if (e) e.textContent = v; };
  setText('modalApiKeyFormTitle', '编辑 API Key');
  set('akId', k.id); set('akName', k.name); set('akValue', k.key_value);
  const akv = el('akValue'); if (akv) { akv.readOnly = true; akv.style.opacity = '0.5'; }
  setText('akValueHint', 'Key 值创建后不可更改，如需更换请删除后重新创建');
  set('akQuota', k.daily_quota); setCb('akActive', k.is_active);
  openModal('modalApiKeyForm');
}

export async function saveApiKey() {
  if (!el('modalApiKeyForm')) return;
  const id = el('akId')?.value ?? '';
  const name = el('akName')?.value.trim() ?? '';
  if (!name) { toast('名称不能为空', 'err'); return; }
  const body = {
    name,
    daily_quota: parseInt(el('akQuota')?.value, 10) || 10000,
    is_active: !!el('akActive')?.checked,
  };
  if (id) {
    body.key_value = el('akValue')?.value.trim() || undefined;
  } else {
    const keyVal = el('akValue')?.value.trim() ?? '';
    if (!keyVal) { toast('Key 值不能为空', 'err'); return; }
    body.key_value = keyVal;
  }
  let r;
  if (id) r = await api('POST', `/api-keys/${id}`, body);
  else r = await api('POST', '/api-keys', body);
  if (r.error) { toast(r.error, 'err'); return; }
  toast('API Key 已保存', 'ok');
  closeModal('modalApiKeyForm');
  await loadApiKeysList();
  await refreshApiKeySelectors();
}

export async function deleteApiKey(id) {
  const keys = await api('GET', '/api-keys');
  const k = keys && keys.find(x => x.id === id);
  if (!k) return toast('API Key 不存在', 'err');
  const ok = await showAppConfirm({
    title: `确定删除「${k.name}」？`,
    message: '关联的账户将改用系统默认 Key。',
    confirmText: '删除',
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('DELETE', `/api-keys/${id}`);
  if (r.error) { toast(r.error, 'err'); return; }
  if (r.affected_accounts && r.affected_accounts.length > 0) {
    toast(`已删除（${r.affected_accounts.length} 个账户已改用默认 Key）`, 'ok');
  } else {
    toast('已删除', 'ok');
  }
  await loadApiKeysList();
  await refreshApiKeySelectors();
}

// Shared API key selector refresh — re-exported from accounts
export { refreshApiKeySelectors } from './accounts.js';
