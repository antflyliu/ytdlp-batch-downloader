// ── Video Detail Modal ───────────────────────────────────────────────
// Full-screen video list with search, sort, pagination, and batch download.

import { api } from '../api.js';
import { esc } from '../utils/format.js';
import { fmtDuration } from '../utils/format.js';
import { toast, openModal, closeModal } from './ui.js';
import { _vdAccId, _vdPage, _vdSel, _gConfig, setVdAccId, setVdPage, setVdSelClear } from './state.js';
import { I18n } from '../../static/js/i18n.js';

/** 重置视频详情表格滚动位置，避免横向滚动停留在末端导致首列只剩一条边线。 */
function resetVdTableScroll() {
  const wrap = document.querySelector('#modalVideoDetail .mvd-table-scroll');
  if (!wrap) return;
  wrap.scrollLeft = 0;
  wrap.scrollTop = 0;
}

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
    toast(I18n.t('common.pageLoading'), 'warning');
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
  resetVdTableScroll();
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
    const msg = (res && res.error) ? String(res.error) : I18n.t('video.loadFailed');
    if (res && res._httpStatus === 429) {
      toast(I18n.t('video.rateLimitHint'), 'warning');
    } else {
      toast(msg, 'err');
    }
    const _s = (id) => { const e = document.getElementById(id); if (e) e.textContent = arguments[1]; };
    _s('vdTotal', I18n.t('video.totalVideos').replace('{n}', '—')); _s('vdPageInfo', I18n.t('video.pageInfo'));
    const _d = (id, v) => { const e = document.getElementById(id); if (e) e.disabled = v; };
    _d('vdPrevBtn', true); _d('vdNextBtn', true);
    tbody.innerHTML =
      '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:32px;line-height:1.6">' +
      esc(msg) + '<br><span style="font-size:12px;opacity:.85">' + I18n.t('video.rateLimitHint') + '</span></td></tr>';
    _updateVdSelCount();
    resetVdTableScroll();
    return;
  }
  const _s2 = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
  const _d2 = (id, v) => { const e = document.getElementById(id); if (e) e.disabled = v; };
  _s2('vdTotal', I18n.t('video.totalVideos').replace('{n}', res.total)); _s2('vdPageInfo', I18n.t('video.pageInfo').replace('{p}', res.page).replace('{t}', res.pages));
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
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:32px">' + I18n.t('video.noData') + '</td></tr>';
    _updateVdSelCount();
    resetVdTableScroll();
    return;
  }
  tbody.innerHTML = res.videos.map(v => {
    const sel = _vdSel.has(v.id) ? 'checked' : '';
    const dlTag = v.download_status === 'downloaded'
      ? '<span class="tag tag-downloaded">' + I18n.t('video.tagDownloaded') + '</span>'
      : v.download_status === 'downloading'
      ? '<span class="tag tag-downloading">' + I18n.t('video.tagDownloading') + '</span>'
      : v.download_status === 'failed'
      ? '<span class="tag tag-download-failed">' + I18n.t('video.tagFailed') + '</span>'
      : '<span class="tag tag-download-pending">' + I18n.t('video.tagPending') + '</span>';
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
 ? ' <button type="button" class="btn-sm" style="color:var(--accent)" onclick="chTriggerClip(' + v.id + ',this)" title="' + I18n.t('video.clipTrigger') + '">✂</button>'
 : '') +
'</td>' +
    '</tr>';
  }).join('');
  const allChecked = res.videos.length > 0 && res.videos.every(v => _vdSel.has(v.id));
  const ca = document.getElementById('vdCheckAll');
  if (ca) ca.checked = allChecked;
  _updateVdSelCount();
  resetVdTableScroll();
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
  if (!confirm(I18n.t('video.retryConfirm').replace('{n}', count))) return;
  retryBtn.disabled = true;
  retryBtn.innerHTML = '<span class="spinner"></span> ' + I18n.t('video.retryInProgress') + '...';
  try {
    // 收集当前表格行 ID（当前页），兼容少量失败场景
    const rows = document.querySelectorAll('#vdTbody tr[data-id]');
    const videoIds = [...rows].map(r => parseInt(r.dataset.id)).filter(id => !isNaN(id));
    if (videoIds.length === 0) {
      toast(I18n.t('video.noRetryable'), 'warning');
      retryBtn.disabled = false;
      retryBtn.innerHTML = I18n.t('video.retryDone').replace('{n}', 0);
      return;
    }
    const r = await api('POST', '/api/videos/retry', {
      video_ids: videoIds,
      account_id: _vdAccId,
    });
    if (r.ok) {
      toast(I18n.t('video.retryDone').replace('{n}', r.retried), 'ok');
      setVdPage(1);
      setVdSelClear();
      vdLoad();
    } else {
      toast(I18n.t('video.retryFailed').replace('{e}', r.error || ''), 'err');
    }
  } catch (e) {
    toast(I18n.t('video.retryRequestFailed').replace('{e}', e.message || ''), 'err');
  }
  retryBtn.disabled = false;
  retryBtn.innerHTML = I18n.t('video.retryCount').replace('{n}', count);
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

/**
 * 批量下载按钮文案：必须用 JS 替换 {n}；不可对整颗按钮使用 data-i18n（否则会破坏子节点且无法插值）。
 */
function _updateVdSelCount() {
  const label = document.getElementById('vdBatchBtnLabel');
  const b = document.getElementById('vdBatchBtn');
  if (label) {
    label.textContent = I18n.t('video.btnDownloadSelected').replace('{n}', String(_vdSel.size));
  }
  if (b) b.disabled = _vdSel.size === 0;
}

/** 语言切换后若视频详情弹层已打开，刷新批量按钮文案 */
export function refreshVdBatchButtonLabel() {
  _updateVdSelCount();
}

export function _updateVdSubLabelText() {
  const toggle = document.getElementById('vdSubToggle');
  const label = document.getElementById('vdSubLabel');
  if (!toggle || !label) return;
  label.textContent = toggle.checked ? I18n.t('video.subtitleOn') : I18n.t('video.subtitleOff');
}

export function _getVdSubPayload() {
  const on = document.getElementById('vdSubToggle').checked;
  const subLangs = (_gConfig && _gConfig.default_sub_langs) || 'zh-Hans,en';
  return on ? { sub_langs: subLangs, no_subs: false } : { no_subs: true };
}

export async function vdBatchDownload() {
  if (_vdSel.size === 0) return;
  const btn = document.getElementById('vdBatchBtn');
  const lbl = document.getElementById('vdBatchBtnLabel');
  btn.disabled = true;
  if (lbl) {
    lbl.innerHTML = '<span class="spinner"></span> <span>' + I18n.t('video.submitting') + '...</span>';
  }

  const payload = Object.assign({ video_ids: Array.from(_vdSel) }, _getVdSubPayload());
  const r = await api('POST', '/accounts/' + _vdAccId + '/videos/batch-download', payload);
  if (!r.ok) {
    toast(I18n.t('video.downloadFailed').replace('{e}', r.error || ''), 'err');
    btn.disabled = false;
    _updateVdSelCount();
    return;
  }

  toast(I18n.t('video.videosQueued').replace('{n}', r.queued), 'ok');

  const routing = r.routing;
  if (routing) {
    const sourceLabels = {
      'account_static': I18n.t('video.routingAccountStatic'),
      'system_paid': I18n.t('video.routingSystemPaid'),
      'system_free': I18n.t('video.routingSystemFree'),
      'direct': I18n.t('video.routingDirect'),
      'failed': I18n.t('video.routingFailed'),
    };
    const source = sourceLabels[routing.source] || routing.source || I18n.t('video.routingUnknown');
    let routingMsg = I18n.t('video.routingCurrent').replace('{s}', source);
    if (routing.provider) routingMsg += ' | ' + routing.provider;
    if (routing.warnings && routing.warnings.length > 0) {
      routingMsg += ' | ' + I18n.t('video.routingWarning') + ' ' + routing.warnings.join(', ');
    }
    setTimeout(() => {
      toast(routingMsg, routing.source === 'direct' || routing.source === 'failed' ? 'warning' : 'info');
    }, 500);
  }

  _vdShowDlBar(r.task_id, r.queued);
  _updateVdSelCount();
  btn.disabled = true;
  await vdLoad();
}

function _vdShowDlBar(taskId, total) {
  const bar = document.getElementById('vdDlBar');
  bar.classList.add('show');
  document.getElementById('vdDlLabel').textContent = I18n.t('video.downloadingN').replace('{n}', '0/' + total + ' ...');
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
      _vdDlDone(I18n.t('video.queryFailed').replace('{e}', t.error));
      return;
    }
    const pct = total > 0 ? Math.round((t.completed / total) * 100) : 0;
    const statusLabel = t.status === 'done' ? I18n.t('video.downlCompleteStatus') : t.status === 'error' ? I18n.t('video.downloadErrorStatus') : I18n.t('video.downloadingStatus');
    document.getElementById('vdDlLabel').textContent =
      statusLabel + ' ' + t.completed + '/' + total;
    document.getElementById('vdDlPercent').textContent = pct + '%';
    document.getElementById('vdDlFill').style.width = pct + '%';
    document.getElementById('vdDlStatus').textContent = t.current_video || '';
    if (t.status === 'done') {
      _vdDlDone(I18n.t('video.batchDone').replace('{s}', t.success).replace('{f}', t.failed));
      toast(I18n.t('video.batchDone').replace('{s}', t.success).replace('{f}', t.failed), t.failed > 0 ? 'err' : 'ok');
    } else if (t.status === 'error') {
      _vdDlDone(I18n.t('video.downloadAbnormal').replace('{e}', t.error || ''));
      toast(I18n.t('video.downloadAbnormal').replace('{e}', t.error || ''), 'err');
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
  if (btn) btn.disabled = false;
  _vdSel.clear();
  _updateVdSelCount();
  vdLoad();
  const dlBar = document.getElementById('vdDlBar');
  if (dlBar) setTimeout(() => dlBar.classList.remove('show'), 5000);
}
