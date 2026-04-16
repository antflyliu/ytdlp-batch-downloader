// ── Proxy Pool Management ─────────────────────────────────────────────
// CRUD for static proxy pools.

import { api } from '../api.js';
import { esc } from '../utils/format.js';
import { toast, openModal, closeModal, showAppConfirm } from './ui.js';
import { refreshProxyPoolSelectors } from './accounts.js';

const el = (id) => document.getElementById(id);

// ── Proxy Pool ──────────────────────────────────────────────────────

export function openProxyDemo() {
  const ppTableView = el('ppTableView');
  if (ppTableView) ppTableView.style.display = 'none';
  const ppDemoView = el('ppDemoView');
  if (ppDemoView) ppDemoView.classList.add('show');
  const ppDemoSection = el('ppDemoSection');
  if (ppDemoSection) ppDemoSection.style.display = 'none';
  const mb = document.querySelector('#modalProxyPools .modal-body');
  if (mb) mb.style.overflow = 'hidden';
  const demoBtn = document.querySelector('#ppDemoBtn');
  if (demoBtn) demoBtn.style.display = 'none';
}

export function closeProxyDemo() {
  const ppTableView = el('ppTableView');
  if (ppTableView) ppTableView.style.display = '';
  const ppDemoView = el('ppDemoView');
  if (ppDemoView) ppDemoView.classList.remove('show');
  const ppDemoSection = el('ppDemoSection');
  if (ppDemoSection) ppDemoSection.style.display = '';
  const mb = document.querySelector('#modalProxyPools .modal-body');
  if (mb) mb.style.overflow = 'auto';
  const empty = el('emptyProxyPools');
  const demoBtn = document.querySelector('#ppDemoBtn');
  if (demoBtn) demoBtn.style.display = (empty && empty.style.display !== 'none') ? 'none' : '';
}

export async function openProxyPools() {
  closeProxyDemo();
  openModal('modalProxyPools');
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
    const demoBtn = document.querySelector('#ppDemoBtn');
    if (demoBtn) demoBtn.style.display = 'none';
    return;
  }
  if (wrap) wrap.style.display = 'table';
  if (empty) empty.style.display = 'none';
  const demoBtn2 = document.querySelector('#ppDemoBtn');
  if (demoBtn2) demoBtn2.style.display = '';
  if (tbody) {
    tbody.innerHTML = pools.map(p => `
    <tr>
      <td class="td-mono" style="color:var(--proxy-text)">${p.id}</td>
      <td class="name-cell">${esc(p.name)}</td>
      <td class="url-cell" title="${esc(p.proxy_url)}">${esc(p.proxy_url)}</td>
      <td>
        <div class="status-cell">
          <span class="proxy-dot ${p.enabled ? 'on' : 'off'}"></span>
          ${p.enabled ? '<span style="color:var(--proxy-text)">在线</span>' : '<span style="color:var(--text-dim)">离线</span>'}
        </div>
      </td>
      <td>
        <div class="actions">
          <button class="btn-sm" onclick="window.openEditProxyPool(${p.id})">编辑</button>
          <button class="btn-sm ${p.enabled ? 'warning' : 'success'}" onclick="window.toggleProxyPool(${p.id}, ${!p.enabled})">${p.enabled ? '禁用' : '启用'}</button>
          <button class="btn-sm danger" onclick="window.deleteProxyPool(${p.id})">删除</button>
        </div>
      </td>
    </tr>`).join('');
  }
}

export function openAddProxyPool() {
  closeProxyDemo();
  const title = el('modalProxyPoolFormTitle');
  if (title) title.textContent = '添加代理节点';
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
  if (!pool) return toast('固定代理不存在', 'err');
  const title = el('modalProxyPoolFormTitle');
  if (title) title.textContent = '编辑代理节点';
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
  if (!name || !url) { toast('名称和代理地址不能为空', 'err'); return; }
  const body = {
    name,
    proxy_url: url,
    enabled: ppEnabled ? ppEnabled.checked : false,
  };
  let r;
  if (id) r = await api('POST', `/proxy-pools/${id}/update`, body);
  else r = await api('POST', '/proxy-pools', body);
  if (r.error) { toast(r.error || '保存失败', 'err'); return; }
  toast(id ? '固定代理已更新' : '固定代理已添加', 'ok');
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
  toast(enabled ? '固定代理已启用' : '固定代理已禁用', 'ok');
  await loadProxyPoolTable();
  await refreshProxyPoolSelectors();
}

export async function deleteProxyPool(id) {
  const pools = await api('GET', '/proxy-pools');
  const pool = pools && pools.find(p => p.id === id);
  if (!pool) return toast('固定代理不存在', 'err');
  const ok = await showAppConfirm({
    title: `确定删除固定代理「${pool.name}」？`,
    message: '关联的账户将停止使用此代理。',
    confirmText: '删除',
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('DELETE', `/proxy-pools/${id}`);
  if (r.error) { toast(r.error, 'err'); return; }
  if (r.affected_accounts && r.affected_accounts.length > 0) {
    toast(`已删除（${r.affected_accounts.length} 个账户已停止使用此代理）`, 'ok');
  } else {
    toast('已删除', 'ok');
  }
  await loadProxyPoolTable();
  await refreshProxyPoolSelectors();
}
