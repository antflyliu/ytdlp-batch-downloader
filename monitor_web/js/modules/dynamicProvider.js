// ── Dynamic Provider Management ──────────────────────────────────────
// CRUD for proxy providers, scheduler controls, and provider detail views.

import { api } from '../api.js';
import { esc } from '../utils/format.js';
import { toast, openModal, closeModal } from './ui.js';

/** 页面与弹层各有一套表格节点（避免 duplicate id 只命中其一） */
function dynTableTargets() {
  return {
    tbodyPage: document.querySelector('#page-dynamic-providers #dynProviderTableBody'),
    tbodyModal: document.querySelector('#modalDynamicProviders #dynProviderTableBody'),
    emptyPage: document.querySelector('#page-dynamic-providers #dynEmptyState'),
    emptyModal: document.querySelector('#modalDynamicProviders #dynEmptyState'),
    shellPage: document.querySelector('#page-dynamic-providers .table-wrap'),
    shellModal: document.querySelector('#modalDynamicProviders .dyn-table-shell'),
  };
}
import { showAppConfirm } from './ui.js';

const el = (id) => document.getElementById(id);

/** 提供方列表分页（客户端），与搜索共用筛选结果 */
const DYN_LIST_PAGE_SIZE = 15;

/** @type {any[]|null} */
let _dynProvidersCache = null;
/** @type {{ nextRunMap: Record<string, string>, lastRefreshMap: Record<number, unknown> }} */
let _dynSchedulerMeta = { nextRunMap: {}, lastRefreshMap: {} };

/** @type {{ page: { pageIndex: number, search: string }, modal: { pageIndex: number, search: string } }} */
const _dynListState = {
  page: { pageIndex: 0, search: '' },
  modal: { pageIndex: 0, search: '' },
};

let _dynListUiListenersBound = false;

/**
 * @param {unknown[]} providers
 * @param {string} q
 */
function filterDynProviders(providers, q) {
  const s = String(q || '').trim().toLowerCase();
  if (!s) return providers.slice();
  return providers.filter((p) => {
    const o = p && typeof p === 'object' ? /** @type {Record<string, unknown>} */ (p) : {};
    const idStr = String(o.id ?? '');
    const name = String(o.name ?? '').toLowerCase();
    const adapter = String(o.adapter_type ?? '').toLowerCase();
    const notes = String(o.notes ?? '').toLowerCase();
    return idStr.includes(s) || name.includes(s) || adapter.includes(s) || notes.includes(s);
  });
}

/**
 * @param {Record<string, unknown>} p
 * @param {{ nextRunMap: Record<string, string>, lastRefreshMap: Record<number, unknown> }} meta
 */
function buildProviderRowHtml(p, meta) {
  const { nextRunMap, lastRefreshMap } = meta;
  const health = String(p.last_health_status || '');
  const healthClass = health === 'healthy' ? 'dyn-status-healthy' : health === 'degraded' ? 'dyn-status-degraded' : health === 'down' ? 'dyn-status-down' : 'dyn-status-unknown';
  const healthDotClass = health === 'healthy' ? 'on' : p.is_in_cooldown ? 'cooldown' : health === 'degraded' ? 'cooldown' : health === 'down' ? 'off' : 'off';
  const healthLabel = health === 'healthy' ? I18n.t('provider.healthOk') : health === 'degraded' ? I18n.t('provider.healthDegraded') : health === 'down' ? I18n.t('provider.healthUnavailable') : I18n.t('provider.healthUnknown');
  const tierChip = p.billing_tier === 'paid'
    ? '<span class="dyn-chip dyn-chip-paid">' + I18n.t('provider.paidChip') + '</span>'
    : '<span class="dyn-chip dyn-chip-free">' + I18n.t('provider.freeChip') + '</span>';
  const caps = [];
  if (p.supports_auto_download) caps.push('<span class="dyn-chip" style="background:rgba(34,197,94,0.08);border-color:rgba(34,197,94,0.2);color:#22c55e">' + I18n.t('provider.autoDownloadChip') + '</span>');
  if (p.supports_cookies) caps.push('<span class="dyn-chip" style="background:rgba(59,130,246,0.08);border-color:rgba(59,130,246,0.2);color:#3b82f6">' + I18n.t('provider.cookiesChip') + '</span>');
  if (p.supports_sticky_session) caps.push('<span class="dyn-chip" style="background:rgba(168,85,247,0.08);border-color:rgba(168,85,247,0.2);color:#a855f7">' + I18n.t('provider.stickyChip') + '</span>');
  const cooldownBadge = p.is_in_cooldown ? '<span class="dyn-badge">' + I18n.t('provider.cooldownBadge') + '</span>' : '';
  const pid = p.id;
  const nextRun = nextRunMap[String(pid)] || null;
  const lastRefresh = lastRefreshMap[pid] || null;
  const lr = lastRefresh && typeof lastRefresh === 'object' ? /** @type {{ started_at?: string, raw_count?: number, valid_count?: number }} */ (lastRefresh) : null;
  const schedulerMeta = (nextRun || lr)
    ? '<div style="margin-top:5px;font-size:10px;color:#87867f;line-height:1.5">' +
        (nextRun ? (I18n.t('provider.nextRun') + esc(nextRun)) : I18n.t('provider.nextRun') + '—') +
        (lr ? ('<br>' + I18n.t('provider.lastRun') + esc(lr.started_at || '') + ' ' + I18n.t('provider.rawCount') + (lr.raw_count || 0) + ' / ' + I18n.t('provider.validCount') + (lr.valid_count || 0)) : '') +
      '</div>'
    : '';
  return '<tr>' +
    '<td class="mono-cell" style="color:var(--dyn-text)">' + pid + '</td>' +
    '<td class="name-cell">' + esc(String(p.name || '')) + schedulerMeta + '</td>' +
    '<td>' + tierChip + '</td>' +
    '<td class="mono-cell">' + esc(String(p.adapter_type || '')) + '</td>' +
    '<td>' +
      '<div style="display:flex;align-items:center;gap:5px">' +
        '<span class="dyn-dot ' + healthDotClass + '"></span>' +
        '<span class="dyn-status-text ' + healthClass + '">' + healthLabel + cooldownBadge + '</span>' +
      '</div>' +
      (p.last_error_message ? '<div style="font-size:10px;color:#ef4444;margin-top:2px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(String(p.last_error_message)) + '">' + esc(String(p.last_error_message)) + '</div>' : '') +
    '</td>' +
    '<td class="mono-cell">' + String(p.priority) + '</td>' +
    '<td><div class="chip-cell">' + caps.join('') + '</div></td>' +
    '<td>' +
      '<div class="actions">' +
        '<button type="button" class="btn-sm" onclick="window.openEditDynamicProvider(' + pid + ')">' + I18n.t('provider.btnEdit') + '</button>' +
        '<button type="button" class="btn-sm ' + (p.enabled ? 'warning' : 'success') + '" onclick="window.toggleDynamicProvider(' + pid + ', ' + (!p.enabled) + ')">' + (p.enabled ? I18n.t('provider.btnDisable') : I18n.t('provider.btnToggle')) + '</button>' +
        '<button type="button" class="btn-sm" onclick="window.healthCheckDynamicProvider(' + pid + ')">' + I18n.t('provider.btnCheck') + '</button>' +
        '<button type="button" class="btn-sm" onclick="window.refreshDynamicProvider(' + pid + ')">' + I18n.t('provider.btnRefresh') + '</button>' +
        '<button type="button" class="btn-sm" onclick="window.previewCandidatesDynamicProvider(' + pid + ')">' + I18n.t('provider.btnPreview') + '</button>' +
        '<button type="button" class="btn-sm" onclick="window.openDynamicProviderDetail(' + pid + ')">' + I18n.t('provider.btnDetail') + '</button>' +
        (p.is_in_cooldown ? '<button type="button" class="btn-sm success" onclick="window.clearCooldownDynamicProvider(' + pid + ')">' + I18n.t('provider.btnClearCooldown') + '</button>' : '') +
        '<button type="button" class="btn-sm danger" onclick="window.deleteDynamicProvider(' + pid + ')">' + I18n.t('provider.btnDelete') + '</button>' +
      '</div>' +
    '</td>' +
  '</tr>';
}

function ensureDynListUiListeners() {
  if (_dynListUiListenersBound) return;
  const bindSearch = (id, surface) => {
    const node = document.getElementById(id);
    if (!node || node.dataset.dynSearchBound) return;
    node.dataset.dynSearchBound = '1';
    node.addEventListener('input', () => {
      _dynListState[surface].search = node.value;
      _dynListState[surface].pageIndex = 0;
      renderDynamicProviderTableUi();
    });
  };
  bindSearch('dynProviderSearchPage', 'page');
  bindSearch('dynProviderSearchModal', 'modal');
  _dynListUiListenersBound = true;
}

/**
 * @param {'page'|'modal'} surface
 */
function renderDynTableForSurface(surface) {
  const suf = surface === 'page' ? 'Page' : 'Modal';
  const tbody =
    surface === 'page'
      ? document.querySelector('#page-dynamic-providers #dynProviderTableBody')
      : document.querySelector('#modalDynamicProviders #dynProviderTableBody');
  const summaryEl = document.getElementById(`dynProviderListSummary${suf}`);
  const pagEl = document.getElementById(`dynProviderPagination${suf}`);
  const prevBtn = document.getElementById(`dynProviderPrev${suf}`);
  const nextBtn = document.getElementById(`dynProviderNext${suf}`);
  const pageInfoEl = document.getElementById(`dynProviderPageInfo${suf}`);
  const searchInput = document.getElementById(`dynProviderSearch${suf}`);

  if (!tbody || !_dynProvidersCache) return;

  const st = _dynListState[surface];
  if (searchInput && searchInput.value !== st.search) searchInput.value = st.search;

  const all = _dynProvidersCache;
  const filtered = filterDynProviders(all, st.search);
  const total = filtered.length;
  const pageSize = DYN_LIST_PAGE_SIZE;
  const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1);
  if (st.pageIndex >= totalPages) st.pageIndex = Math.max(0, totalPages - 1);
  const start = st.pageIndex * pageSize;
  const pageRows = filtered.slice(start, start + pageSize);

  if (total === 0 && all.length > 0) {
    tbody.innerHTML = '<tr><td colspan="8" style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px">' + I18n.t('provider.noMatchProviders') + '</td></tr>';
  } else {
    tbody.innerHTML = pageRows.map((p) => buildProviderRowHtml(/** @type {Record<string, unknown>} */ (p), _dynSchedulerMeta)).join('');
  }

  const q = String(st.search || '').trim();
  if (summaryEl) {
    summaryEl.textContent = q
      ? `${all.length} total · ${total} filtered · ${st.pageIndex + 1}/${totalPages}`
      : `${total} total · ${st.pageIndex + 1}/${totalPages}`;
  }
  if (pageInfoEl) {
    pageInfoEl.textContent = total === 0 ? '—' : `${start + 1}–${Math.min(start + pageSize, total)} / ${total}`;
  }
  const showPag = total > pageSize;
  if (pagEl) pagEl.style.display = showPag ? 'flex' : 'none';
  if (prevBtn) prevBtn.disabled = st.pageIndex <= 0;
  if (nextBtn) nextBtn.disabled = st.pageIndex >= totalPages - 1;
}

/** 数据已在缓存时刷新两侧表格、分页与摘要（搜索/翻页时调用） */
function renderDynamicProviderTableUi() {
  ensureDynListUiListeners();
  if (!_dynProvidersCache) return;
  renderDynTableForSurface('page');
  renderDynTableForSurface('modal');
}

/**
 * @param {'page'|'modal'} surface
 * @param {number} delta
 */
export function dynProviderGoPage(surface, delta) {
  const st = _dynListState[surface];
  if (!st || !_dynProvidersCache) return;
  const filtered = filterDynProviders(_dynProvidersCache, st.search);
  const totalPages = Math.max(1, Math.ceil(filtered.length / DYN_LIST_PAGE_SIZE) || 1);
  st.pageIndex = Math.min(totalPages - 1, Math.max(0, st.pageIndex + delta));
  renderDynamicProviderTableUi();
}

// ── Dynamic Provider Management ─────────────────────────────────────

/** 刷新动态代理页 + 弹层内数据（不打开弹层） */
export async function refreshDynamicProvidersUi() {
  await updateProviderSchedulerHint();
  await Promise.all([loadDynamicProviderTable(), loadProviderSchedulerLogs()]);
}

/** 打开「管理提供方」弹层并刷新内容 */
export async function openDynamicProviders() {
  openModal('modalDynamicProviders');
  await refreshDynamicProvidersUi();
}

export async function updateProviderSchedulerHint() {
  const hints = document.querySelectorAll('[data-dyn-scheduler-hint]');
  const badges = document.querySelectorAll('[data-dyn-scheduler-badge]');
  const nextEls = document.querySelectorAll('[data-dyn-scheduler-next]');
  const btns = document.querySelectorAll('[data-dyn-scheduler-toggle]');
  if (!hints.length || !badges.length || !nextEls.length || !btns.length) return;

  let status = null;
  try { status = await api('GET', '/provider-scheduler/status'); } catch (_) { status = null; }

  const running = !!(status && status.running && !status.error);
  const nextRuns = (status && Array.isArray(status.next_runs)) ? status.next_runs : [];
  if (running) {
    hints.forEach((h) => {
      h.textContent = I18n.t('provider.schedulerRunningHint');
      h.style.color = 'var(--text-muted)';
    });
    badges.forEach((b) => {
      b.textContent = I18n.t('provider.schedulerRunning');
      b.className = 'tag tag--success';
      b.removeAttribute('style');
    });
    if (nextRuns.length) {
      const maxShow = 12;
      const lines = nextRuns.slice(0, maxShow).map(j =>
        '<div style="font-size:10px;color:var(--text-muted);margin-top:3px;line-height:1.35">' +
        esc(j.name || j.id || '') + ' · <span style="color:var(--text)">' + esc(j.next_run || '—') + '</span></div>'
      ).join('');
      const more = nextRuns.length > maxShow
        ? '<div style="font-size:10px;color:var(--text-dim);margin-top:4px">… ' + nextRuns.length + ' tasks registered</div>'
        : '';
      const html = '<div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">Registered tasks and next run</div>' + lines + more;
      nextEls.forEach((el) => { el.innerHTML = html; });
    } else {
      nextEls.forEach((el) => { el.textContent = I18n.t('provider.noTasksYet'); });
    }
    btns.forEach((b) => {
      b.textContent = b.dataset.schedulerCompact === 'true' ? I18n.t('provider.btnStopScheduler') : I18n.t('provider.btnStopDynScheduler');
      b.classList.remove('btn--ghost', 'btn--success', 'btn--warning');
      b.classList.add('btn--warning');
    });
  } else {
    hints.forEach((h) => {
      h.textContent = I18n.t('provider.schedulerHint');
      h.style.color = 'var(--text-muted)';
    });
    badges.forEach((b) => {
      b.textContent = I18n.t('provider.schedulerNotStarted');
      b.className = 'tag tag--warning';
      b.removeAttribute('style');
    });
    const html = '<div style="font-size:11px;color:var(--text-muted);line-height:1.55;margin-bottom:8px">' + I18n.t('provider.schedulerHintHtml') + '</div>';
    nextEls.forEach((el) => { el.innerHTML = html; });
    btns.forEach((b) => {
      b.textContent = b.dataset.schedulerCompact === 'true' ? I18n.t('provider.btnStartScheduler') : I18n.t('provider.btnStartDynScheduler');
      b.classList.remove('btn--ghost', 'btn--success', 'btn--warning');
      b.classList.add('btn--success');
    });
  }
}

/** 同步页内与弹窗中的调度日志筛选下拉框。 */
export function syncDynLogFilters(source) {
  const v = source.value;
  document.querySelectorAll('[data-dyn-log-filter]').forEach((s) => {
    if (s !== source) s.value = v;
  });
}

/**
 * 折叠面板：展开/收起「最近调度执行」「调度说明」。
 * @param {HTMLButtonElement} btn
 */
export function toggleDynCollapse(btn) {
  const panelId = btn.getAttribute('aria-controls');
  const panel = panelId ? document.getElementById(panelId) : null;
  if (!panel) return;
  const expanded = btn.getAttribute('aria-expanded') === 'true';
  const next = !expanded;
  btn.setAttribute('aria-expanded', String(next));
  panel.hidden = !next;
  const root = btn.closest('.dyn-collapse');
  if (root) root.classList.toggle('dyn-collapse--open', next);
}

export async function loadProviderSchedulerLogs() {
  const shells = document.querySelectorAll('[data-dyn-scheduler-logs]');
  if (!shells.length) return;

  const filter = document.querySelector('[data-dyn-log-filter]');
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
    const emptyHtml = '<div class="dyn-log-empty">' + I18n.t('provider.noLogsYet') + '</div>';
    shells.forEach((s) => { s.innerHTML = emptyHtml; });
    return;
  }
  const html = filtered.slice(0, 6).map(r => {
    const rowClass = r.status === 'success' ? 'success' : r.status === 'error' ? 'error' : 'unknown';
    const title = r.provider_name ? `${r.provider_name} · ${r.job_type}` : `system · ${r.job_type}`;
    const summary = r.job_type === 'refresh'
      ? `raw ${r.raw_count || 0} / valid ${r.valid_count || 0}`
      : (r.message || 'completed');
    return `<div class="dyn-log-row dyn-log-row--${rowClass}">
      <div class="dyn-log-row__head">
        <div class="dyn-log-row__title">${esc(title)}</div>
        <div class="dyn-log-row__status">${esc(r.status || 'unknown')}</div>
      </div>
      <div class="dyn-log-row__summary">${esc(summary)}</div>
      <div class="dyn-log-row__time">${esc(r.started_at || '')}</div>
    </div>`;
  }).join('');
  shells.forEach((s) => { s.innerHTML = html; });
}

export async function loadDynamicProviderTable() {
  const { tbodyPage, tbodyModal, emptyPage, emptyModal, shellPage, shellModal } = dynTableTargets();
  if (!tbodyPage && !tbodyModal) return;

  const empties = [emptyPage, emptyModal].filter(Boolean);
  const tbodies = [tbodyPage, tbodyModal].filter(Boolean);

  function showDynEmptyDefaults() {
    empties.forEach((empty) => {
      const titleEl = empty.querySelector('.dyn-empty-title');
      const descEl = empty.querySelector('.dyn-empty-desc');
      const ctaEl = empty.querySelector('.dyn-empty-cta');
      if (titleEl) titleEl.textContent = I18n.t('page.dynamicProviders.emptyTitle');
      if (descEl) descEl.textContent = I18n.t('page.dynamicProviders.emptyDesc');
      if (ctaEl) ctaEl.style.display = '';
    });
  }

  function showDynLoadError(errMsg) {
    empties.forEach((empty) => {
      const titleEl = empty.querySelector('.dyn-empty-title');
      const descEl = empty.querySelector('.dyn-empty-desc');
      const ctaEl = empty.querySelector('.dyn-empty-cta');
      if (titleEl) titleEl.textContent = I18n.t('provider.loadFailed');
      if (descEl) descEl.textContent = errMsg;
      if (ctaEl) ctaEl.style.display = 'none';
    });
  }

  function setTableShellsVisible(showTable) {
    if (shellPage) shellPage.style.display = showTable ? '' : 'none';
    if (shellModal) shellModal.style.display = showTable ? '' : 'none';
    empties.forEach((e) => { e.style.display = showTable ? 'none' : ''; });
    document.querySelectorAll('.dyn-provider-list-toolbar').forEach((n) => { n.style.display = showTable ? '' : 'none'; });
    document.querySelectorAll('.dyn-provider-pagination').forEach((n) => {
      if (!showTable) n.style.display = 'none';
    });
  }

  let providers;
  try { providers = await api('GET', '/dynamic-providers'); } catch (_) { providers = null; }

  if (!Array.isArray(providers)) {
    const raw = providers && typeof providers === 'object' && providers !== null ? providers.error : undefined;
    const errMsg = raw != null && String(raw).trim() ? String(raw).trim() : 'Unable to parse provider list (check network or Token)';
    toast(I18n.t('provider.loadProvidersFailed') + ': ' + errMsg, 'err');
    tbodies.forEach((tb) => { tb.innerHTML = ''; });
    _dynProvidersCache = null;
    setTableShellsVisible(false);
    showDynLoadError(errMsg);
    return;
  }

  if (!providers || providers.length === 0) {
    showDynEmptyDefaults();
    tbodies.forEach((tb) => { tb.innerHTML = ''; });
    _dynProvidersCache = null;
    setTableShellsVisible(false);
    return;
  }

  setTableShellsVisible(true);

  let sched = null; let logs = [];
  try { [sched, logs] = await Promise.all([api('GET', '/provider-scheduler/status'), api('GET', '/provider-scheduler/logs')]); }
  catch (_) { sched = null; logs = []; }
  if (!Array.isArray(logs)) logs = [];
  const nextRunsList = sched && Array.isArray(sched.next_runs) ? sched.next_runs : [];

  const nextRunMap = {};
  nextRunsList.forEach((j) => {
    const m = /^provider_refresh_(\d+)$/.exec(j.id || '');
    if (m) nextRunMap[m[1]] = j.next_run;
  });
  const lastRefreshMap = {};
  logs.forEach((r) => {
    if (r.job_type !== 'refresh' || !r.provider_id) return;
    if (!lastRefreshMap[r.provider_id]) lastRefreshMap[r.provider_id] = r;
  });

  _dynProvidersCache = providers;
  _dynSchedulerMeta = { nextRunMap, lastRefreshMap };
  _dynListState.page.pageIndex = 0;
  _dynListState.modal.pageIndex = 0;
  renderDynamicProviderTableUi();
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
  if (trigger) trigger.textContent = cur === 'none' ? I18n.t('provider.advMappingExpand') : I18n.t('provider.advMappingCollapse');
}

export function onDynBillingTierChange() {
  const tier = el('dynBillingTier');
  const risk = el('dynRiskLevel');
  if (!tier || !risk) return;
  if (tier.value === 'free') risk.value = 'medium';
}

export function openAddDynamicProvider() {
  if (!el('dynFormTitle') || !el('modalDynamicProviderForm')) return;
  el('dynFormTitle').textContent = I18n.t('dynProviders.addProviderTitle');
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
  if (!p) return toast(I18n.t('provider.providerNotFound'), 'err');
  el('dynFormTitle').textContent = I18n.t('dynProviders.addProviderTitle');
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
    if (!host || !port) { toast(I18n.t('provider.gatewayRequired'), 'err'); return null; }
    cfg.gateway_host = host;
    cfg.gateway_port = parseInt(port, 10);
    cfg.protocol = document.getElementById('dynProtocol').value;
    const uname = document.getElementById('dynUsername').value.trim();
    const pwd = document.getElementById('dynPassword').value;
    if (uname) cfg.username = uname;
    if (pwd) cfg.password = pwd;
  } else if (adapter === 'local_gateway') {
    const url = document.getElementById('dynLocalProxyUrl').value.trim();
    if (!url) { toast(I18n.t('provider.localProxyRequired'), 'err'); return null; }
    cfg.local_proxy_url = url;
  } else if (adapter === 'list_api' || adapter === 'public_feed') {
    const baseUrl = document.getElementById('dynListApiBaseUrl').value.trim();
    if (!baseUrl) { toast(I18n.t('provider.apiUrlRequired'), 'err'); return null; }
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
  if (!name) { toast(I18n.t('provider.providerNameRequired'), 'err'); return; }
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
  if (r.error) { toast(r.error || 'Failed to save', 'err'); return; }
  toast(id ? I18n.t('provider.editSuccess') : I18n.t('provider.addSuccess'), 'ok');
  closeModal('modalDynamicProviderForm');
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function toggleDynamicProvider(id, enabled) {
  const r = await api('POST', '/dynamic-providers/' + id + '/update', { enabled });
  if (r.error) { toast(r.error, 'err'); return; }
  toast(enabled ? I18n.t('proxy.enabled') : I18n.t('proxy.disabled'), 'ok');
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function deleteDynamicProvider(id) {
  const providers = await api('GET', '/dynamic-providers');
  if (!Array.isArray(providers)) { toast((providers && providers.error) ? String(providers.error) : I18n.t('provider.loadProviderListFailed'), 'err'); return; }
  const p = providers.find(x => x.id === id);
  if (!p) return toast(I18n.t('provider.providerNotFound'), 'err');
  const ok = await showAppConfirm({
    title: I18n.t('provider.deleteConfirmTitle'),
    message: I18n.t('provider.deleteConfirmMsg').replace('{name}', p.name),
    confirmText: I18n.t('provider.btnDelete'),
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('DELETE', '/dynamic-providers/' + id);
  if (r.error) { toast(r.error, 'err'); return; }
  toast(I18n.t('provider.deleteSuccess'), 'ok');
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function healthCheckDynamicProvider(id) {
  const r = await api('POST', '/dynamic-providers/' + id + '/health-check', {});
  if (r.error) { toast(r.error, 'err'); }
  else {
    const latency = r.latency_ms >= 0 ? r.latency_ms + 'ms' : '-';
    const err = r.error_message ? ' | ' + r.error_message : '';
    const statusLabel = r.status === 'healthy' ? I18n.t('provider.healthOk') : r.status === 'degraded' ? I18n.t('provider.healthDegraded') : r.status === 'down' ? I18n.t('provider.healthUnavailable') : r.status || 'healthy';
    toast('Health check: ' + statusLabel + ' (' + latency + ')' + err, r.status === 'healthy' ? 'ok' : 'warn');
  }
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function clearCooldownDynamicProvider(id) {
  const r = await api('POST', '/dynamic-providers/' + id + '/cooldown/clear', {});
  if (r.error) { toast(r.error, 'err'); return; }
  toast(I18n.t('provider.clearCooldown'), 'ok');
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}

export async function refreshDynamicProvider(id) {
  const r = await api('POST', '/dynamic-providers/' + id + '/refresh', {});
  if (r.error) { toast(I18n.t('provider.refreshError').replace('{e}', r.error), 'err'); return; }
  const raw = r.raw_count || 0;
  const valid = r.valid_count || 0;
  const top = r.top_candidate;
  const msg = top
    ? I18n.t('provider.refreshSuccess') + ' — pulled ' + raw + ', pooled ' + valid + ', health=' + (top.last_probe_status || '-')
    : I18n.t('provider.refreshSuccess') + ' — pulled ' + raw + ', pooled ' + valid;
  toast(msg, 'ok');
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
  await window.openDynamicProviderDetail(id);
}

export async function previewCandidatesDynamicProvider(id) {
  const r = await api('GET', '/dynamic-providers/' + id + '/candidates/preview');
  if (!r || r.error || r._fetchFailed) { toast(I18n.t('provider.previewFailed') + ': ' + (r.error || 'Unknown'), 'err'); return; }
  const total = r.total_count || 0;
  const sc = r.status_counts || {};
  const healthy = sc.healthy || 0;
  const down = sc.down || 0;
  const degraded = sc.degraded || 0;
  const top = r.top_candidate;
  const topInfo = top ? ' | ' + I18n.t('provider.topCandidate') + ': ' + (top.masked_proxy_endpoint || '-') + ' (' + (top.last_probe_status || '-') + ')' : '';
  toast(I18n.t('provider.previewSuccess') + ' ' + total + ' — healthy=' + healthy + ' | degraded=' + degraded + ' | down=' + down + topInfo, 'ok');
}

// ── Provider Detail Drawer ───────────────────────────────────────────

export async function openDynamicProviderDetail(id) {
  const drawer = document.getElementById('dynProviderDetailDrawer');
  const body = document.getElementById('dynProviderDetailBody');
  const errBox = document.getElementById('dynProviderDetailError');
  const previewBox = document.getElementById('dynProviderDetailPreviewSummary');
  const failureBox = document.getElementById('dynProviderDetailFailures');
  if (!drawer || !body || !errBox || !previewBox || !failureBox) {
    toast(I18n.t('provider.providerDetailNotReady'), 'warning');
    return;
  }
  openModal('dynProviderDetailDrawer');
  errBox.style.display = 'none';
  errBox.textContent = '';
  previewBox.style.display = 'none';
  previewBox.textContent = '';
  failureBox.style.display = 'none';
  failureBox.textContent = '';
  body.innerHTML = '<div class="dpd-loading">' + I18n.t('provider.providerDetailLoading') + '</div>';

  const [providers, logs, preview] = await Promise.all([
    api('GET', '/dynamic-providers'),
    api('GET', '/provider-scheduler/logs'),
    api('GET', '/dynamic-providers/' + id + '/candidates/preview'),
  ]);
  const netErr = [providers, logs, preview].find(x => x && x._fetchFailed);
  if (netErr) {
    body.innerHTML = '<div class="dpd-error-inline">' + esc(netErr.error || 'Request failed') + '</div>';
    return;
  }
  const providerList = Array.isArray(providers) ? providers : [];
  const logList = Array.isArray(logs) ? logs : [];
  const p = providerList.find(x => String(x.id) === String(id));
  if (!p) { body.innerHTML = '<div class="dpd-error-inline">' + I18n.t('provider.providerDetailNotFound') + '</div>'; return; }
  const rows = logList.filter(r => String(r.provider_id) === String(id)).slice(0, 8);
  const latest = rows.length ? rows[0] : null;
  const failureRows = rows.filter(r => r.status === 'error' || (r.message && r.message !== 'ok')).slice(0, 5);
  if (p.last_error_message || failureRows.length) {
    errBox.style.display = '';
    errBox.innerHTML = '<strong>' + I18n.t('provider.recentError') + '</strong> ' +
      esc((failureRows[0] && failureRows[0].message) || p.last_error_message || 'Unknown error');
  }
if (failureRows.length) {
    failureBox.style.display = '';
    failureBox.dataset.expanded = 'false';
    const toggle = el('dynProviderDetailFailuresToggle');
    if (toggle) toggle.textContent = failureRows.length > 2 ? I18n.t('provider.expand') : I18n.t('provider.collapse');
    const list = el('dynProviderDetailFailuresList');
    if (list) {
      list.innerHTML = failureRows.slice(0, 2).map(r => '<div class="dpd-failure-row"><span class="dpd-history-type">' + esc(r.job_type || '-') + '</span> · ' + esc(r.started_at || '') + '<br>' + esc(r.message || r.status || 'error') + '</div>').join('');
      list.dataset.full = JSON.stringify(failureRows.map(r => ({job_type: r.job_type || '-', started_at: r.started_at || '', message: r.message || r.status || 'error'})));
    }
  }
  if (preview && !preview.error) {
    const sc = preview.status_counts || {};
    previewBox.style.display = '';
    previewBox.innerHTML = '<strong>' + I18n.t('provider.candidatePreview') + '</strong> ' +
      'Total ' + esc(preview.total_count || 0) + ' · healthy ' + esc(sc.healthy || 0) +
      ' · degraded ' + esc(sc.degraded || 0) + ' · down ' + esc(sc.down || 0);
  }
  const actionBar = document.getElementById('dynProviderDetailActions');
  if (actionBar) {
    actionBar.innerHTML = `
      <button class="btn-sm" onclick="window.refreshDynamicProviderDetail(${id})">${I18n.t('provider.btnRefreshCurrent')}</button>
      <button class="btn-sm" onclick="window.previewCandidatesDynamicProvider(${id})">${I18n.t('provider.btnPreview')}</button>
      <button class="btn-sm" onclick="window.healthCheckDynamicProviderDetail(${id})">${I18n.t('provider.btnHealthCheck')}</button>
      ${p.is_in_cooldown ? `<button class="btn-sm success" onclick="window.clearCooldownDynamicProviderDetail(${id})">${I18n.t('provider.btnClearCooldown')}</button>` : ''}
    `;
  }
  body.innerHTML = `
    <div class="dpd-stack">
      <div class="dpd-card">
        <div class="dpd-card-title">${esc(p.name || '-')}</div>
        <div class="dpd-card-sub">Adapter ${esc(p.adapter_type || '-')} · Priority ${esc(p.priority || '-')} · Refresh ${esc(p.refresh_interval_minutes || 0)} min</div>
      </div>
      <div class="dpd-metrics">
        <div class="dpd-metric">
          <div class="dpd-metric-label">${I18n.t('provider.latestRaw')}</div>
          <div class="dpd-metric-value">${latest ? esc(latest.raw_count || 0) : '—'}</div>
        </div>
        <div class="dpd-metric">
          <div class="dpd-metric-label">${I18n.t('provider.latestValid')}</div>
          <div class="dpd-metric-value">${latest ? esc(latest.valid_count || 0) : '—'}</div>
        </div>
        <div class="dpd-metric">
          <div class="dpd-metric-label">${I18n.t('provider.latestStatus')}</div>
          <div class="dpd-metric-value">${latest ? esc(latest.status || '-') : '—'}</div>
        </div>
      </div>
      <div class="dpd-card">
        <div class="dpd-section-title">${I18n.t('provider.recentExecHistory')}</div>
        <div class="dpd-history">
          ${rows.length ? rows.map(r => `
            <div class="dpd-history-item ${r.status === 'success' ? 'dpd-history-item--ok' : 'dpd-history-item--err'}">
              <div class="dpd-history-row">
                <span class="dpd-history-type">${esc(r.job_type || '-')}</span>
                <span class="dpd-history-status ${r.status === 'success' ? 'ok' : 'err'}">${esc(r.status || '-')}</span>
              </div>
              <div class="dpd-history-meta">raw ${esc(r.raw_count || 0)} / valid ${esc(r.valid_count || 0)} · ${esc(r.started_at || '')}</div>
            </div>
          `).join('') : '<div class="dpd-empty">' + I18n.t('provider.noExecHistory') + '</div>'}
        </div>
      </div>
    </div>`;
}

export async function refreshDynamicProviderDetail(id) {
  try { await window.refreshDynamicProvider(id); await window.openDynamicProviderDetail(id); }
  catch (e) { toast(I18n.t('provider.refreshException') + ': ' + ((e && e.message) || e), 'err'); }
}

export async function healthCheckDynamicProviderDetail(id) {
  try { await window.healthCheckDynamicProvider(id); await window.openDynamicProviderDetail(id); }
  catch (e) { toast(I18n.t('provider.healthCheckException') + ': ' + ((e && e.message) || e), 'err'); }
}

export async function clearCooldownDynamicProviderDetail(id) {
  try { await window.clearCooldownDynamicProvider(id); await window.openDynamicProviderDetail(id); }
  catch (e) { toast(I18n.t('provider.operationException') + ': ' + ((e && e.message) || e), 'err'); }
}

export function toggleProviderFailureList() {
  const box = el('dynProviderDetailFailures');
  const list = el('dynProviderDetailFailuresList');
  const toggle = el('dynProviderDetailFailuresToggle');
  if (!box || !list || !toggle) return;
  const full = JSON.parse(list.dataset.full || '[]');
  const expanded = box.dataset.expanded === 'true';
  const rows = expanded ? full.slice(0, 2) : full;
  list.innerHTML = rows.map(r => '<div class="dpd-failure-row"><span class="dpd-history-type">' + esc(r.job_type || '-') + '</span> · ' + esc(r.started_at || '') + '<br>' + esc(r.message || 'error') + '</div>').join('');
  box.dataset.expanded = expanded ? 'false' : 'true';
  toggle.textContent = expanded ? I18n.t('provider.expand') : I18n.t('provider.collapse');
}

export function closeDynamicProviderDetail() {
  closeModal('dynProviderDetailDrawer');
}

export async function healthCheckAllProviders() {
  const providers = await api('GET', '/dynamic-providers');
  if (!providers || providers.length === 0) { toast(I18n.t('provider.noProvidersToCheck'), 'info'); return; }
  toast(I18n.t('provider.healthCheckAllStart') + ' (' + providers.length + ' providers)…', 'info');
  for (let i = 0; i < providers.length; i++) {
    await api('POST', '/dynamic-providers/' + providers[i].id + '/health-check', {});
    if (i % 3 === 2 || i === providers.length - 1) await window.loadDynamicProviderTable();
  }
  toast(I18n.t('provider.healthCheckAllDone') + ' (' + providers.length + ' providers)', 'ok');
}

window.init_dynamic_providers_page = refreshDynamicProvidersUi;
