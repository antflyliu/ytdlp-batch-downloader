// ── Clip History Module ─────────────────────────────────────────
import { api } from '../api.js';
import { esc, fmtTime } from '../utils/format.js';
import { toast, openModal, closeModal } from './ui.js';

let _chPage = 1;
let _chTotal = 0;
let _chAccounts = [];
let _clipPaths = {};  // id -> clip_path (raw JS string, no HTML attr encoding)

export function openClipHistory() {
  _chPage = 1;
  _loadAccountOptions().then(() => {
    chLoad();
  });
}

async function _loadAccountOptions() {
  const accounts = await api('GET', '/accounts');
  if (!Array.isArray(accounts)) return;
  _chAccounts = accounts;
  const select = document.getElementById('chAccountFilter');
  if (!select) return;
  // Preserve current selection
  const current = select.value;
  select.innerHTML = '<option value="">' + I18n.t('page.clipHistory.filterAccount') + '</option>' +
    accounts.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join('');
  select.value = current;
}

function chLoad() {
  const accountId = document.getElementById('chAccountFilter')?.value || '';
  const status = document.getElementById('chStatusFilter')?.value || '';
  const params = new URLSearchParams();
  if (accountId) params.set('account_id', accountId);
  if (status) params.set('status', status);
  params.set('limit', '20');
  params.set('offset', String((_chPage - 1) * 20));

  const tbody = document.getElementById('chTbody');
  const empty = document.getElementById('chEmpty');
  const loading = document.getElementById('chLoading');
  const tableWrap = document.getElementById('chTableWrap');
  const pagBar = document.getElementById('chPagination');
  if (!tbody) return;

  tbody.innerHTML = '';
  if (empty) empty.style.display = 'none';
  if (tableWrap) tableWrap.style.display = 'block';
  if (loading) loading.style.display = 'block';

  api('GET', '/clips?' + params.toString()).then(data => {
    if (loading) loading.style.display = 'none';
    if (!data || !Array.isArray(data.tasks)) {
      toast(I18n.t('clip.loadFailed'), 'err');
      return;
    }
    _chTotal = data.total || 0;
    const tasks = data.tasks;
    if (tasks.length === 0) {
      if (empty) empty.style.display = 'block';
      if (tableWrap) tableWrap.style.display = 'none';
      if (pagBar) pagBar.style.display = 'none';
      tbody.innerHTML = '';
      _updatePagination(0);
      return;
    }
    if (empty) empty.style.display = 'none';
    if (tableWrap) tableWrap.style.display = 'block';
    if (pagBar) pagBar.style.display = '';
    tbody.innerHTML = tasks.map(t => {
      const statusClass = t.status === 'done' ? 'tag-success'
        : t.status === 'running' ? 'tag-accent'
        : t.status === 'error' ? 'tag-error'
        : 'tag-muted';
      const statusLabel = t.status === 'done' ? I18n.t('page.clipHistory.statusDone')
        : t.status === 'running' ? I18n.t('page.clipHistory.statusRunning')
        : t.status === 'error' ? I18n.t('page.clipHistory.statusError')
        : I18n.t('page.clipHistory.statusPending');
      return `<tr>
        <td class="td-mono">${t.id}</td>
        <td class="td-name td-clip-account" title="${esc(t.account_name)}">${esc(t.account_name)}</td>
        <td class="td-clip-video-title" title="${esc(t.video_title)}">${esc(t.video_title)}</td>
        <td><span class="tag ${statusClass}">${statusLabel}</span></td>
        <td class="td-mono">${t.clip_count ?? 0}</td>
        <td class="td-mono">${t.collection_count ?? 0}</td>
        <td class="td-mono" style="font-size:11px">${fmtTime(t.created_at)}</td>
        <td>
          <div class="actions">
            <button type="button" class="btn-sm" onclick="window.chViewTask(${t.id})" title="${I18n.t('common.view')}">${I18n.t('clip.btnDetail')}</button>
          </div>
        </td>
      </tr>`;
    }).join('');
    _updatePagination(data.total || 0);

    const totalEl = document.getElementById('chTotal');
    if (totalEl) totalEl.textContent = I18n.t('batch.total').replace('{n}', data.total);
  }).catch(() => {
    if (loading) loading.style.display = 'none';
    if (tableWrap) tableWrap.style.display = 'block';
    toast(I18n.t('clip.loadFailed'), 'err');
  });
}

function _updatePagination(total) {
  const totalPages = Math.ceil(total / 20);
  const pageInfo = document.getElementById('chPageInfo');
  const prevBtn = document.getElementById('chPrevBtn');
  const nextBtn = document.getElementById('chNextBtn');
  if (pageInfo) pageInfo.textContent = I18n.t('video.pageInfo').replace('{p}', _chPage).replace('{t}', totalPages || 1);
  if (prevBtn) prevBtn.disabled = _chPage <= 1;
  if (nextBtn) nextBtn.disabled = _chPage >= totalPages;
}

function chGoPage(dir) {
  const totalPages = Math.ceil(_chTotal / 20);
  const nextPage = _chPage + dir;
  if (nextPage < 1 || nextPage > totalPages) return;
  _chPage = nextPage;
  chLoad();
}

async function chTriggerClip(monitorVideoId, btnEl) {
  // Trigger clip for a specific video from the video detail table
  if (!btnEl) return;
  btnEl.disabled = true;
  btnEl.textContent = '...';
  try {
    const resp = await api('POST', '/clips', { video_id: monitorVideoId });
    if (resp && resp.ok) {
      toast(I18n.t('clip.taskCreated').replace('{id}', resp.task_id), 'ok');
      window.location.hash = '/clip-history';
      openClipHistory();
    } else {
      toast((resp && resp.error) ? String(resp.error) : I18n.t('clip.createFailed'), 'err');
      btnEl.disabled = false;
      btnEl.textContent = '✂';
    }
  } catch (e) {
    toast(I18n.t('clip.requestFailed').replace('{e}', String(e)), 'err');
    btnEl.disabled = false;
    btnEl.textContent = '✂';
  }
}

const STATUS_LABELS = {
  done: I18n.t('clip.clipDone'), running: I18n.t('clip.clipRunning'), error: I18n.t('clip.clipError'), pending: I18n.t('clip.clipPending')
};

function _fmtDur(seconds) {
  if (!seconds || seconds < 0) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m + ':' + String(s).padStart(2, '0');
}

async function chViewTask(taskId) {
  if (!document.getElementById('modalClipDetail')) {
    toast(I18n.t('clip.pageLoading'), 'warning');
    return;
  }
  const task = await api('GET', '/clips/' + taskId);
  if (!task || task.error) {
    toast(I18n.t('clip.loadTaskFailed'), 'err');
    return;
  }

  // Header（#ccdTaskId 须在独立节点上，勿放在仅含 data-i18n 的父级内，否则 I18n.apply 会清空子节点）
  const ccdTaskIdEl = document.getElementById('ccdTaskId');
  const ccdVideoTitleEl = document.getElementById('ccdVideoTitle');
  if (!ccdTaskIdEl || !ccdVideoTitleEl) {
    toast(I18n.t('clip.loadTaskFailed'), 'err');
    return;
  }
  ccdTaskIdEl.textContent = task.id;
  ccdVideoTitleEl.textContent = task.video_title || I18n.t('clip.unknownVideo');

  const statusEl = document.getElementById('ccdStatus');
  statusEl.textContent = STATUS_LABELS[task.status] || task.status;
  statusEl.className = 'ccd-badge ' + (task.status || 'pending');

  document.getElementById('ccdClipCount').textContent = I18n.t('clip.clipCount').replace('{n}', task.clip_count ?? 0);
  document.getElementById('ccdCreatedAt').textContent = fmtTime(task.created_at);

  // Clips
  const clips = task.clips || [];
  document.getElementById('ccdClipsCount').textContent = clips.length;
  const clipsEmpty = document.getElementById('ccdClipsEmpty');
  const clipsList = document.getElementById('ccdClipsList');

  if (clips.length === 0) {
    clipsEmpty.style.display = 'block';
    clipsList.innerHTML = '';
  } else {
    clipsEmpty.style.display = 'none';
    clipsList.innerHTML = clips.map(function(clip) {
      const score = clip.final_score || 0;
      const scoreClass = score >= 8 ? 'high' : score >= 6 ? 'medium' : 'low';
      const dur = _fmtDur((clip.end_time || 0) - (clip.start_time || 0));
      const title = esc(clip.generated_title || clip.title || I18n.t('clip.btnClip') + ' #' + clip.id);
      const path = clip.clip_path || '';
      _clipPaths[clip.id] = path;  // store raw path in JS object
      return '<div class="ccd-item ccd-clip-item">' +
        '<div class="ccd-item-main">' +
          '<div class="ccd-item-title" title="' + title + '">' + title + '</div>' +
          '<div class="ccd-item-sub">' +
            '<span class="ccd-duration">' + dur + '</span>' +
            '<span class="ccd-dot"></span>' +
            '<span class="ccd-score-label">' + I18n.t('clip.scoreLabel').replace('{s}', score.toFixed(1)) + '</span>' +
          '</div>' +
        '</div>' +
        '<span class="ccd-score-badge ' + scoreClass + '">' + score.toFixed(1) + '</span>' +
        '<button class="ccd-play-btn" title="' + I18n.t('clip.clipPlay') + '" onclick="ccdPlay(\'' + clip.id + '\')">' +
          '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 2.5l10 5.5-10 5.5V2.5z"/></svg>' +
        '</button>' +
      '</div>';
    }).join('');
  }

  // Collections
  const collections = task.collections || [];
  document.getElementById('ccdCollectionsCount').textContent = collections.length;
  const collectionsEmpty = document.getElementById('ccdCollectionsEmpty');
  const collectionsList = document.getElementById('ccdCollectionsList');

  if (collections.length === 0) {
    collectionsEmpty.style.display = 'block';
    collectionsList.innerHTML = '';
  } else {
    collectionsEmpty.style.display = 'none';
    collectionsList.innerHTML = collections.map(function(col) {
      const title = esc(col.title || I18n.t('batch.btnReopen') + ' #' + col.id);
      const desc = esc(col.description || '');
      const path = col.collection_path || '';
      return '<div class="ccd-item ccd-collection-item">' +
        '<div class="ccd-item-main">' +
          '<div class="ccd-item-title" title="' + title + '">' + title + '</div>' +
          (desc ? '<div class="ccd-item-desc" title="' + desc + '">' + desc + '</div>' : '') +
        '</div>' +
        '<button class="ccd-play-btn" title="' + I18n.t('clip.clipPlay') + '" onclick="ccdPlay(\'' + encodeURIComponent(path) + '\')">' +
          '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 2.5l10 5.5-10 5.5V2.5z"/></svg>' +
        '</button>' +
      '</div>';
    }).join('');
  }

  openModal('modalClipDetail');
}

window.ccdPlay = function(clipIdOrPath) {
  if (!clipIdOrPath) { toast(I18n.t('clip.loadTaskFailed'), 'err'); return; }
  var path;
  if (_clipPaths[clipIdOrPath] !== undefined) {
    // clips: 通过 clip ID 查表（避免 data-path 属性编码问题）
    path = _clipPaths[clipIdOrPath];
  } else {
    // collections: 传入的是 encodeURIComponent 编码后的路径
    path = decodeURIComponent(clipIdOrPath);
  }
  if (!path) { toast(I18n.t('clip.loadTaskFailed'), 'err'); return; }
  // 构造相对路径：从 videos/ 开始
  var rel = path;
  var idx = rel.toLowerCase().indexOf('videos');
  if (idx !== -1) {
    rel = rel.substring(idx); // "videos\clips\..."
  }
  // 统一用正斜杠
  rel = rel.replace(/\\/g, '/');

  var player = document.getElementById('ccdPlayer');
  var video  = document.getElementById('ccdVideoEl');
  var body   = document.getElementById('ccdBody');
  if (!player || !video) { toast(I18n.t('clip.loadTaskFailed'), 'err'); return; }

  video.src = '/api/video-stream?path=' + encodeURIComponent(rel);
  video.load();
  player.style.display = 'flex';
  if (body) body.style.display = 'none';
};

window.ccdClosePlayer = function() {
  var player = document.getElementById('ccdPlayer');
  var video  = document.getElementById('ccdVideoEl');
  var body   = document.getElementById('ccdBody');
  if (video) { video.pause(); video.src = ''; }
  if (player) player.style.display = 'none';
  if (body) body.style.display = '';
};

// Expose to global
window.openClipHistory = openClipHistory;
window.chLoad = chLoad;
window.chGoPage = chGoPage;
window.chViewTask = chViewTask;
window.chTriggerClip = chTriggerClip;
window.init_clip_history_page = openClipHistory;
