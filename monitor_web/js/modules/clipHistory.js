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
    openModal('modalClipHistory');
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
  select.innerHTML = '<option value="">全部账户</option>' +
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
  if (!tbody) return;

  tbody.innerHTML = '';
  if (empty) empty.style.display = 'none';
  if (loading) loading.style.display = 'block';

  api('GET', '/clips?' + params.toString()).then(data => {
    if (loading) loading.style.display = 'none';
    if (!data || !Array.isArray(data.tasks)) {
      toast('加载失败', 'err');
      return;
    }
    _chTotal = data.total || 0;
    const tasks = data.tasks;
    if (tasks.length === 0) {
      if (empty) empty.style.display = 'block';
      tbody.innerHTML = '';
      _updatePagination(0);
      return;
    }
    if (empty) empty.style.display = 'none';
    tbody.innerHTML = tasks.map(t => {
      const statusClass = t.status === 'done' ? 'tag-success'
        : t.status === 'running' ? 'tag-accent'
        : t.status === 'error' ? 'tag-error'
        : 'tag-muted';
      const statusLabel = t.status === 'done' ? '完成'
        : t.status === 'running' ? '进行中'
        : t.status === 'error' ? '失败'
        : '等待';
      return `<tr>
        <td class="td-mono">${t.id}</td>
        <td style="font-size:12px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(t.account_name)}">${esc(t.account_name)}</td>
        <td style="font-size:12px;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(t.video_title)}">${esc(t.video_title)}</td>
        <td><span class="tag ${statusClass}">${statusLabel}</span></td>
        <td class="td-mono">${t.clip_count ?? 0}</td>
        <td class="td-mono">${t.collection_count ?? 0}</td>
        <td class="td-mono" style="font-size:11px">${fmtTime(t.created_at)}</td>
        <td>
          <div class="actions">
            <button class="btn-sm" onclick="chViewTask(${t.id})" title="查看">详情</button>
          </div>
        </td>
      </tr>`;
    }).join('');
    _updatePagination(data.total || 0);

    const totalEl = document.getElementById('chTotal');
    if (totalEl) totalEl.textContent = `共 ${data.total} 条`;
  }).catch(() => {
    if (loading) loading.style.display = 'none';
    toast('加载失败', 'err');
  });
}

function _updatePagination(total) {
  const totalPages = Math.ceil(total / 20);
  const pageInfo = document.getElementById('chPageInfo');
  const prevBtn = document.getElementById('chPrevBtn');
  const nextBtn = document.getElementById('chNextBtn');
  if (pageInfo) pageInfo.textContent = `第 ${_chPage} / ${totalPages || 1} 页`;
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
      toast(`切片任务 #${resp.task_id} 已创建`, 'ok');
      openModal('modalClipHistory');
    } else {
      toast((resp && resp.error) ? String(resp.error) : '创建失败', 'err');
      btnEl.disabled = false;
      btnEl.textContent = '✂';
    }
  } catch (e) {
    toast('请求失败: ' + String(e), 'err');
    btnEl.disabled = false;
    btnEl.textContent = '✂';
  }
}

const STATUS_LABELS = {
  done: '已完成', running: '进行中', error: '失败', pending: '等待中'
};

function _fmtDur(seconds) {
  if (!seconds || seconds < 0) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m + ':' + String(s).padStart(2, '0');
}

async function chViewTask(taskId) {
  const task = await api('GET', '/clips/' + taskId);
  if (!task || task.error) {
    toast('加载任务详情失败', 'err');
    return;
  }

  // Header
  document.getElementById('ccdTaskId').textContent = task.id;
  document.getElementById('ccdVideoTitle').textContent = task.video_title || '未知视频';

  const statusEl = document.getElementById('ccdStatus');
  statusEl.textContent = STATUS_LABELS[task.status] || task.status;
  statusEl.className = 'ccd-badge ' + (task.status || 'pending');

  document.getElementById('ccdClipCount').textContent = (task.clip_count ?? 0) + ' 个切片';
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
      const title = esc(clip.generated_title || clip.title || '切片 #' + clip.id);
      const path = clip.clip_path || '';
      _clipPaths[clip.id] = path;  // store raw path in JS object
      return '<div class="ccd-item ccd-clip-item">' +
        '<div class="ccd-item-main">' +
          '<div class="ccd-item-title" title="' + title + '">' + title + '</div>' +
          '<div class="ccd-item-sub">' +
            '<span class="ccd-duration">' + dur + '</span>' +
            '<span class="ccd-dot"></span>' +
            '<span class="ccd-score-label">评分 ' + score.toFixed(1) + '</span>' +
          '</div>' +
        '</div>' +
        '<span class="ccd-score-badge ' + scoreClass + '">' + score.toFixed(1) + '</span>' +
        '<button class="ccd-play-btn" title="播放" onclick="ccdPlay(\'' + clip.id + '\')">' +
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
      const title = esc(col.title || '合集 #' + col.id);
      const desc = esc(col.description || '');
      const path = col.collection_path || '';
      return '<div class="ccd-item ccd-collection-item">' +
        '<div class="ccd-item-main">' +
          '<div class="ccd-item-title" title="' + title + '">' + title + '</div>' +
          (desc ? '<div class="ccd-item-desc" title="' + desc + '">' + desc + '</div>' : '') +
        '</div>' +
        '<button class="ccd-play-btn" title="播放合集" onclick="ccdPlay(\'' + encodeURIComponent(path) + '\')">' +
          '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4 2.5l10 5.5-10 5.5V2.5z"/></svg>' +
        '</button>' +
      '</div>';
    }).join('');
  }

  openModal('modalClipDetail');
}

window.ccdPlay = function(clipIdOrPath) {
  if (!clipIdOrPath) { toast('文件路径无效', 'err'); return; }
  var path;
  if (_clipPaths[clipIdOrPath] !== undefined) {
    // clips: 通过 clip ID 查表（避免 data-path 属性编码问题）
    path = _clipPaths[clipIdOrPath];
  } else {
    // collections: 传入的是 encodeURIComponent 编码后的路径
    path = decodeURIComponent(clipIdOrPath);
  }
  if (!path) { toast('文件路径无效', 'err'); return; }
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
  if (!player || !video) { toast('播放器未初始化', 'err'); return; }

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