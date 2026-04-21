// ── Account List Component ─────────────────────────────────────────
import { api } from '../api.js';
import { esc, fmtTime } from '../utils/format.js';
import { toast } from '../modules/ui.js';

const el = (id) => document.getElementById(id);

// Raw account data cached for client-side search filtering
let _accountsCache = [];

/**
 * Filter the displayed account table rows by name or channel URL.
 * @param {string} query
 */
export function filterAccountTable(query) {
  const tbody = el('accountsTable');
  if (!tbody) return;
  const q = query.trim().toLowerCase();
  const rows = tbody.querySelectorAll('tr');
  let visible = 0;
  rows.forEach(row => {
    // Data is stored in data-* attributes on the <tr>
    const name = (row.dataset.name || '').toLowerCase();
    const url = (row.dataset.url || '').toLowerCase();
    const match = !q || name.includes(q) || url.includes(q);
    row.style.display = match ? '' : 'none';
    if (match) visible++;
  });
  const countEl = el('accountCount');
  if (countEl) {
    countEl.textContent = q
      ? `${visible} / ${_accountsCache.length}`
      : I18n.t('account.totalAccounts').replace('{n}', String(_accountsCache.length));
  }
}

/**
 * Load and render the accounts table.
 * @returns {Promise<void>}
 */
export async function loadAccounts() {
  const accounts = await api('GET', '/accounts');
  const tbody = el('accountsTable');
  const empty = el('emptyAccounts');
  const tableWrap = el('accountsTableWrap');

  if (!tbody) return;

  if (!Array.isArray(accounts)) {
    const msg = (accounts && accounts.error) ? String(accounts.error) : I18n.t('account.loadFailed');
    if (accounts && accounts._httpStatus === 429) {
      toast(I18n.t('account.loadRateLimit'), 'warning');
    } else {
      toast(msg, 'err');
    }
    tbody.innerHTML =
      '<tr><td colspan="11" style="text-align:center;color:var(--text-muted);padding:20px">' +
      esc(msg) + '</td></tr>';
    if (empty) empty.style.display = 'none';
    if (tableWrap) tableWrap.style.display = 'block';
    return;
  }

  if (!accounts || accounts.length === 0) {
    tbody.innerHTML = '';
    if (empty) empty.style.display = 'block';
    if (tableWrap) tableWrap.style.display = 'none';
    return;
  }
  if (empty) empty.style.display = 'none';
  if (tableWrap) tableWrap.style.display = 'block';

  // Cache raw data for search filtering
  _accountsCache = accounts;

  // Update count display
  const countEl = el('accountCount');
  if (countEl) countEl.textContent = I18n.t('account.totalAccounts').replace('{n}', String(accounts.length));

  // Clear search input when reload
  const searchEl = el('accountSearch');
  if (searchEl) searchEl.value = '';

  tbody.innerHTML = accounts.map(a => {
    const modeTag = a.fetch_mode === 'playlist'
      ? '<span class="tag tag-muted">playlist</span>'
      : '<span class="tag tag-accent">search</span>';
    const platTag = a.notify_platform === 'feishu'
      ? `<span class="tag tag-feishu">${I18n.t('account.platFeishu')}</span>`
      : a.notify_platform === 'dingtalk'
      ? `<span class="tag tag-dingtalk">${I18n.t('account.platDingtalk')}</span>`
      : a.notify_platform === 'telegram'
      ? `<span class="tag tag-telegram">${I18n.t('account.platTelegram')}</span>`
      : `<span class="tag tag-wecom">${I18n.t('account.platWecom')}</span>`;
    const statusTag = a.enabled
      ? `<span class="tag tag-success">${I18n.t('account.statusEnabled')}</span>`
      : `<span class="tag tag-muted">${I18n.t('account.statusDisabled')}</span>`;
    const notifyTag = a.notify_enabled
      ? `<span class="tag tag-success">${I18n.t('account.notifyEnabled')}</span>`
      : `<span class="tag tag-muted">${I18n.t('account.notifySilent')}</span>`;
    const apiKeyTag = a.api_key_id
      ? '<span class="tag tag-accent">Key-' + a.api_key_id + '</span>'
      : '<span class="tag tag-muted">' + I18n.t('common.default') + '</span>';
    const proxyTag = a.proxy_enabled && a.proxy_pool_id
      ? '<span class="account-proxy-cell"><span class="proxy-dot on" title=""></span><span style="font-size:11px;color:var(--proxy-text)">' + I18n.t('account.proxyEnabled') + '</span></span>'
      : '<span class="account-proxy-cell"><span class="proxy-dot off" title=""></span><span style="font-size:11px;color:var(--text-dim)">—</span></span>';
    return `<tr data-name="${esc(a.name || '')}" data-url="${esc(a.channel_url || '')}">
      <td class="td-mono">${a.id}</td>
      <td class="td-name">${esc(a.name)}</td>
      <td class="td-url" title="${esc(a.channel_url)}">${esc(a.channel_url)}</td>
      <td>${apiKeyTag}</td>
      <td>${modeTag}</td>
      <td class="td-mono">${a.scan_interval}m</td>
      <td class="td-mono">${a.fetch_limit}</td>
      <td>${statusTag}</td>
      <td>${platTag}${notifyTag}</td>
      <td>${proxyTag}</td>
      <td>
        <div class="actions">
          <button class="btn-sm" onclick="window.openEditAccount(${a.id})">${I18n.t('account.btnEdit')}</button>
          <button class="btn-sm" onclick="window.openVideoDetail(${a.id})">${I18n.t('account.btnDetail')}</button>
          <button class="btn-sm info" data-scan-now-id="${a.id}" onclick="window.scanNow(${a.id}, this)">${I18n.t('account.btnScanNow')}</button>
          <button class="btn-sm danger" onclick="window.deleteAccount(${a.id})">${I18n.t('account.btnDelete')}</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}
