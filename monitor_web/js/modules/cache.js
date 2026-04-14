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
    cacheEl.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:20px">暂无缓存</div>';
    return;
  }
  cacheEl.innerHTML = list.map(c => `
    <div class="account-row" style="align-items:center;padding:8px 12px;border-bottom:1px solid var(--border)">
      <div style="flex:1;min-width:0">
        <div class="mono" style="font-size:12px;color:var(--accent)">@${esc(c.handle)}</div>
        <div class="mono" style="font-size:11px;color:var(--text-muted)">
          ${esc(c.channel_id)} · ${esc(c.channel_name || '—')} · ${esc(c.uploads_playlist_id || '—')}
        </div>
        <div class="mono" style="font-size:10px;color:var(--text-muted)">缓存于 ${fmtTime(c.cached_at)}</div>
      </div>
      <div style="display:flex;gap:4px">
        <button class="btn-sm" onclick="window.refreshCacheItemByHandle('${esc(c.handle)}')">刷新</button>
        <button class="btn-sm danger" onclick="window.deleteCacheItem('${esc(c.handle)}')">删除</button>
      </div>
    </div>`).join('');
}

export async function refreshCacheItem() {
  const handleEl = el('cacheHandle');
  const apiKeyEl = el('cacheApiKey');
  const handle = handleEl ? handleEl.value.trim() : '';
  const apiKey = apiKeyEl ? apiKeyEl.value.trim() : '';
  if (!handle || !apiKey) { toast('handle 和 API Key 均必填', 'err'); return; }
  const r = await api('POST', '/cache/refresh', { handle, api_key: apiKey });
  if (r.success) { toast('缓存刷新成功', 'ok'); await loadCacheList(); }
  else toast('刷新失败: ' + (r.error || ''), 'err');
}

export async function refreshCacheItemByHandle(handle) {
  const apiKey = prompt('请输入 YouTube API Key（用于刷新缓存）:\n\n提示：需要该频道对应的 API Key');
  if (!apiKey) return;
  const r = await api('POST', '/cache/refresh', { handle, api_key: apiKey });
  if (r.success) { toast('缓存刷新成功', 'ok'); await loadCacheList(); }
  else toast('刷新失败: ' + (r.error || ''), 'err');
}

export async function deleteCacheItem(handle) {
  const ok = await showAppConfirm({
    title: `确认删除缓存 @${handle}？`,
    message: '删除后下次扫描会重新调用 API（1 unit）。',
    confirmText: '删除',
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('DELETE', `/cache/${encodeURIComponent(handle)}`);
  if (r.ok) { toast('已删除', 'ok'); await loadCacheList(); }
  else toast('删除失败', 'err');
}

export async function clearAllCache() {
  const ok = await showAppConfirm({
    title: '确认清空所有 API 缓存？',
    message: '所有频道下次扫描都会重新调用 API（每次 1 unit）。',
    confirmText: '清空全部',
    variant: 'danger',
  });
  if (!ok) return;
  const r = await api('POST', '/cache/clear', {});
  if (r.ok) { toast(`已清空 ${r.cleared} 条缓存`, 'ok'); await loadCacheList(); }
  else toast('清空失败', 'err');
}
