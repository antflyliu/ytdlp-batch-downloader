// ── Account List Component ─────────────────────────────────────────
import { api } from '../api.js';
import { esc, fmtTime } from '../utils/format.js';
import { toast } from '../modules/ui.js';

const el = (id) => document.getElementById(id);

/**
 * Load and render the accounts table.
 * @returns {Promise<void>}
 */
export async function loadAccounts() {
  const accounts = await api('GET', '/accounts');
  const tbody = el('accountsTable');
  const empty = el('emptyAccounts');
  const tableWrap = document.querySelector('.table-wrap');

  if (!tbody) return;

  if (!Array.isArray(accounts)) {
    const msg = (accounts && accounts.error) ? String(accounts.error) : '加载失败';
    if (accounts && accounts._httpStatus === 429) {
      toast('账户列表请求被限流，将随下次刷新重试', 'warning');
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

  tbody.innerHTML = accounts.map(a => {
    const modeTag = a.fetch_mode === 'playlist'
      ? '<span class="tag tag-muted">playlist</span>'
      : '<span class="tag tag-accent">search</span>';
    const platTag = a.notify_platform === 'feishu'
      ? '<span class="tag tag-feishu">飞书</span>'
      : a.notify_platform === 'dingtalk'
      ? '<span class="tag tag-dingtalk">钉钉</span>'
      : '<span class="tag tag-wecom">企微</span>';
    const statusTag = a.enabled
      ? '<span class="tag tag-success">启用</span>'
      : '<span class="tag tag-muted">禁用</span>';
    const notifyTag = a.notify_enabled
      ? '<span class="tag tag-success">通知</span>'
      : '<span class="tag tag-muted">静默</span>';
    const apiKeyTag = a.api_key_id
      ? '<span class="tag tag-accent">Key-' + a.api_key_id + '</span>'
      : '<span class="tag tag-muted">默认</span>';
    const proxyTag = a.proxy_enabled && a.proxy_pool_id
      ? '<span class="account-proxy-cell"><span class="proxy-dot on" title="代理已启用"></span><span style="font-size:11px;color:var(--proxy-text)">启用</span></span>'
      : '<span class="account-proxy-cell"><span class="proxy-dot off" title="不使用代理"></span><span style="font-size:11px;color:var(--text-dim)">—</span></span>';
    return `<tr>
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
          <button class="btn-sm" onclick="window.openEditAccount(${a.id})">编辑</button>
          <button class="btn-sm" onclick="window.openVideoDetail(${a.id})">详情</button>
          <button class="btn-sm info" data-scan-now-id="${a.id}" onclick="window.scanNow(${a.id}, this)">立即扫描</button>
          <button class="btn-sm danger" onclick="window.deleteAccount(${a.id})">删除</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}
