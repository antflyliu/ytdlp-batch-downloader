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
  const idx = p === 'feishu' ? 1 : p === 'dingtalk' ? 2 : 3;
  const btn = document.querySelector(`.platform-btn:nth-child(${idx})`);
  if (btn) btn.className = `platform-btn active-${p}`;
  accPlatform.value = p;
  const isFeishu = p === 'feishu';
  const ftc = el('feishuTemplateConfig');
  const dssg = el('dingtalkSignSecretGroup');
  if (ftc) ftc.style.display = isFeishu ? '' : 'none';
  if (dssg) dssg.style.display = p === 'dingtalk' ? '' : 'none';
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
    lastScan = latest && latest.last_scan_at ? fmtTime(latest.last_scan_at) : '从未';
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
      '扫描' + totalScanCount + '次' +
      (blockedScans > 0 ? ' · 已阻止' + blockedScans + '次' : '') +
      ' · ' + pct + '%' +
      ' · ' + quota.items.length + '个Key';
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
  mt.textContent = '添加监控账户';
  set('accId', ''); set('accName', ''); set('accChannel', '');
  set('accApiKeySelect', ''); set('accApiKeyId', '');
  set('accApiKeyEnv', 'YOUTUBE_Data_API_V3');
  set('accMode', 'playlist'); set('accLimit', '5'); set('accInterval', '5');
  set('accWebhook', ''); set('accDingtalkSecret', '');
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
  if (!acc) return toast('账户不存在', 'err');
  const set = (eid, v) => { const e = el(eid); if (e) e.value = v; };
  const setCb = (eid, v) => { const e = el(eid); if (e) e.checked = v; };
  mt.textContent = '编辑监控账户';
  set('accId', acc.id); set('accName', acc.name); set('accChannel', acc.channel_url);
  set('accApiKeyId', acc.api_key_id || '');
  set('accApiKeyEnv', acc.api_key_env || 'YOUTUBE_Data_API_V3');
  await refreshApiKeySelectors();
  set('accApiKeySelect', acc.api_key_id || '');
  set('accMode', acc.fetch_mode); set('accLimit', acc.fetch_limit); set('accInterval', acc.scan_interval);
  set('accWebhook', acc.webhook_url || ''); set('accDingtalkSecret', acc.dingtalk_sign_secret || '');
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
  'auto': '优先使用账户固定代理，不可用时回退到系统动态代理',
  'account_only': '只使用账户绑定的固定代理，不做系统回退',
  'system_only': '忽略账户固定代理，始终使用系统动态代理',
  'direct_only': '本账户下载不使用任何代理',
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
  if (!accIdVal) { toast('请先保存账户，再预览路由', 'info'); return; }
  const accountId = parseInt(accIdVal, 10);
  const auto = 0;
  const cookies = (_gConfig && _gConfig.download_cookies_file) ? 1 : 0;
  const direct = el('accDownloadProxyMode')?.value === 'direct_only' ? 1 : 0;
  const res = await api('GET', '/routing-preview?account_id=' + accountId + '&auto=' + auto + '&cookies=' + cookies + '&direct=' + direct);
  if (res.error) { toast(res.error, 'err'); return; }
  const routing = res.routing || {};
  const sourceLabels = {
    account_static: '账户固定代理',
    system_paid: '系统付费动态代理',
    system_free: '系统免费动态代理',
    direct: '直连',
    failed: '路由失败',
  };
  const box = el('routingPreviewBox');
  const mainEl = el('routingPreviewMain');
  if (!box || !mainEl) return;
  const mainText = sourceLabels[routing.resolved_proxy_source] || routing.resolved_proxy_source || '未知';
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
  if (rpw) rpw.textContent = routing.warnings && routing.warnings.length ? ('注意：' + routing.warnings.join(' · ')) : '';
  box.classList.add('show');
}

export async function refreshProxyPoolSelectors(selectedId) {
  const sel = el('accProxyPoolSelect');
  if (!sel) return;
  const pools = await api('GET', '/proxy-pools');
  const opts = ['<option value="">— 选择固定代理 —</option>'];
  if (pools && pools.length > 0) {
    pools.forEach(p => {
      const enabled = p.enabled ? '' : ' [禁用]';
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
    webhook_url: document.getElementById('accWebhook').value.trim() || null,
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
  if (!body.name || !body.channel_url) { toast('名称和频道 URL 不能为空', 'err'); return; }
  if (body.download_proxy_mode === 'account_only' && (!body.proxy_enabled || !body.proxy_pool_id)) {
    toast('"仅账户固定代理"模式必须启用并选择一个固定代理节点', 'err');
    return;
  }
  const r = await api('POST', '/accounts', body);
  if (r.error) { toast(r.error, 'err'); }
  else { toast('账户已保存', 'ok'); closeModal('modalAccount'); await refresh(); }
}

export async function deleteAccount(id) {
  const accounts = await api('GET', '/accounts');
  const acc = Array.isArray(accounts) && accounts.find(a => a.id === id);
  if (!acc) return toast('账户不存在', 'err');
  const ok = await showAppConfirm({
    title: `确定删除监控账户「${acc.name}」？`,
    message: '删除后将停止对该频道的扫描与通知，且无法恢复。',
    confirmText: '删除',
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('DELETE', `/accounts/${id}`, {});
  if (r.error) toast(r.error, 'err');
  else { toast('账户已删除', 'ok'); await refresh(); }
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
    ? '<span class="spinner"></span><span>扫描中</span>'
    : '<span>立即扫描</span>';
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
      toast('扫描已触发' + (autoDl ? '（含自动下载）' : ''), 'info');
    } else {
      toast((r && r.error) || '扫描触发失败', 'err');
    }
  } catch (e) {
    toast('网络错误', 'err');
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
  const opts = ['<option value="">— 使用系统默认 —</option>'];
  keys.forEach(k => {
    opts.push(`<option value="${k.id}">${esc(k.name)} (${k.key_value})</option>`);
  });
  const sel = document.getElementById('accApiKeySelect');
  if (sel) sel.innerHTML = opts.join('');
  const cfgSel = document.getElementById('cfgDefaultApiKey');
  if (cfgSel) {
    const cfgOpts = ['<option value="">— 无默认 Key（需手动指定）—</option>'];
    keys.forEach(k => { cfgOpts.push(`<option value="${k.id}">${esc(k.name)}</option>`); });
    cfgSel.innerHTML = cfgOpts.join('');
  }
}

// Alias: refreshAccounts is loadAccounts (called from scheduler-panel re-render)
export { loadAccounts as refreshAccounts } from '../components/account-list.js';
