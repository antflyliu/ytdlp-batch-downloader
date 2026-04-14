// ── Dynamic Provider Management ──────────────────────────────────────
// CRUD for proxy providers, scheduler controls, and provider detail views.

import { api } from '../api.js';
import { esc } from '../utils/format.js';
import { toast, openModal, closeModal } from './ui.js';
import { showAppConfirm } from './ui.js';

const el = (id) => document.getElementById(id);

// ── Dynamic Provider Management ─────────────────────────────────────

export async function openDynamicProviders() {
  openModal('modalDynamicProviders');
  await updateProviderSchedulerHint();
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function updateProviderSchedulerHint() {
  const hint = document.getElementById('dynSchedulerHint');
  const badge = document.getElementById('dynProviderSchedulerBadge');
  const nextRun = document.getElementById('dynProviderNextRun');
  const btn = document.getElementById('btnDynProviderSchedulerToggle');
  if (!hint || !badge || !nextRun || !btn) return;

  let status = null;
  try { status = await api('GET', '/provider-scheduler/status'); } catch (_) { status = null; }

  const running = !!(status && status.running && !status.error);
  const nextRuns = (status && Array.isArray(status.next_runs)) ? status.next_runs : [];
  if (running) {
    hint.textContent = 'Provider scheduler 运行中：将按下方各任务的下次时间执行列表拉取与候选清理';
    hint.style.color = '#b0aea5';
    badge.textContent = '运行中';
    badge.style.background = 'rgba(34,197,94,0.12)';
    badge.style.color = '#86efac';
    badge.style.borderColor = 'rgba(34,197,94,0.18)';
    if (nextRuns.length) {
      const maxShow = 12;
      const lines = nextRuns.slice(0, maxShow).map(j =>
        '<div style="font-size:10px;color:#a8a29e;margin-top:3px;line-height:1.35">' +
        esc(j.name || j.id || '') + ' · <span style="color:#d6d3d1">' + esc(j.next_run || '—') + '</span></div>'
      ).join('');
      const more = nextRuns.length > maxShow
        ? '<div style="font-size:10px;color:#6b6a63;margin-top:4px">… 共 ' + nextRuns.length + ' 个已注册任务</div>'
        : '';
      nextRun.innerHTML = '<div style="font-size:11px;color:#87867f;margin-bottom:4px">已注册任务与下次执行</div>' + lines + more;
    } else {
      nextRun.textContent = '已启动，但未返回任务列表（可尝试重载动态代理任务）';
    }
    btn.textContent = '停止动态代理调度';
  } else {
    hint.textContent = 'Provider scheduler 未运行：不会按「刷新间隔」自动拉列表';
    hint.style.color = '#b0aea5';
    badge.textContent = '未启动';
    badge.style.background = 'rgba(201,100,66,0.12)';
    badge.style.color = '#d97757';
    badge.style.borderColor = 'rgba(201,100,66,0.18)';
    nextRun.innerHTML =
      '<div style="font-size:11px;color:#87867f;line-height:1.55">请先点击右侧 <strong style="color:#d6d3d1">启动动态代理调度</strong>。</div>' +
      '<div style="font-size:10px;color:#6b6a63;line-height:1.55;margin-top:8px">启用 list_api / public_feed 后，在编辑提供方里把 <strong style="color:#a8a29e">刷新间隔（分钟）</strong> 设为大于 0 并保存；启动后若仍无定时拉取，可点 <strong style="color:#a8a29e">重载动态代理任务</strong>。</div>';
    btn.textContent = '启动动态代理调度';
  }
}

export async function loadProviderSchedulerLogs() {
  const shell = el('dynProviderSchedulerLogs');
  const filter = el('dynProviderLogFilter');
  if (!shell) return;

  let rows = [];
  try { rows = await api('GET', '/provider-scheduler/logs'); } catch (_) { rows = []; }
  if (!Array.isArray(rows)) rows = [];

  const mode = filter ? filter.value : 'all';
  const filtered = rows.filter(r => {
    if (mode === 'refresh') return r.job_type === 'refresh';
    if (mode === 'cleanup') return r.job_type === 'cleanup';
    if (mode === 'error') return r.status === 'error';
    return true;
  });
  if (!filtered || filtered.length === 0) {
    shell.innerHTML = '<div style="font-size:12px;color:#87867f">当前筛选条件下暂无 provider 调度记录</div>';
    return;
  }
  shell.innerHTML = filtered.slice(0, 6).map(r => {
    const tone = r.status === 'success' ? '#86efac' : r.status === 'error' ? '#fca5a5' : '#f5d0fe';
    const bg = r.status === 'success' ? 'rgba(34,197,94,0.08)' : r.status === 'error' ? 'rgba(239,68,68,0.08)' : 'rgba(168,85,247,0.08)';
    const title = r.provider_name ? `${r.provider_name} · ${r.job_type}` : `system · ${r.job_type}`;
    const summary = r.job_type === 'refresh'
      ? `raw ${r.raw_count || 0} / valid ${r.valid_count || 0}`
      : (r.message || 'completed');
    return `<div style="background:${bg};border:1px solid rgba(135,134,127,0.14);border-radius:14px;padding:10px 12px">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:4px">
        <div style="font-size:12px;color:#f5f4ed">${esc(title)}</div>
        <div style="font-size:10px;color:${tone}">${esc(r.status || 'unknown')}</div>
      </div>
      <div style="font-size:11px;color:#b0aea5;line-height:1.55">${esc(summary)}</div>
      <div style="font-size:10px;color:#87867f;margin-top:4px">${esc(r.started_at || '')}</div>
    </div>`;
  }).join('');
}

export async function loadDynamicProviderTable() {
  const tbody = el('dynProviderTableBody');
  const empty = el('dynEmptyState');
  const shell = document.querySelector('#modalDynamicProviders .dyn-table-shell');
  if (!tbody || !empty) return;

  function showDynEmptyDefaults() {
    if (!empty) return;
    const titleEl = empty.querySelector('.dyn-empty-title');
    const descEl = empty.querySelector('.dyn-empty-desc');
    const ctaEl = empty.querySelector('.dyn-empty-cta');
    if (titleEl) titleEl.textContent = '还没有配置动态代理提供方';
    if (descEl) descEl.textContent = '添加一个提供方后，它将参与系统动态代理路由决策。付费提供方优先，免费提供方兜底。';
    if (ctaEl) ctaEl.style.display = '';
  }

  function showDynLoadError(errMsg) {
    if (!empty) return;
    const titleEl = empty.querySelector('.dyn-empty-title');
    const descEl = empty.querySelector('.dyn-empty-desc');
    const ctaEl = empty.querySelector('.dyn-empty-cta');
    if (titleEl) titleEl.textContent = '加载失败';
    if (descEl) descEl.textContent = errMsg;
    if (ctaEl) ctaEl.style.display = 'none';
  }

  let providers;
  try { providers = await api('GET', '/dynamic-providers'); } catch (_) { providers = null; }

  if (!Array.isArray(providers)) {
    const raw = providers && typeof providers === 'object' && providers !== null ? providers.error : undefined;
    const errMsg = raw != null && String(raw).trim() ? String(raw).trim() : '无法解析提供方列表（请检查网络或 Token）';
    toast('加载动态代理提供方失败：' + errMsg, 'err');
    tbody.innerHTML = '';
    empty.style.display = '';
    if (shell) shell.style.display = 'none';
    showDynLoadError(errMsg);
    return;
  }

  if (!providers || providers.length === 0) {
    showDynEmptyDefaults();
    tbody.innerHTML = '';
    empty.style.display = '';
    if (shell) shell.style.display = 'none';
    return;
  }

  if (shell) shell.style.display = '';
  empty.style.display = 'none';

  let sched = null, logs = [];
  try { [sched, logs] = await Promise.all([api('GET', '/provider-scheduler/status'), api('GET', '/provider-scheduler/logs')]); }
  catch (_) { sched = null; logs = []; }
  if (!Array.isArray(logs)) logs = [];
  const nextRunsList = sched && Array.isArray(sched.next_runs) ? sched.next_runs : [];

  const nextRunMap = {};
  nextRunsList.forEach(j => {
    const m = /^provider_refresh_(\d+)$/.exec(j.id || '');
    if (m) nextRunMap[m[1]] = j.next_run;
  });
  const lastRefreshMap = {};
  logs.forEach(r => {
    if (r.job_type !== 'refresh' || !r.provider_id) return;
    if (!lastRefreshMap[r.provider_id]) lastRefreshMap[r.provider_id] = r;
  });

  tbody.innerHTML = providers.map(p => {
    const health = p.last_health_status || '';
    const healthClass = health === 'healthy' ? 'dyn-status-healthy' : health === 'degraded' ? 'dyn-status-degraded' : health === 'down' ? 'dyn-status-down' : 'dyn-status-unknown';
    const healthDotClass = health === 'healthy' ? 'on' : p.is_in_cooldown ? 'cooldown' : health === 'degraded' ? 'cooldown' : health === 'down' ? 'off' : 'off';
    const healthLabel = health === 'healthy' ? '健康' : health === 'degraded' ? '降级' : health === 'down' ? '不可用' : '未知';
    const tierChip = p.billing_tier === 'paid'
      ? '<span class="dyn-chip dyn-chip-paid">付费</span>'
      : '<span class="dyn-chip dyn-chip-free">免费</span>';
    const caps = [];
    if (p.supports_auto_download) caps.push('<span class="dyn-chip" style="background:rgba(34,197,94,0.08);border-color:rgba(34,197,94,0.2);color:#22c55e">自动下载</span>');
    if (p.supports_cookies) caps.push('<span class="dyn-chip" style="background:rgba(59,130,246,0.08);border-color:rgba(59,130,246,0.2);color:#3b82f6">Cookie</span>');
    if (p.supports_sticky_session) caps.push('<span class="dyn-chip" style="background:rgba(168,85,247,0.08);border-color:rgba(168,85,247,0.2);color:#a855f7">粘性</span>');
    const cooldownBadge = p.is_in_cooldown ? '<span class="dyn-badge">冷却中</span>' : '';
    const nextRun = nextRunMap[String(p.id)] || null;
    const lastRefresh = lastRefreshMap[p.id] || null;
    const schedulerMeta = (nextRun || lastRefresh)
      ? '<div style="margin-top:5px;font-size:10px;color:#87867f;line-height:1.5">' +
          (nextRun ? ('下次: ' + esc(nextRun)) : '下次: —') +
          (lastRefresh ? ('<br>上次刷新: ' + esc(lastRefresh.started_at || '') + ' · raw ' + (lastRefresh.raw_count || 0) + ' / valid ' + (lastRefresh.valid_count || 0)) : '') +
        '</div>'
      : '';
    return '<tr>' +
      '<td class="mono-cell" style="color:var(--dyn-text)">' + p.id + '</td>' +
      '<td class="name-cell">' + esc(p.name) + schedulerMeta + '</td>' +
      '<td>' + tierChip + '</td>' +
      '<td class="mono-cell">' + esc(p.adapter_type) + '</td>' +
      '<td>' +
        '<div style="display:flex;align-items:center;gap:5px">' +
          '<span class="dyn-dot ' + healthDotClass + '"></span>' +
          '<span class="dyn-status-text ' + healthClass + '">' + healthLabel + cooldownBadge + '</span>' +
        '</div>' +
        (p.last_error_message ? '<div style="font-size:10px;color:#ef4444;margin-top:2px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(p.last_error_message) + '">' + esc(p.last_error_message) + '</div>' : '') +
      '</td>' +
      '<td class="mono-cell">' + p.priority + '</td>' +
      '<td><div class="chip-cell">' + caps.join('') + '</div></td>' +
      '<td>' +
        '<div class="dyn-actions">' +
          '<button class="btn-sm" onclick="window.openEditDynamicProvider(' + p.id + ')">编辑</button>' +
          '<button class="btn-sm ' + (p.enabled ? 'warning' : 'success') + '" onclick="window.toggleDynamicProvider(' + p.id + ', ' + (!p.enabled) + ')">' + (p.enabled ? '禁用' : '启用') + '</button>' +
          '<button class="btn-sm" onclick="window.healthCheckDynamicProvider(' + p.id + ')">检查</button>' +
          '<button class="btn-sm" onclick="window.refreshDynamicProvider(' + p.id + ')">刷新</button>' +
          '<button class="btn-sm" onclick="window.previewCandidatesDynamicProvider(' + p.id + ')">预览</button>' +
          '<button class="btn-sm" onclick="window.openDynamicProviderDetail(' + p.id + ')">详情</button>' +
          (p.is_in_cooldown ? '<button class="btn-sm success" onclick="window.clearCooldownDynamicProvider(' + p.id + ')">解除冷却</button>' : '') +
          '<button class="btn-sm danger" onclick="window.deleteDynamicProvider(' + p.id + ')">删除</button>' +
        '</div>' +
      '</td>' +
    '</tr>';
  }).join('');
}

// ── Form helpers ─────────────────────────────────────────────────────

export function onDynAdapterTypeChange() {
  const type = el('dynAdapterType')?.value;
  const gw = el('dynGatewayConfig');
  const local = el('dynLocalConfig');
  const api = el('dynListApiConfig');
  if (!type || !gw || !local || !api) return;
  gw.style.display = type === 'rotating_gateway' ? '' : 'none';
  local.style.display = type === 'local_gateway' ? '' : 'none';
  api.style.display = (type === 'list_api' || type === 'public_feed') ? '' : 'none';
}

export function onDynListApiAuthToggle() {
  const checkbox = el('dynListApiHasAuth');
  const fields = el('dynListApiAuthFields');
  if (!checkbox || !fields) return;
  fields.style.display = checkbox.checked ? '' : 'none';
}

export function onDynListApiAdvToggle() {
  const adv = el('dynListApiAdvFields');
  if (!adv) return;
  const cur = adv.style.display;
  adv.style.display = cur === 'none' ? '' : 'none';
  const trigger = document.querySelector('#dynListApiAdvSection .dyn-adv-trigger');
  if (trigger) trigger.textContent = cur === 'none' ? '高级字段映射 ▴' : '高级字段映射 ▾';
}

export function onDynBillingTierChange() {
  const tier = el('dynBillingTier');
  const risk = el('dynRiskLevel');
  if (!tier || !risk) return;
  if (tier.value === 'free') risk.value = 'medium';
}

export function openAddDynamicProvider() {
  if (!el('dynFormTitle') || !el('modalDynamicProviderForm')) return;
  el('dynFormTitle').textContent = '添加动态代理提供方';
  el('dynId').value = '';
  el('dynName').value = '';
  el('dynBillingTier').value = 'paid';
  el('dynAdapterType').value = 'rotating_gateway';
  el('dynPriority').value = '100';
  el('dynRiskLevel').value = 'medium';
  el('dynGatewayHost').value = '';
  el('dynGatewayPort').value = '';
  el('dynProtocol').value = 'http';
  el('dynUsername').value = '';
  el('dynPassword').value = '';
  el('dynLocalProxyUrl').value = '';
  el('dynSupportsAutoDownload').checked = true;
  el('dynSupportsCookies').checked = false;
  el('dynSupportsCountryFilter').checked = false;
  el('dynSupportsStickySession').checked = true;
  el('dynEnabled').checked = true;
  el('dynNotes').value = '';
  el('dynListApiAdapterName').value = 'geonode';
  onDynAdapterTypeChange();
  openModal('modalDynamicProviderForm');
}

export async function openEditDynamicProvider(id) {
  if (!el('dynFormTitle') || !el('modalDynamicProviderForm')) return;
  const providers = await api('GET', '/dynamic-providers');
  const p = providers && providers.find(x => x.id === id);
  if (!p) return toast('提供方不存在', 'err');
  el('dynFormTitle').textContent = '编辑动态代理提供方';
  el('dynId').value = p.id;
  el('dynName').value = p.name || '';
  el('dynBillingTier').value = p.billing_tier || 'free';
  el('dynAdapterType').value = p.adapter_type || 'rotating_gateway';
  el('dynPriority').value = p.priority || 100;
  el('dynRiskLevel').value = p.risk_level || 'medium';
  el('dynSupportsAutoDownload').checked = !!p.supports_auto_download;
  el('dynSupportsCookies').checked = !!p.supports_cookies;
  el('dynSupportsCountryFilter').checked = !!p.supports_country_filter;
  el('dynSupportsStickySession').checked = !!p.supports_sticky_session;
  el('dynEnabled').checked = !!p.enabled;
  el('dynNotes').value = p.notes || '';
  el('dynRefreshInterval').value = p.refresh_interval_minutes || 0;
  const cfg = p.config_json || {};
  el('dynListApiAdapterName').value = (cfg.adapter_name || '').trim();
  el('dynListApiBaseUrl').value = cfg.base_url || '';
  el('dynListApiLimit').value = cfg.limit || 50;
  el('dynListApiItemsPath').value = cfg.items_path || '';
  el('dynListApiCountry').value = cfg.country || '';
  el('dynListApiProtocol').value = cfg.protocol || '';
  const hasAuth = !!(cfg.username);
  el('dynListApiHasAuth').checked = hasAuth;
  el('dynListApiAuthFields').style.display = hasAuth ? '' : 'none';
  el('dynListApiUsername').value = cfg.username || '';
  const fm = cfg.field_mapping || {};
  el('dynListApiHostField').value = (fm.host && fm.host[0]) || 'ip';
  el('dynListApiPortField').value = (fm.port && fm.port[0]) || 'port';
  el('dynListApiProtocolField').value = (fm.protocol && fm.protocol.length)
    ? fm.protocol.join(',')
    : 'protocols';
  el('dynGatewayHost').value = cfg.gateway_host || '';
  el('dynGatewayPort').value = cfg.gateway_port || '';
  el('dynProtocol').value = cfg.protocol || 'http';
  el('dynUsername').value = cfg.username || '';
  el('dynPassword').value = cfg.password ? '***' : '';
  el('dynLocalProxyUrl').value = cfg.local_proxy_url || '';
  onDynAdapterTypeChange();
  openModal('modalDynamicProviderForm');
}

export function _buildDynConfigJson() {
  const adapter = document.getElementById('dynAdapterType').value;
  const cfg = {};
  if (adapter === 'rotating_gateway') {
    const host = document.getElementById('dynGatewayHost').value.trim();
    const port = document.getElementById('dynGatewayPort').value.trim();
    if (!host || !port) { toast('网关地址和端口不能为空', 'err'); return null; }
    cfg.gateway_host = host;
    cfg.gateway_port = parseInt(port, 10);
    cfg.protocol = document.getElementById('dynProtocol').value;
    const uname = document.getElementById('dynUsername').value.trim();
    const pwd = document.getElementById('dynPassword').value;
    if (uname) cfg.username = uname;
    if (pwd) cfg.password = pwd;
  } else if (adapter === 'local_gateway') {
    const url = document.getElementById('dynLocalProxyUrl').value.trim();
    if (!url) { toast('本地代理地址不能为空', 'err'); return null; }
    cfg.local_proxy_url = url;
  } else if (adapter === 'list_api' || adapter === 'public_feed') {
    const baseUrl = document.getElementById('dynListApiBaseUrl').value.trim();
    if (!baseUrl) { toast('API 地址不能为空', 'err'); return null; }
    cfg.base_url = baseUrl;
    const listAdapter = document.getElementById('dynListApiAdapterName').value.trim();
    if (listAdapter) cfg.adapter_name = listAdapter;
    const limit = parseInt(document.getElementById('dynListApiLimit').value, 10) || 50;
    if (limit > 0) cfg.limit = limit;
    const itemsPath = document.getElementById('dynListApiItemsPath').value.trim();
    if (itemsPath) cfg.items_path = itemsPath;
    const country = document.getElementById('dynListApiCountry').value.trim();
    if (country) cfg.country = country;
    const proto = document.getElementById('dynListApiProtocol').value;
    if (proto) cfg.protocol = proto;
    if (document.getElementById('dynListApiHasAuth').checked) {
      const u = document.getElementById('dynListApiUsername').value.trim();
      const p = document.getElementById('dynListApiPassword').value;
      if (u) cfg.username = u;
      if (p) cfg.password = p;
    }
    cfg.field_mapping = {};
    const hf = document.getElementById('dynListApiHostField').value.trim();
    const pf = document.getElementById('dynListApiPortField').value.trim();
    const rf = document.getElementById('dynListApiProtocolField').value.trim();
    if (hf) cfg.field_mapping.host = [hf];
    if (pf) cfg.field_mapping.port = [pf];
    if (rf) cfg.field_mapping.protocol = rf.split(',').map((s) => s.trim()).filter(Boolean);
  }
  return cfg;
}

export async function saveDynamicProvider() {
  const form = el('modalDynamicProviderForm');
  if (!form) return;
  const idEl = el('dynId');
  const nameEl = el('dynName');
  const billingTier = el('dynBillingTier');
  const adapterType = el('dynAdapterType');
  const priority = el('dynPriority');
  const riskLevel = el('dynRiskLevel');
  const autoDownload = el('dynSupportsAutoDownload');
  const cookies = el('dynSupportsCookies');
  const countryFilter = el('dynSupportsCountryFilter');
  const sticky = el('dynSupportsStickySession');
  const enabled = el('dynEnabled');
  const notes = el('dynNotes');
  const refreshInterval = el('dynRefreshInterval');
  if (!idEl || !nameEl || !billingTier || !adapterType || !priority || !riskLevel ||
      !autoDownload || !cookies || !countryFilter || !sticky || !enabled || !notes || !refreshInterval) {
    return;
  }
  const id = idEl.value;
  const name = nameEl.value.trim();
  if (!name) { toast('提供方名称不能为空', 'err'); return; }
  const cfg = _buildDynConfigJson();
  if (cfg === null) return;
  const body = {
    name,
    billing_tier: billingTier.value,
    adapter_type: adapterType.value,
    priority: parseInt(priority.value, 10) || 100,
    risk_level: riskLevel.value,
    config_json: cfg,
    supports_auto_download: autoDownload.checked,
    supports_cookies: cookies.checked,
    supports_country_filter: countryFilter.checked,
    supports_sticky_session: sticky.checked,
    enabled: enabled.checked,
    notes: notes.value.trim() || null,
    refresh_interval_minutes: parseInt(refreshInterval.value, 10) || 0,
  };
  let r;
  if (id) r = await api('POST', '/dynamic-providers/' + id + '/update', body);
  else r = await api('POST', '/dynamic-providers', body);
  if (r.error) { toast(r.error || '保存失败', 'err'); return; }
  toast(id ? '提供方已更新' : '提供方已添加', 'ok');
  closeModal('modalDynamicProviderForm');
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function toggleDynamicProvider(id, enabled) {
  const r = await api('POST', '/dynamic-providers/' + id + '/update', { enabled });
  if (r.error) { toast(r.error, 'err'); return; }
  toast(enabled ? '提供方已启用' : '提供方已禁用', 'ok');
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function deleteDynamicProvider(id) {
  const providers = await api('GET', '/dynamic-providers');
  if (!Array.isArray(providers)) { toast((providers && providers.error) ? String(providers.error) : '无法加载提供方列表', 'err'); return; }
  const p = providers.find(x => x.id === id);
  if (!p) return toast('提供方不存在', 'err');
  const ok = await showAppConfirm({
    title: '确定删除提供方「' + p.name + '」？',
    message: '删除后它将不再参与路由决策。',
    confirmText: '删除',
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('DELETE', '/dynamic-providers/' + id);
  if (r.error) { toast(r.error, 'err'); return; }
  toast('已删除', 'ok');
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function healthCheckDynamicProvider(id) {
  const r = await api('POST', '/dynamic-providers/' + id + '/health-check', {});
  if (r.error) { toast(r.error, 'err'); }
  else {
    const latency = r.latency_ms >= 0 ? r.latency_ms + 'ms' : '-';
    const err = r.error_message ? ' | ' + r.error_message : '';
    toast('健康检查: ' + (r.status || 'healthy') + ' (' + latency + ')' + err, r.status === 'healthy' ? 'ok' : 'warn');
  }
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function clearCooldownDynamicProvider(id) {
  const r = await api('POST', '/dynamic-providers/' + id + '/cooldown/clear', {});
  if (r.error) { toast(r.error, 'err'); return; }
  toast('冷却已解除', 'ok');
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function refreshDynamicProvider(id) {
  const r = await api('POST', '/dynamic-providers/' + id + '/refresh', {});
  if (r.error) { toast('刷新失败: ' + r.error, 'err'); return; }
  const raw = r.raw_count || 0;
  const valid = r.valid_count || 0;
  const top = r.top_candidate;
  const msg = top
    ? '刷新完成，拉取' + raw + '个候选，入池' + valid + '个，健康=' + (top.last_probe_status || '-')
    : '刷新完成，拉取' + raw + '个候选，入池' + valid + '个';
  toast(msg, 'ok');
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
  await window.openDynamicProviderDetail(id);
}

export async function previewCandidatesDynamicProvider(id) {
  const r = await api('GET', '/dynamic-providers/' + id + '/candidates/preview');
  if (!r || r.error || r._fetchFailed) { toast('预览失败: ' + (r.error || '未知'), 'err'); return; }
  const total = r.total_count || 0;
  const sc = r.status_counts || {};
  const healthy = sc.healthy || 0;
  const down = sc.down || 0;
  const degraded = sc.degraded || 0;
  const top = r.top_candidate;
  const topInfo = top ? ' | 当前最优: ' + (top.masked_proxy_endpoint || '-') + ' (' + (top.last_probe_status || '-') + ')' : '';
  toast('候选总计' + total + '个，健康=' + healthy + '|降级=' + degraded + '|不可用=' + down + topInfo, 'ok');
}

// ── Provider Detail Drawer ───────────────────────────────────────────

export async function openDynamicProviderDetail(id) {
  const drawer = document.getElementById('dynProviderDetailDrawer');
  const body = document.getElementById('dynProviderDetailBody');
  const errBox = document.getElementById('dynProviderDetailError');
  const previewBox = document.getElementById('dynProviderDetailPreviewSummary');
  const failureBox = document.getElementById('dynProviderDetailFailures');
  if (!drawer || !body || !errBox || !previewBox || !failureBox) return;
  drawer.style.display = '';
  drawer.classList.add('show');
  errBox.style.display = 'none';
  errBox.textContent = '';
  previewBox.style.display = 'none';
  previewBox.textContent = '';
  failureBox.style.display = 'none';
  failureBox.textContent = '';
  body.innerHTML = '<div style="font-size:12px;color:#b0aea5">加载中...</div>';

  const [providers, logs, preview] = await Promise.all([
    api('GET', '/dynamic-providers'),
    api('GET', '/provider-scheduler/logs'),
    api('GET', '/dynamic-providers/' + id + '/candidates/preview'),
  ]);
  const netErr = [providers, logs, preview].find(x => x && x._fetchFailed);
  if (netErr) {
    body.innerHTML = '<div style="font-size:12px;color:#fca5a5;line-height:1.6">' + esc(netErr.error || '请求失败') + '</div>';
    return;
  }
  const providerList = Array.isArray(providers) ? providers : [];
  const logList = Array.isArray(logs) ? logs : [];
  const p = providerList.find(x => String(x.id) === String(id));
  if (!p) { body.innerHTML = '<div style="font-size:12px;color:#fca5a5">提供方不存在</div>'; return; }
  const rows = logList.filter(r => String(r.provider_id) === String(id)).slice(0, 8);
  const latest = rows.length ? rows[0] : null;
  const failureRows = rows.filter(r => r.status === 'error' || (r.message && r.message !== 'ok')).slice(0, 5);
  if (p.last_error_message || failureRows.length) {
    errBox.style.display = '';
    errBox.innerHTML = '<strong style="display:block;margin-bottom:4px;color:#fda4af">最近错误</strong>' +
      esc((failureRows[0] && failureRows[0].message) || p.last_error_message || '未知错误');
  }
if (failureRows.length) {
    failureBox.style.display = '';
    failureBox.dataset.expanded = 'false';
    const toggle = el('dynProviderDetailFailuresToggle');
    if (toggle) toggle.textContent = failureRows.length > 2 ? '展开' : '收起';
    const list = el('dynProviderDetailFailuresList');
    if (list) {
      list.innerHTML = failureRows.slice(0, 2).map(r => '<div style="padding-top:6px;border-top:1px solid rgba(250,204,21,0.10)"><span style="color:#f5f4ed">' + esc(r.job_type || '-') + '</span> · ' + esc(r.started_at || '') + '<br>' + esc(r.message || r.status || 'error') + '</div>').join('');
      list.dataset.full = JSON.stringify(failureRows.map(r => ({job_type: r.job_type || '-', started_at: r.started_at || '', message: r.message || r.status || 'error'})));
    }
  }
  if (preview && !preview.error) {
    const sc = preview.status_counts || {};
    previewBox.style.display = '';
    previewBox.innerHTML = '<strong style="display:block;margin-bottom:4px;color:#f5f4ed">候选预览摘要</strong>' +
      '总数 ' + esc(preview.total_count || 0) + ' · healthy ' + esc(sc.healthy || 0) +
      ' · degraded ' + esc(sc.degraded || 0) + ' · down ' + esc(sc.down || 0);
  }
  const actionBar = document.getElementById('dynProviderDetailActions');
  if (actionBar) {
    actionBar.innerHTML = `
      <button class="btn-sm" onclick="window.refreshDynamicProviderDetail(${id})">刷新当前提供方</button>
      <button class="btn-sm" onclick="window.previewCandidatesDynamicProvider(${id})">候选预览</button>
      <button class="btn-sm" onclick="window.healthCheckDynamicProviderDetail(${id})">健康检查</button>
      ${p.is_in_cooldown ? `<button class="btn-sm success" onclick="window.clearCooldownDynamicProviderDetail(${id})">解除冷却</button>` : ''}
    `;
  }
  body.innerHTML = `
    <div style="display:grid;gap:14px">
      <div style="padding:14px 16px;border:1px solid rgba(232,230,220,0.10);border-radius:18px;background:rgba(18,21,35,0.58)">
        <div style="font-family:Georgia,serif;font-size:22px;line-height:1.2;color:#f5f4ed;margin-bottom:6px">${esc(p.name || '-')}</div>
        <div style="font-size:12px;color:#b0aea5;line-height:1.65">适配器 ${esc(p.adapter_type || '-')} · 优先级 ${esc(p.priority || '-')} · 刷新间隔 ${esc(p.refresh_interval_minutes || 0)} 分钟</div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px">
        <div style="padding:12px 14px;border-radius:16px;background:rgba(18,21,35,0.58);border:1px solid rgba(232,230,220,0.10)">
          <div style="font-size:11px;color:#87867f;text-transform:uppercase;letter-spacing:.06em">最新 raw</div>
          <div style="font-family:Georgia,serif;font-size:24px;color:#f5f4ed;margin-top:4px">${latest ? esc(latest.raw_count || 0) : '—'}</div>
        </div>
        <div style="padding:12px 14px;border-radius:16px;background:rgba(18,21,35,0.58);border:1px solid rgba(232,230,220,0.10)">
          <div style="font-size:11px;color:#87867f;text-transform:uppercase;letter-spacing:.06em">最新 valid</div>
          <div style="font-family:Georgia,serif;font-size:24px;color:#f5f4ed;margin-top:4px">${latest ? esc(latest.valid_count || 0) : '—'}</div>
        </div>
        <div style="padding:12px 14px;border-radius:16px;background:rgba(18,21,35,0.58);border:1px solid rgba(232,230,220,0.10)">
          <div style="font-size:11px;color:#87867f;text-transform:uppercase;letter-spacing:.06em">最新状态</div>
          <div style="font-family:Georgia,serif;font-size:24px;color:#f5f4ed;margin-top:4px">${latest ? esc(latest.status || '-') : '—'}</div>
        </div>
      </div>
      <div style="padding:14px 16px;border:1px solid rgba(232,230,220,0.10);border-radius:18px;background:rgba(18,21,35,0.58)">
        <div style="font-family:Georgia,serif;font-size:18px;line-height:1.2;color:#f5f4ed;margin-bottom:10px">最近执行历史</div>
        <div style="display:grid;gap:8px">
          ${rows.length ? rows.map(r => `
            <div style="border:1px solid rgba(232,230,220,0.08);border-radius:14px;padding:10px 12px;background:${r.status === 'success' ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)'}">
              <div style="display:flex;justify-content:space-between;gap:10px;margin-bottom:4px">
                <div style="font-size:12px;color:#f5f4ed">${esc(r.job_type || '-')}</div>
                <div style="font-size:10px;color:${r.status === 'success' ? '#86efac' : '#fca5a5'}">${esc(r.status || '-')}</div>
              </div>
              <div style="font-size:11px;color:#b0aea5;line-height:1.55">raw ${esc(r.raw_count || 0)} / valid ${esc(r.valid_count || 0)} · ${esc(r.started_at || '')}</div>
            </div>
          `).join('') : '<div style="font-size:12px;color:#87867f">暂无该提供方的调度历史</div>'}
        </div>
      </div>
    </div>`;
}

export async function refreshDynamicProviderDetail(id) {
  try { await window.refreshDynamicProvider(id); await window.openDynamicProviderDetail(id); }
  catch (e) { toast('刷新异常: ' + ((e && e.message) || e), 'err'); }
}

export async function healthCheckDynamicProviderDetail(id) {
  try { await window.healthCheckDynamicProvider(id); await window.openDynamicProviderDetail(id); }
  catch (e) { toast('健康检查异常: ' + ((e && e.message) || e), 'err'); }
}

export async function clearCooldownDynamicProviderDetail(id) {
  try { await window.clearCooldownDynamicProvider(id); await window.openDynamicProviderDetail(id); }
  catch (e) { toast('操作异常: ' + ((e && e.message) || e), 'err'); }
}

export function toggleProviderFailureList() {
  const box = el('dynProviderDetailFailures');
  const list = el('dynProviderDetailFailuresList');
  const toggle = el('dynProviderDetailFailuresToggle');
  if (!box || !list || !toggle) return;
  const full = JSON.parse(list.dataset.full || '[]');
  const expanded = box.dataset.expanded === 'true';
  const rows = expanded ? full.slice(0, 2) : full;
  list.innerHTML = rows.map(r => '<div style="padding-top:6px;border-top:1px solid rgba(250,204,21,0.10)"><span style="color:#f5f4ed">' + esc(r.job_type || '-') + '</span> · ' + esc(r.started_at || '') + '<br>' + esc(r.message || 'error') + '</div>').join('');
  box.dataset.expanded = expanded ? 'false' : 'true';
  toggle.textContent = expanded ? '展开' : '收起';
}

export function closeDynamicProviderDetail() {
  const drawer = el('dynProviderDetailDrawer');
  if (drawer) { drawer.classList.remove('show'); drawer.style.display = 'none'; }
}

export async function healthCheckAllProviders() {
  const providers = await api('GET', '/dynamic-providers');
  if (!providers || providers.length === 0) { toast('没有提供方', 'info'); return; }
  toast('开始全量健康检查 (' + providers.length + ' 个)…', 'info');
  for (let i = 0; i < providers.length; i++) {
    await api('POST', '/dynamic-providers/' + providers[i].id + '/health-check', {});
    if (i % 3 === 2 || i === providers.length - 1) await window.loadDynamicProviderTable();
  }
  toast('全量健康检查完成 (' + providers.length + ' 个)', 'ok');
}
