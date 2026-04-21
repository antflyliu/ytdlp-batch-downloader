// ── Account Operations ──────────────────────────────────────────────
// Account CRUD, scan operations, stats loading, and refresh orchestration.

import { api } from '../api.js';
import { esc, fmtTime, fmtDuration } from '../utils/format.js';
import { toast, openModal, closeModal, _resetScanNowState, showAppConfirm } from './ui.js';
import {
  _pendingScanNow,
  _scanNowSubmitting,
  _scanNowCooldown,
  _refreshChain,
  _mainRefreshTimer,
  _gConfig,
  setRefreshChain,
  setGConfig,
  setPendingScanNow,
  setScanNowSubmitting,
  setMainRefreshTimer,
} from './state.js';
import { loadAccounts } from '../components/account-list.js';
import { loadEvents } from '../components/event-log.js';
import { loadStatus } from '../components/scheduler-panel.js';

const SCAN_NOW_COOLDOWN_MS = 3000;

// ── DOM Helpers (guard against lazy-loaded templates) ─────────────────
const el = (id) => document.getElementById(id);
const $ = (sel) => document.querySelector(sel);

// ── Platform Selection ───────────────────────────────────────────────
export function selectPlatform(p) {
  const accPlatform = el('accPlatform');
  if (!accPlatform) return;
  const btns = document.querySelectorAll('.platform-btn');
  btns.forEach(b => b.className = 'platform-btn');
  const idx = p === 'feishu' ? 1 : p === 'dingtalk' ? 2 : p === 'telegram' ? 3 : 2;
  const btn = document.querySelector(`.platform-btn:nth-child(${idx})`);
  if (btn) btn.className = `platform-btn active-${p}`;
  accPlatform.value = p;
  const isFeishu = p === 'feishu';
  const ftc = el('feishuTemplateConfig');
  const dssg = el('dingtalkSignSecretGroup');
  const wlhDefault = el('webhookHintDefault');
  const wlhTg = el('webhookHintTelegram');
  if (ftc) ftc.style.display = isFeishu ? '' : 'none';
  if (dssg) dssg.style.display = p === 'dingtalk' ? '' : 'none';

  // Telegram: separate Bot Token field; Webhook URL field is for feishu/dingtalk/wecom
  const ttg = el('telegramTokenGroup');
  const accWebhookGroup = el('accWebhookGroup');
  const accWebhook = el('accWebhook');
  const accWebhookLabel = el('accWebhookLabel');
  if (ttg) ttg.style.display = p === 'telegram' ? '' : 'none';
  // Telegram 不使用 Webhook URL，隐藏整个字段组
  if (accWebhookGroup) accWebhookGroup.style.display = p === 'telegram' ? 'none' : '';
  if (wlhDefault) wlhDefault.style.display = p === 'telegram' ? 'none' : '';
  if (wlhTg) wlhTg.style.display = p === 'telegram' ? '' : 'none';
  if (accWebhook && accWebhookLabel && p !== 'telegram') {
    if (p === 'dingtalk') {
      accWebhook.placeholder = 'https://oapi.dingtalk.com/robot/send?access_token=xxx';
      accWebhookLabel.textContent = 'Webhook URL';
    } else {
      accWebhook.placeholder = 'https://open.feishu.cn/open-apis/bot/v2/hook/xxx';
      accWebhookLabel.textContent = 'Webhook URL';
    }
  }
  // 切换平台时清除不属于当前平台的字段，避免跨平台污染（Bug 7）
  // Feishu/Dingtalk 共用 accWebhook，需清除；Telegram 用独立字段
  if (p === 'telegram') {
    // 离开 Telegram → 清除 Webhook（不属于 Telegram）
    if (accWebhook) accWebhook.value = '';
  } else {
    // 切换到 Feishu/Dingtalk → 清除 Telegram Bot Token（不属于这两个平台）
    const accTgToken = el('accTelegramToken');
    if (accTgToken) accTgToken.value = '';
    // 切换时 accWebhook 保持原值（各自填写自己的 URL）
  }
  updateFeishuModeUI();
}

export function updateFeishuModeUI() {
  const accPlatform = el('accPlatform');
  const accFeishuMode = el('accFeishuMode');
  if (!accPlatform || !accFeishuMode) return;
  const isFeishu = accPlatform.value === 'feishu';
  const isTemplate = accFeishuMode.value === 'template';
  const show = isFeishu && isTemplate;
  const ftig = el('feishuTemplateIdGroup');
  const fstig = el('feishuScanTemplateIdGroup');
  if (ftig) ftig.style.display = show ? '' : 'none';
  if (fstig) fstig.style.display = show ? '' : 'none';
}

// ── Stats ────────────────────────────────────────────────────────────
export async function loadStats() {
  const [stats, quota] = await Promise.all([
    api('GET', '/stats'),
    api('GET', '/quota').catch(() => null),
  ]);
  let totalScans = 0, totalNew = 0, lastScan = '—';
  if (Array.isArray(stats) && stats.length > 0) {
    totalScans = stats.reduce((s, r) => s + (r.total_scans || 0), 0);
    totalNew = stats.reduce((s, r) => s + (r.total_new_videos || 0), 0);
    const latest = stats.find(r => r.last_scan_at);
    lastScan = latest && latest.last_scan_at ? fmtTime(latest.last_scan_at) : I18n.t('account.neverScanned');
  }
  const sa = el('statAccounts'), ss = el('statScans'), sn = el('statNew'), sl = el('statLast');
  if (sa) sa.textContent = Array.isArray(stats) ? String(stats.length) : '—';
  if (ss) ss.textContent = totalScans;
  if (sn) sn.textContent = totalNew;
  if (sl) sl.textContent = lastScan;

  if (quota && quota.items && quota.items.length > 0) {
    let totalUsed = 0, totalBudget = 0, totalScanCount = 0, blockedScans = 0;
    quota.items.forEach(q => {
      totalUsed += q.quota_used || 0;
      totalBudget += q.daily_quota || 8000;
      totalScanCount += q.scans_done || 0;
      blockedScans += q.blocked_scans || 0;
    });
    const pct = totalBudget > 0 ? Math.min(Math.round(totalUsed / totalBudget * 100), 100) : 0;
    const color = pct >= 90 ? 'var(--error)' : pct >= 70 ? 'var(--warning)' : 'var(--success)';
    const qc = el('quotaCard'), sq = el('statQuota'), qb = el('quotaBar'), qsub = el('quotaSub');
    if (qc) qc.style.display = '';
    if (sq) { sq.textContent = totalUsed.toLocaleString() + ' / ' + totalBudget.toLocaleString() + ' units'; sq.style.color = color; }
    if (qb) { qb.style.width = pct + '%'; qb.style.background = color; }
    if (qsub) qsub.textContent =
      I18n.t('account.statsScans').replace('{n}', totalScanCount) +
      (blockedScans > 0 ? I18n.t('account.statsBlocked').replace('{n}', blockedScans) : '') +
      ' · ' + pct + '%' +
      ' · ' + quota.items.length + I18n.t('account.statsKeys');
  } else {
    const qc = el('quotaCard');
    if (qc) qc.style.display = 'none';
  }
}

// ── Refresh Orchestration ────────────────────────────────────────────
const AUTO_REFRESH_INTERVAL_MS = 30000;  // 30 秒自动刷新主页面数据

/**
 * Serial queue: overlapping refresh() calls (e.g. timer + manual) run
 * sequentially without dropping subsequent cycles.
 */
export async function refresh() {
  const run = () => Promise.all([loadStatus(), loadAccounts(), loadStats(), loadEvents()]);
  const p = _refreshChain.then(run, run);
  setRefreshChain(p.catch(() => {}));
  return p;
}

/**
 * Start auto-refresh timer (刷新事件日志 / 调度器状态 / 账户状态)。
 * 已启动则忽略，支持重复调用。
 */
export function startAutoRefresh() {
  if (_mainRefreshTimer !== null) return;  // 已在运行
  const timer = setInterval(refresh, AUTO_REFRESH_INTERVAL_MS);
  setMainRefreshTimer(timer);
}

/**
 * Stop auto-refresh timer.
 */
export function stopAutoRefresh() {
  if (_mainRefreshTimer === null) return;
  clearInterval(_mainRefreshTimer);
  setMainRefreshTimer(null);
}

// ── Account Modal ────────────────────────────────────────────────────

export async function openAddAccount() {
  const mt = el('modalAccountTitle');
  if (!mt) return; // Modal template not loaded yet
  const set = (id, v) => { const e = el(id); if (e) e.value = v; };
  const setCb = (id, v) => { const e = el(id); if (e) e.checked = v; };
  mt.textContent = I18n.t('account.modalTitleAdd');
  set('accId', ''); set('accName', ''); set('accChannel', '');
  set('accApiKeySelect', ''); set('accApiKeyId', '');
  set('accApiKeyEnv', 'YOUTUBE_Data_API_V3');
  set('accMode', 'playlist'); set('accLimit', '5'); set('accInterval', '5');
  set('accWebhook', ''); set('accTelegramToken', ''); set('accDingtalkSecret', '');
  set('accFeishuMode', 'card_json');
  set('accFeishuTemplateId', ''); set('accFeishuScanTemplateId', '');
  setCb('accEnabled', true); setCb('accNotify', true); setCb('accProxyEnabled', false);
  const pps = el('accProxyPoolSelect');
  if (pps) { pps.value = ''; pps.disabled = true; pps.style.opacity = '0.4'; }
  set('accDownloadProxyMode', 'auto');
  onAccountProxyModeChange();
  selectPlatform('feishu');
  await refreshApiKeySelectors();
  await refreshProxyPoolSelectors();
  await toggleProxySection();
  openModal('modalAccount');
}

export async function openEditAccount(id) {
  const mt = el('modalAccountTitle');
  if (!mt) return;
  const accounts = await api('GET', '/accounts');
  const acc = accounts.find(a => a.id === id);
  if (!acc) return toast(I18n.t('account.accountNotFound'), 'err');
  const set = (eid, v) => { const e = el(eid); if (e) e.value = v; };
  const setCb = (eid, v) => { const e = el(eid); if (e) e.checked = v; };
  mt.textContent = I18n.t('account.modalTitleEdit');
  set('accId', acc.id); set('accName', acc.name); set('accChannel', acc.channel_url);
  set('accApiKeyId', acc.api_key_id || '');
  set('accApiKeyEnv', acc.api_key_env || 'YOUTUBE_Data_API_V3');
  await refreshApiKeySelectors();
  set('accApiKeySelect', acc.api_key_id || '');
  set('accMode', acc.fetch_mode); set('accLimit', acc.fetch_limit); set('accInterval', acc.scan_interval);
  set('accWebhook', acc.webhook_url || ''); set('accTelegramToken', acc.telegram_bot_token || ''); set('accDingtalkSecret', acc.dingtalk_sign_secret || '');
  set('accFeishuMode', acc.feishu_message_mode || 'card_json');
  set('accFeishuTemplateId', acc.feishu_template_id || '');
  set('accFeishuScanTemplateId', acc.feishu_scan_template_id || '');
  setCb('accEnabled', acc.enabled); setCb('accNotify', acc.notify_enabled); setCb('accProxyEnabled', !!acc.proxy_enabled);
  set('accDownloadProxyMode', acc.download_proxy_mode || 'auto');
  onAccountProxyModeChange();
  await refreshProxyPoolSelectors(acc.proxy_pool_id || '');
  selectPlatform(acc.notify_platform);
  await toggleProxySection();
  openModal('modalAccount');
}

export function onApiKeySelectChanged() {
  const sel = el('accApiKeySelect');
  const kid = el('accApiKeyId');
  if (sel && kid) kid.value = sel.value;
}

export async function toggleProxySection() {
  const toggle = el('accProxyEnabled');
  const sel = el('accProxyPoolSelect');
  if (!sel) return;
  const enabled = toggle ? toggle.checked : false;
  sel.disabled = !enabled;
  if (!enabled) {
    sel.value = '';
    sel.style.opacity = '0.4';
    sel.style.cursor = 'not-allowed';
  } else {
    sel.style.opacity = '';
    sel.style.cursor = '';
  }
}

// Proxy mode descriptions
export const PROXY_MODE_HELP = {
  'auto': I18n.t('account.proxyModeAuto'),
  'account_only': I18n.t('account.proxyModeAccountOnly'),
  'system_only': I18n.t('account.proxyModeSystemOnly'),
  'direct_only': I18n.t('account.proxyModeDirectOnly'),
};

export function onAccountProxyModeChange() {
  const modeEl = el('accDownloadProxyMode');
  const helpText = el('accProxyModeHelp');
  const proxyToggle = el('accProxyEnabled');
  const proxySelect = el('accProxyPoolSelect');

  if (helpText && modeEl) helpText.textContent = PROXY_MODE_HELP[modeEl.value] || '';
  if (!proxyToggle || !proxySelect) return;

  const mode = modeEl ? modeEl.value : 'auto';
  if (mode === 'account_only') {
    proxyToggle.checked = true;
    proxySelect.disabled = false;
    proxySelect.style.opacity = '';
    proxySelect.style.cursor = '';
    return;
  }
  if (mode === 'direct_only' || mode === 'system_only') {
    proxySelect.disabled = true;
    proxySelect.style.opacity = '0.4';
    proxySelect.style.cursor = 'not-allowed';
    return;
  }
  toggleProxySection();
}

export function onDynamicProxySettingChange() {
  // No-op: config modal saves on explicit button click
}

export async function previewAccountRouting() {
  const accIdVal = el('accId')?.value;
  if (!accIdVal) { toast(I18n.t('account.previewSaveFirst'), 'info'); return; }
  const accountId = parseInt(accIdVal, 10);
  const auto = 0;
  const cookies = (_gConfig && _gConfig.download_cookies_file) ? 1 : 0;
  const direct = el('accDownloadProxyMode')?.value === 'direct_only' ? 1 : 0;
  const res = await api('GET', '/routing-preview?account_id=' + accountId + '&auto=' + auto + '&cookies=' + cookies + '&direct=' + direct);
  if (res.error) { toast(res.error, 'err'); return; }
  const routing = res.routing || {};
  const sourceLabels = {
    account_static: I18n.t('account.routingAccountStatic'),
    system_paid: I18n.t('account.routingSystemPaid'),
    system_free: I18n.t('account.routingSystemFree'),
    direct: I18n.t('account.routingDirect'),
    failed: I18n.t('account.routingFailed'),
  };
  const box = el('routingPreviewBox');
  const mainEl = el('routingPreviewMain');
  if (!box || !mainEl) return;
  const mainText = sourceLabels[routing.resolved_proxy_source] || routing.resolved_proxy_source || I18n.t('account.routingUnknown');
  mainEl.textContent = mainText;
  if (routing.resolved_proxy_source === 'failed') mainEl.style.color = '#f87171';
  else if (routing.resolved_proxy_source === 'direct') mainEl.style.color = '#fbbf24';
  else mainEl.style.color = '#34d399';
  const meta = [];
  if (routing.provider_name) meta.push('<span class="routing-chip">' + esc(routing.provider_name) + '</span>');
  if (routing.provider_tier) meta.push('<span class="routing-chip">' + esc(routing.provider_tier) + '</span>');
  if (routing.session_mode) meta.push('<span class="routing-chip">' + esc(routing.session_mode) + '</span>');
  if (routing.masked_proxy_endpoint) meta.push('<span class="routing-chip">' + esc(routing.masked_proxy_endpoint) + '</span>');
  if (typeof routing.fallback_depth === 'number') meta.push('<span class="routing-chip">fallback #' + routing.fallback_depth + '</span>');
  const rpm = el('routingPreviewMeta'), rpr = el('routingPreviewReason'), rpw = el('routingPreviewWarnings');
  if (rpm) rpm.innerHTML = meta.join('');
  if (rpr) rpr.textContent = routing.reason || '—';
  if (rpw) rpw.textContent = routing.warnings && routing.warnings.length ? (I18n.t('account.routingWarning') + ' ' + routing.warnings.join(' · ')) : '';
  box.classList.add('show');
}

export async function refreshProxyPoolSelectors(selectedId) {
  const sel = el('accProxyPoolSelect');
  if (!sel) return;
  const pools = await api('GET', '/proxy-pools');
  const opts = ['<option value="">' + I18n.t('account.selectProxy') + '</option>'];
  if (pools && pools.length > 0) {
    pools.forEach(p => {
      const enabled = p.enabled ? '' : ' ' + I18n.t('account.proxyDisabledTag');
      opts.push('<option value="' + p.id + '">' + esc(p.name) + enabled + '</option>');
    });
  }
  sel.innerHTML = opts.join('');
  if (selectedId !== undefined) sel.value = selectedId;
}

export async function saveAccount() {
  if (!el('modalAccount')) return;
  const apiKeyIdVal = el('accApiKeyId')?.value ?? '';
  const api_key_id = apiKeyIdVal ? parseInt(apiKeyIdVal, 10) : null;
  const proxyPoolIdVal = document.getElementById('accProxyPoolSelect').value;
  const proxy_pool_id = proxyPoolIdVal ? parseInt(proxyPoolIdVal, 10) : null;
  const body = {
    id: parseInt(document.getElementById('accId').value, 10) || null,
    name: document.getElementById('accName').value.trim(),
    channel_url: document.getElementById('accChannel').value.trim(),
    api_key_env: document.getElementById('accApiKeyEnv').value.trim() || 'YOUTUBE_Data_API_V3',
    api_key_id: api_key_id,
    fetch_mode: document.getElementById('accMode').value,
    fetch_limit: parseInt(document.getElementById('accLimit').value, 10) || 5,
    scan_interval: parseInt(document.getElementById('accInterval').value, 10) || 5,
    notify_platform: document.getElementById('accPlatform').value,
    webhook_url: document.getElementById('accPlatform').value === 'telegram' ? null : document.getElementById('accWebhook').value.trim() || null,
    telegram_bot_token: document.getElementById('accTelegramToken').value.trim() || null,
    dingtalk_sign_secret: document.getElementById('accDingtalkSecret').value.trim() || null,
    feishu_message_mode: document.getElementById('accFeishuMode').value,
    feishu_template_id: document.getElementById('accFeishuTemplateId').value.trim() || null,
    feishu_scan_template_id: document.getElementById('accFeishuScanTemplateId').value.trim() || null,
    enabled: document.getElementById('accEnabled').checked,
    notify_enabled: document.getElementById('accNotify').checked,
    proxy_pool_id: proxy_pool_id,
    proxy_enabled: document.getElementById('accProxyEnabled').checked,
    download_proxy_mode: document.getElementById('accDownloadProxyMode').value,
  };
  if (!body.name || !body.channel_url) { toast(I18n.t('account.nameAndUrlRequired'), 'err'); return; }
  if (body.download_proxy_mode === 'account_only' && (!body.proxy_enabled || !body.proxy_pool_id)) {
    toast(I18n.t('account.accountOnlyProxyMustEnable'), 'err');
    return;
  }
  const r = await api('POST', '/accounts', body);
  if (r.error) { toast(r.error, 'err'); }
  else { toast(I18n.t('account.saved'), 'ok'); closeModal('modalAccount'); await refresh(); }
}

export async function deleteAccount(id) {
  const accounts = await api('GET', '/accounts');
  const acc = Array.isArray(accounts) && accounts.find(a => a.id === id);
  if (!acc) return toast(I18n.t('account.accountNotFound'), 'err');
  const ok = await showAppConfirm({
    title: I18n.t('account.deleteConfirmTitle').replace('{name}', acc.name),
    message: I18n.t('account.deleteConfirmMsg'),
    confirmText: I18n.t('account.btnDelete'),
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('DELETE', `/accounts/${id}`, {});
  if (r.error) toast(r.error, 'err');
  else { toast(I18n.t('account.deleted'), 'ok'); await refresh(); }
}

// ── Scan Now ─────────────────────────────────────────────────────────

function _isScanNowCoolingDown(accountId) {
  const until = _scanNowCooldown.get(accountId);
  if (until === undefined || Date.now() >= until) {
    _scanNowCooldown.delete(accountId);
    return false;
  }
  return true;
}

function _findScanNowBtn(accountId, fallbackBtn) {
  if (fallbackBtn && fallbackBtn.isConnected) return fallbackBtn;
  return document.querySelector(`[data-scan-now-id="${accountId}"]`);
}

function _updateScanNowBtn(accountId, fallbackBtn) {
  const btn = _findScanNowBtn(accountId, fallbackBtn);
  if (!btn) return;
  const submitting = _scanNowSubmitting && _pendingScanNow.accountId === accountId;
  btn.disabled = submitting || _isScanNowCoolingDown(accountId);
  btn.innerHTML = submitting
    ? '<span class="spinner"></span><span>' + I18n.t('account.scanning') + '</span>'
    : '<span>' + I18n.t('account.scanNow') + '</span>';
}

export function scanNow(id, btn) {
  const modal = el('modalScanConfirm');
  if (!modal || modal.classList.contains('show') || _scanNowSubmitting || _isScanNowCoolingDown(id)) return;
  setPendingScanNow({ accountId: id, button: btn || null });
  openModal('modalScanConfirm');
}

export async function confirmScanNow() {
  if (_scanNowSubmitting || !_pendingScanNow.accountId) return;
  setScanNowSubmitting(true);

  const accountId = _pendingScanNow.accountId;
  const btn = _pendingScanNow.button;
  const autoDl = el('scanNowAutoDownload')?.checked ?? true;

  closeScanConfirm(false);
  _updateScanNowBtn(accountId, btn);

  if (!accountId) { _resetScanNowState(); return; }

  try {
    const r = await api('POST', '/accounts/scan', {
      account_id: accountId,
      auto_download: autoDl
    });
    if (r && !r.error && r.ok !== false) {
      toast(I18n.t('account.scanTriggered') + (autoDl ? ' ' + I18n.t('account.autoDownloadIncluded') : ''), 'info');
    } else {
      toast((r && r.error) || I18n.t('account.scanTriggerFailed'), 'err');
    }
  } catch (e) {
    toast(I18n.t('account.networkError'), 'err');
  } finally {
    const restoreBtn = btn;
    _scanNowCooldown.set(accountId, Date.now() + SCAN_NOW_COOLDOWN_MS);
    _resetScanNowState();
    _updateScanNowBtn(accountId, restoreBtn);
    setTimeout(() => _updateScanNowBtn(accountId, restoreBtn), SCAN_NOW_COOLDOWN_MS);
  }
}

// ── API Key Selectors (shared) ───────────────────────────────────────
export async function refreshApiKeySelectors() {
  const keys = await api('GET', '/api-keys').catch(() => []);
  const opts = ['<option value="">' + I18n.t('account.apiKeyDefault') + '</option>'];
  keys.forEach(k => {
    opts.push(`<option value="${k.id}">${esc(k.name)} (${k.key_value})</option>`);
  });
  const sel = document.getElementById('accApiKeySelect');
  if (sel) sel.innerHTML = opts.join('');
  const cfgSel = document.getElementById('cfgDefaultApiKey');
  if (cfgSel) {
    const cfgOpts = ['<option value="">' + I18n.t('account.noDefaultKey') + '</option>'];
    keys.forEach(k => { cfgOpts.push(`<option value="${k.id}">${esc(k.name)}</option>`); });
    cfgSel.innerHTML = cfgOpts.join('');
  }
}

// Alias: refreshAccounts is loadAccounts (called from scheduler-panel re-render)
export { loadAccounts as refreshAccounts } from '../components/account-list.js';
