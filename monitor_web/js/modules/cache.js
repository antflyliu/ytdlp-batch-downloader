// ── Cache Management ─────────────────────────────────────────────────
// API channel cache list and refresh/delete operations.

import { api } from '../api.js';
import { esc, fmtTime } from '../utils/format.js';
import { toast, openModal, showAppConfirm } from './ui.js';

const el = (id) => document.getElementById(id);

// ── Cache ────────────────────────────────────────────────────────────

export async function openCache() {
  openModal('modalCache');
  await loadCacheList();
}

export async function loadCacheList() {
  const list = await api('GET', '/cache');
  const cacheEl = el('cacheList');
  if (!cacheEl) return;
  if (!list || list.length === 0) {
    cacheEl.innerHTML = `<div style="color:var(--text-muted);text-align:center;padding:20px">${I18n.t('cache.noCache')}</div>`;
    return;
  }
  cacheEl.innerHTML = list.map(c => `
    <div class="account-row" style="align-items:center;padding:8px 12px;border-bottom:1px solid var(--border)">
      <div style="flex:1;min-width:0">
        <div class="mono" style="font-size:12px;color:var(--accent)">@${esc(c.handle)}</div>
        <div class="mono" style="font-size:11px;color:var(--text-muted)">
          ${esc(c.channel_id)} · ${esc(c.channel_name || '—')} · ${esc(c.uploads_playlist_id || '—')}
        </div>
        <div class="mono" style="font-size:10px;color:var(--text-muted)">${I18n.t('cache.cachedAt')}${fmtTime(c.cached_at)}</div>
      </div>
      <div style="display:flex;gap:4px">
        <button class="btn-sm" onclick="window.refreshCacheItemByHandle('${esc(c.handle)}')">${I18n.t('common.refresh')}</button>
        <button class="btn-sm danger" onclick="window.deleteCacheItem('${esc(c.handle)}')">${I18n.t('common.delete')}</button>
      </div>
    </div>`).join('');
}

export async function refreshCacheItem() {
  const handleEl = el('cacheHandle');
  const apiKeyEl = el('cacheApiKey');
  const handle = handleEl ? handleEl.value.trim() : '';
  const apiKey = apiKeyEl ? apiKeyEl.value.trim() : '';
  if (!handle || !apiKey) { toast(I18n.t('cache.handleAndApiKeyRequired'), 'err'); return; }
  const r = await api('POST', '/cache/refresh', { handle, api_key: apiKey });
  if (r.success) { toast(I18n.t('cache.cacheRefreshSuccess'), 'ok'); await loadCacheList(); }
  else toast(I18n.t('cache.refreshFailed') + (r.error ? ': ' + r.error : ''), 'err');
}

export async function refreshCacheItemByHandle(handle) {
  const apiKey = prompt(I18n.t('cache.enterApiKey'));
  if (!apiKey) return;
  const r = await api('POST', '/cache/refresh', { handle, api_key: apiKey });
  if (r.success) { toast(I18n.t('cache.cacheRefreshSuccess'), 'ok'); await loadCacheList(); }
  else toast(I18n.t('cache.refreshFailed') + (r.error ? ': ' + r.error : ''), 'err');
}

export async function deleteCacheItem(handle) {
  const ok = await showAppConfirm({
    title: I18n.t('cache.confirmDeleteCache').replace('{handle}', handle),
    message: I18n.t('cache.confirmDeleteCacheMsg'),
    confirmText: I18n.t('common.delete'),
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('DELETE', `/cache/${encodeURIComponent(handle)}`);
  if (r.ok) { toast(I18n.t('cache.deleted'), 'ok'); await loadCacheList(); }
  else toast(I18n.t('cache.deleteFailed'), 'err');
}

export async function clearAllCache() {
  const ok = await showAppConfirm({
    title: I18n.t('cache.confirmClearAll'),
    message: I18n.t('cache.confirmClearAllMsg'),
    confirmText: I18n.t('cache.clearAll'),
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('POST', '/cache/clear', {});
  if (r.ok) { toast(I18n.t('cache.cleared').replace('{n}', r.cleared), 'ok'); await loadCacheList(); }
  else toast(I18n.t('cache.clearFailed'), 'err');
}
