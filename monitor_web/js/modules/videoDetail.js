// ── Video Detail Modal ───────────────────────────────────────────────
// Full-screen video list with search, sort, pagination, and batch download.

import { api } from '../api.js';
import { esc } from '../utils/format.js';
import { fmtDuration } from '../utils/format.js';
import { toast, openModal, closeModal } from './ui.js';
import { _vdAccId, _vdPage, _vdSel, _gConfig, setVdAccId, setVdPage, setVdSelClear } from './state.js';

// Click delegation for external links in video table
// Uses event delegation on document so it works even if vdTbody is lazy-loaded
document.addEventListener('click', (e) => {
  const opener = e.target.closest('.vd-open-url');
  if (!opener) return;
  const targetUrl = opener.getAttribute('data-open-url');
  if (!targetUrl) return;
  window.open(targetUrl.startsWith('http') ? targetUrl : '#', '_blank');
});

export function openVideoDetail(accId) {
  // Guard: modalVideoDetail is loaded via loadPartials() — if not yet in DOM, skip
  if (!document.getElementById('modalVideoDetail')) {
    toast('页面加载中，请稍后重试', 'warning');
    return;
  }
  setVdAccId(accId);
  setVdPage(1);
  setVdSelClear();
  const subToggle = document.getElementById('vdSubToggle');
  if (subToggle) subToggle.checked = false;
  _updateVdSubLabelText();
  // ESC：ui.closeModal('modalVideoDetail') 会移除监听并关闭
  window._vdEscHandlerRef = (e) => { if (e.key === 'Escape') closeModal('modalVideoDetail'); };
  document.addEventListener('keydown', window._vdEscHandlerRef);
  openModal('modalVideoDetail');
  vdLoad();
}

export async function vdLoad() {
  const el = (id) => document.getElementById(id);
  const titleKw = (el('vdTitleSearch') || {value:''}).value.trim();
  const urlKw = (el('vdUrlSearch') || {value:''}).value.trim();
  const sortBy = (el('vdSortBy') || {value:'published_at'}).value;
  const sortDir = (el('vdSortDir') || {value:'desc'}).value;
  const pageSizeEl = el('vdPageSize');
  const pageSize = pageSizeEl ? (parseInt(pageSizeEl.value, 10) || 20) : 20;
  const statusFilter = (el('vdStatusFilter') || {value:''}).value;
  const videoPath = '/accounts/' + _vdAccId + '/videos?title_kw=' + encodeURIComponent(titleKw) +
    '&url_kw=' + encodeURIComponent(urlKw) + '&sort_by=' + sortBy + '&sort_dir=' + sortDir +
    (statusFilter ? '&status=' + encodeURIComponent(statusFilter) : '') +
    '&page=' + _vdPage + '&page_size=' + pageSize;
  const [res, accs] = await Promise.all([
    api('GET', videoPath),
    api('GET', '/accounts').catch(() => null),
  ]);
  const nameEl = el('vdAccountName');
  if (nameEl) {
    if (Array.isArray(accs)) {
      const row = accs.find(x => String(x.id) === String(_vdAccId));
      nameEl.textContent = row && row.name ? ' · ' + row.name : '';
    } else {
      nameEl.textContent = '';
    }
  }
  const tbody = document.getElementById('vdTbody');
  if (!tbody) return;
  if (!res || res.error || !Array.isArray(res.videos)) {
    const msg = (res && res.error) ? String(res.error) : '加载失败';
    if (res && res._httpStatus === 429) {
      toast('请求过于频繁，请稍后再试或点击「搜索」重试', 'warning');
    } else {
      toast(msg, 'err');
    }
    const _s = (id) => { const e = document.getElementById(id); if (e) e.textContent = arguments[1]; };
    _s('vdTotal', '共 — 条'); _s('vdPageInfo', '— / — 页');
    const _d = (id, v) => { const e = document.getElementById(id); if (e) e.disabled = v; };
    _d('vdPrevBtn', true); _d('vdNextBtn', true);
    tbody.innerHTML =
      '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:32px;line-height:1.6">' +
      esc(msg) + '<br><span style="font-size:12px;opacity:.85">若为限流，等待约 1 分钟后点击「搜索」刷新。</span></td></tr>';
    return;
  }
  const _s2 = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
  const _d2 = (id, v) => { const e = document.getElementById(id); if (e) e.disabled = v; };
  _s2('vdTotal', '共 ' + res.total + ' 条'); _s2('vdPageInfo', res.page + ' / ' + res.pages + ' 页');
  _d2('vdPrevBtn', res.page <= 1); _d2('vdNextBtn', res.page >= res.pages);

  // 状态筛选模式下隐藏分页（因为 get_account_videos_filtered 不支持分页）
  const footerBar = document.querySelector('.vd-modal-toolbar--footer');
  if (footerBar) footerBar.style.display = statusFilter ? 'none' : '';

  // 显示重试按钮（仅"失败"筛选时）
  const retryBtn = document.getElementById('vdRetryBtn');
  const retryCount = document.getElementById('vdRetryCount');
  if (retryBtn && retryCount) {
    if (statusFilter === 'failed') {
      retryBtn.style.display = '';
      retryCount.textContent = res.total;
    } else {
      retryBtn.style.display = 'none';
    }
  }
  if (!res.videos || res.videos.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:32px">暂无数据</td></tr>';
    return;
  }
  tbody.innerHTML = res.videos.map(v => {
    const sel = _vdSel.has(v.id) ? 'checked' : '';
    const dlTag = v.download_status === 'downloaded'
      ? '<span class="tag tag-downloaded">已下载</span>'
      : v.download_status === 'downloading'
      ? '<span class="tag tag-downloading">下载中</span>'
      : v.download_status === 'failed'
      ? '<span class="tag tag-download-failed">失败</span>'
      : '<span class="tag tag-download-pending">待下载</span>';
    const pubDate = v.published_at ? v.published_at.slice(0, 10) : '—';
    const duration = v.duration_sec ? fmtDuration(v.duration_sec) : '—';
    const views = v.view_count ? Number(v.view_count).toLocaleString() : '—';
    const title = esc(v.title || '');
    const url = esc(v.url || '');
    const desc = v.description ? esc(v.description.slice(0, 80) + (v.description.length > 80 ? '…' : '')) : '';
    return '<tr data-id="' + v.id + '">' +
      '<td class="vd-check"><input type="checkbox" ' + sel + ' onchange="window.vdToggle(' + v.id + ', this.checked)"></td>' +
      '<td>' +
        '<div class="vd-title vd-open-url" data-open-url="' + (url.startsWith('http') ? url : '#') + '" title="' + title + '">' + title + '</div>' +
        '<a class="vd-url" href="' + (url.startsWith('http') ? url : '#') + '" target="_blank">' + url + '</a>' +
        (desc ? '<div class="vd-desc">' + desc + '</div>' : '') +
      '</td>' +
      '<td class="vd-num">' + pubDate + '</td>' +
      '<td class="vd-num">' + duration + '</td>' +
      '<td class="vd-num">' + views + '</td>' +
      '<td class="vd-num">' + (v.like_count || '—') + '</td>' +
      '<td class="vd-num">' + (v.comment_count || '—') + '</td>' +
      '<td>' + dlTag + '</td>' +
      '<td><button type="button" class="btn-sm vd-open-url" data-open-url="' + (url.startsWith('http') ? url : '#') + '">▶</button>' +
(v.download_status === 'downloaded'
 ? ' <button type="button" class="btn-sm" style="color:var(--accent)" onclick="chTriggerClip(' + v.id + ',this)" title="AI切片">✂</button>'
 : '') +
'</td>' +
    '</tr>';
  }).join('');
  const allChecked = res.videos.length > 0 && res.videos.every(v => _vdSel.has(v.id));
  const ca = document.getElementById('vdCheckAll');
  if (ca) ca.checked = allChecked;
  _updateVdSelCount();
}

export function vdSearch() { setVdPage(1); vdLoad(); }
export function vdGoPage(dir) { setVdPage(_vdPage + dir); vdLoad(); }
export function vdChangePageSize() { setVdPage(1); vdLoad(); }

export function vdClearFilters() {
  const ts = document.getElementById('vdTitleSearch');
  const us = document.getElementById('vdUrlSearch');
  const sf = document.getElementById('vdStatusFilter');
  const sb = document.getElementById('vdSortBy');
  const sd = document.getElementById('vdSortDir');
  if (ts) ts.value = '';
  if (us) us.value = '';
  if (sf) sf.value = '';
  if (sb) sb.value = 'published_at';
  if (sd) sd.value = 'desc';
  setVdPage(1);
  vdLoad();
}

export async function vdRetryFailed() {
  const retryBtn = document.getElementById('vdRetryBtn');
  if (!retryBtn) return;
  const count = parseInt(document.getElementById('vdRetryCount').textContent || '0', 10);
  if (count === 0) return;
  if (!confirm('确定要重试 ' + count + ' 个失败视频吗？')) return;
  retryBtn.disabled = true;
  retryBtn.innerHTML = '<span class="spinner"></span> 重试中...';
  try {
    // 收集当前表格中所有失败视频的 ID
    const rows = document.querySelectorAll('#vdTbody tr[data-id]');
    const videoIds = [...rows].map(r => parseInt(r.dataset.id)).filter(id => !isNaN(id));
    if (videoIds.length === 0) {
      toast('没有可重试的视频', 'warning');
      retryBtn.disabled = false;
      retryBtn.innerHTML = '重试失败 (<span id="vdRetryCount">0</span>)';
      return;
    }
    const r = await api('POST', '/api/videos/retry', {
      video_ids: videoIds,
      account_id: _vdAccId,
    });
    if (r.ok) {
      toast(r.retried + ' 个视频已重试', 'ok');
      setVdPage(1);
      setVdSelClear();
      vdLoad();
    } else {
      toast('重试失败: ' + (r.error || ''), 'err');
    }
  } catch (e) {
    toast('重试请求失败: ' + (e.message || ''), 'err');
  }
  retryBtn.disabled = false;
  retryBtn.innerHTML = '重试失败 (<span id="vdRetryCount">' + count + '</span>)';
}

export function vdToggle(id, checked) {
  if (checked) _vdSel.add(id); else _vdSel.delete(id);
  const row = document.querySelector(`tr[data-id="${id}"]`);
  if (row) {
    const cb = row.querySelector('input[type="checkbox"]');
    if (cb) cb.checked = checked;
  }
  _updateVdSelCount();
  _syncVdCheckAll();
}

function _syncVdCheckAll() {
  const rows = document.querySelectorAll('#vdTbody tr');
  const allChecked = rows.length > 0 && [...rows].every(r => _vdSel.has(parseInt(r.dataset.id)));
  document.getElementById('vdCheckAll').checked = allChecked;
}

export function vdToggleAll(el) {
  const rows = document.querySelectorAll('#vdTbody tr');
  if (el.checked) {
    rows.forEach(r => {
      const cb = r.querySelector('input[type="checkbox"]');
      if (cb) cb.checked = true;
      _vdSel.add(parseInt(r.dataset.id));
    });
  } else {
    rows.forEach(r => {
      const cb = r.querySelector('input[type="checkbox"]');
      if (cb) cb.checked = false;
      _vdSel.delete(parseInt(r.dataset.id));
    });
  }
  _updateVdSelCount();
}

function _updateVdSelCount() {
  const n = document.getElementById('vdSelCount');
  const b = document.getElementById('vdBatchBtn');
  if (n) n.textContent = _vdSel.size;
  if (b) b.disabled = _vdSel.size === 0;
}

export function _updateVdSubLabelText() {
  const toggle = document.getElementById('vdSubToggle');
  const label = document.getElementById('vdSubLabel');
  if (!toggle || !label) return;
  label.textContent = toggle.checked ? '字幕:是' : '字幕:否';
}

export function _getVdSubPayload() {
  const on = document.getElementById('vdSubToggle').checked;
  const subLangs = (_gConfig && _gConfig.default_sub_langs) || 'zh-Hans,en';
  return on ? { sub_langs: subLangs, no_subs: false } : { no_subs: true };
}

export async function vdBatchDownload() {
  if (_vdSel.size === 0) return;
  const btn = document.getElementById('vdBatchBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span><span>提交中...</span>';

  const payload = Object.assign({ video_ids: Array.from(_vdSel) }, _getVdSubPayload());
  const r = await api('POST', '/accounts/' + _vdAccId + '/videos/batch-download', payload);
  if (!r.ok) {
    toast('下载失败: ' + (r.error || ''), 'err');
    btn.disabled = false;
    btn.innerHTML = '下载选中 (<span id="vdSelCount">' + _vdSel.size + '</span>)';
    return;
  }

  toast(r.queued + ' 个视频已开始下载', 'ok');

  const routing = r.routing;
  if (routing) {
    const sourceLabels = {
      'account_static': '账户固定代理',
      'system_paid': '系统付费动态代理',
      'system_free': '系统免费动态代理',
      'direct': '直连',
      'failed': '路由失败',
    };
    const source = sourceLabels[routing.source] || routing.source || '未知';
    let routingMsg = '本次线路: ' + source;
    if (routing.provider) routingMsg += ' | ' + routing.provider;
    if (routing.warnings && routing.warnings.length > 0) {
      routingMsg += ' | 注意：' + routing.warnings.join(', ');
    }
    setTimeout(() => {
      toast(routingMsg, routing.source === 'direct' || routing.source === 'failed' ? 'warning' : 'info');
    }, 500);
  }

  _vdShowDlBar(r.task_id, r.queued);
  btn.innerHTML = '下载选中 (<span id="vdSelCount">' + _vdSel.size + '</span>)';
  btn.disabled = true;
  await vdLoad();
}

function _vdShowDlBar(taskId, total) {
  const bar = document.getElementById('vdDlBar');
  bar.classList.add('show');
  document.getElementById('vdDlLabel').textContent = '正在下载 0/' + total + ' ...';
  document.getElementById('vdDlPercent').textContent = '0%';
  document.getElementById('vdDlFill').style.width = '0%';
  document.getElementById('vdDlStatus').textContent = '';

  if (window._vdDlPollTimerId) clearInterval(window._vdDlPollTimerId);
  const timerId = setInterval(() => _vdPollDlTask(taskId, total), 3000);
  // Expose to external close modal so it can be cleared
  window._vdDlPollTimerId = timerId;
}

async function _vdPollDlTask(taskId, total) {
  try {
    const t = await api('GET', '/download-tasks/' + taskId);
    if (t.error) {
      if (t._httpStatus === 429) return;
      _vdDlDone('查询失败: ' + t.error);
      return;
    }
    const pct = total > 0 ? Math.round((t.completed / total) * 100) : 0;
    document.getElementById('vdDlLabel').textContent =
      (t.status === 'done' ? '下载完成' : t.status === 'error' ? '下载出错' : '正在下载') +
      ' ' + t.completed + '/' + total;
    document.getElementById('vdDlPercent').textContent = pct + '%';
    document.getElementById('vdDlFill').style.width = pct + '%';
    document.getElementById('vdDlStatus').textContent = t.current_video || '';
    if (t.status === 'done') {
      _vdDlDone('下载完成: 成功 ' + t.success + ', 失败 ' + t.failed);
      toast('下载完成: 成功 ' + t.success + ' 个, 失败 ' + t.failed + ' 个', t.failed > 0 ? 'err' : 'ok');
    } else if (t.status === 'error') {
      _vdDlDone('下载异常: ' + (t.error || ''));
      toast('下载异常: ' + (t.error || ''), 'err');
    }
  } catch (e) {
    // 网络错误时继续轮询，不中断
  }
}

export function _vdDlDone(msg) {
  const timerId = window._vdDlPollTimerId;
  if (timerId) { clearInterval(timerId); window._vdDlPollTimerId = null; }
  const dlStatus = document.getElementById('vdDlStatus');
  const dlFill = document.getElementById('vdDlFill');
  const btn = document.getElementById('vdBatchBtn');
  if (dlStatus) dlStatus.textContent = msg;
  if (dlFill) dlFill.style.width = '100%';
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '下载选中 (<span id="vdSelCount">' + _vdSel.size + '</span>)';
  }
  _vdSel.clear();
  _updateVdSelCount();
  vdLoad();
  const dlBar = document.getElementById('vdDlBar');
  if (dlBar) setTimeout(() => dlBar.classList.remove('show'), 5000);
}
