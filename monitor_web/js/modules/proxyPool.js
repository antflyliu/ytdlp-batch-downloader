// ── Proxy Pool Management ─────────────────────────────────────────────
// CRUD for static proxy pools.

import { api } from '../api.js';
import { esc } from '../utils/format.js';
import { toast, openModal, closeModal, showAppConfirm } from './ui.js';
import { refreshProxyPoolSelectors } from './accounts.js';

const el = (id) => document.getElementById(id);

// ── Proxy Pool ──────────────────────────────────────────────────────

/** 在独立 sheet 弹窗中打开「功能演示」iframe，避免页内切换导致表格被隐藏而出现空白。 */
export function openProxyDemo() {
  openModal('modalProxyPoolDemo');
}

export function closeProxyDemo() {
  closeModal('modalProxyPoolDemo');
}

export async function openProxyPools() {
  closeProxyDemo();
  await loadProxyPoolTable();
}

export async function loadProxyPoolTable() {
  const pools = await api('GET', '/proxy-pools');
  const tbody = el('proxyPoolTable');
  const empty = el('emptyProxyPools');
  const wrap = el('proxyPoolTableWrap');
  if (!pools || pools.length === 0) {
    if (tbody) tbody.innerHTML = '';
    if (empty) empty.style.display = '';
    if (wrap) wrap.style.display = 'none';
    return;
  }
  if (wrap) wrap.style.display = 'block';
  if (empty) empty.style.display = 'none';
  if (tbody) {
    tbody.innerHTML = pools.map(p => `
    <tr>
      <td class="td-mono">${p.id}</td>
      <td class="td-name">${esc(p.name)}</td>
      <td class="td-url" title="${esc(p.proxy_url)}">${esc(p.proxy_url)}</td>
      <td>
        <div class="proxy-pool-status">
          <span class="proxy-dot ${p.enabled ? 'on' : 'off'}"></span>
          ${p.enabled ? '<span class="proxy-pool-status__on">' + I18n.t('proxy.statusOnline') + '</span>' : '<span class="proxy-pool-status__off">' + I18n.t('proxy.statusOffline') + '</span>'}
        </div>
      </td>
      <td>
        <div class="actions">
          <button class="btn-sm" onclick="window.openEditProxyPool(${p.id})">${I18n.t('proxy.btnEdit')}</button>
          <button class="btn-sm ${p.enabled ? 'warning' : 'success'}" onclick="window.toggleProxyPool(${p.id}, ${!p.enabled})">${p.enabled ? I18n.t('proxy.btnDisable') : I18n.t('proxy.btnEnable')}</button>
          <button class="btn-sm danger" onclick="window.deleteProxyPool(${p.id})">${I18n.t('proxy.btnDelete')}</button>
        </div>
      </td>
    </tr>`).join('');
  }
}

export function openAddProxyPool() {
  closeProxyDemo();
  const title = el('modalProxyPoolFormTitle');
  if (title) title.textContent = I18n.t('proxy.modalTitleAdd');
  const ppId = el('ppId');
  if (ppId) ppId.value = '';
  const ppName = el('ppName');
  if (ppName) ppName.value = '';
  const ppUrl = el('ppUrl');
  if (ppUrl) ppUrl.value = '';
  const ppEnabled = el('ppEnabled');
  if (ppEnabled) ppEnabled.checked = true;
  openModal('modalProxyPoolForm');
}

export async function openEditProxyPool(id) {
  const pools = await api('GET', '/proxy-pools');
  const pool = pools && pools.find(p => p.id === id);
  if (!pool) return toast(I18n.t('proxy.notFound'), 'err');
  const title = el('modalProxyPoolFormTitle');
  if (title) title.textContent = I18n.t('proxy.modalTitleEdit');
  const ppId = el('ppId');
  if (ppId) ppId.value = pool.id;
  const ppName = el('ppName');
  if (ppName) ppName.value = pool.name;
  const ppUrl = el('ppUrl');
  if (ppUrl) ppUrl.value = pool.proxy_url;
  const ppEnabled = el('ppEnabled');
  if (ppEnabled) ppEnabled.checked = !!pool.enabled;
  openModal('modalProxyPoolForm');
}

export async function saveProxyPool() {
  const ppId = el('ppId');
  const ppName = el('ppName');
  const ppUrl = el('ppUrl');
  const ppEnabled = el('ppEnabled');
  const id = ppId ? ppId.value : '';
  const name = ppName ? ppName.value.trim() : '';
  const url = ppUrl ? ppUrl.value.trim() : '';
  if (!name || !url) { toast(I18n.t('proxy.nameAndUrlRequired'), 'err'); return; }
  const body = {
    name,
    proxy_url: url,
    enabled: ppEnabled ? ppEnabled.checked : false,
  };
  let r;
  if (id) r = await api('POST', `/proxy-pools/${id}/update`, body);
  else r = await api('POST', '/proxy-pools', body);
  if (r.error) { toast(r.error || I18n.t('proxy.saveFailed'), 'err'); return; }
  toast(id ? I18n.t('proxy.saved') : I18n.t('proxy.added'), 'ok');
  closeModal('modalProxyPoolForm');
  await loadProxyPoolTable();
  await refreshProxyPoolSelectors();
}

export async function toggleProxyPool(id, enabled) {
  const pools = await api('GET', '/proxy-pools');
  const pool = pools && pools.find(p => p.id === id);
  if (!pool) return;
  const r = await api('POST', `/proxy-pools/${id}/update`, { enabled });
  if (r.error) { toast(r.error, 'err'); return; }
  toast(enabled ? I18n.t('proxy.enabled') : I18n.t('proxy.disabled'), 'ok');
  await loadProxyPoolTable();
  await refreshProxyPoolSelectors();
}

export async function deleteProxyPool(id) {
  const pools = await api('GET', '/proxy-pools');
  const pool = pools && pools.find(p => p.id === id);
  if (!pool) return toast(I18n.t('proxy.notFound'), 'err');
  const ok = await showAppConfirm({
    title: I18n.t('proxy.deleteConfirmTitle').replace('{name}', pool.name),
    message: I18n.t('proxy.deleteConfirmMsg'),
    confirmText: I18n.t('proxy.btnDelete'),
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('DELETE', `/proxy-pools/${id}`);
  if (r.error) { toast(r.error, 'err'); return; }
  if (r.affected_accounts && r.affected_accounts.length > 0) {
    toast(I18n.t('proxy.deletedWithAccounts').replace('{n}', r.affected_accounts.length), 'ok');
  } else {
    toast(I18n.t('proxy.btnDelete'), 'ok');
  }
  await loadProxyPoolTable();
  await refreshProxyPoolSelectors();
}

window.init_proxy_pools_page = openProxyPools;
