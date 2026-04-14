// ── Batch Download Modal Component ────────────────────────────────
import { api, apiForm } from '../api.js';
import { esc } from '../utils/format.js';
import { toast } from '../modules/ui.js';

// ── DOM Helper (null-safe) ─────────────────────────────────────────
const el = (id) => document.getElementById(id);

// ── State ──────────────────────────────────────────────────────────
let _bdTaskId = null;
let _bdPollTimer = null;
let _bdUploadId = null;
let _bdPreviewUrls = [];
let _bdLastLogCount = 0;
let _bdRecentFilter = 'all';
let _bdState = 'idle'; // idle | running | cancelling

// ── Reset Helpers ──────────────────────────────────────────────────

export function bdResetUploadState() {
  _bdUploadId = null;
  _bdPreviewUrls = [];
  const bdDropIdle = el('bdDropIdle');     if (bdDropIdle) bdDropIdle.style.display = '';
  const bdDropSelected = el('bdDropSelected'); if (bdDropSelected) bdDropSelected.style.display = 'none';
  const bdDropzone = el('bdDropzone');     if (bdDropzone) bdDropzone.className = 'bd-dropzone';
  const bdFileError = el('bdFileError');   if (bdFileError) bdFileError.style.display = 'none';
  const bdFileName = el('bdFileName');     if (bdFileName) bdFileName.textContent = '';
  const bdUrlCount = el('bdUrlCount');     if (bdUrlCount) bdUrlCount.textContent = '';
  const bdFileInput = el('bdFileInput');   if (bdFileInput) bdFileInput.value = '';
}

export function bdResetProgressState() {
  _bdLastLogCount = 0;
  const bdProgressSection = el('bdProgressSection'); if (bdProgressSection) bdProgressSection.style.display = 'none';
  const bdComplete = el('bdComplete'); if (bdComplete) { bdComplete.style.display = 'none'; bdComplete.className = 'bd-complete'; }
  const bdTrackFill = el('bdTrackFill'); if (bdTrackFill) bdTrackFill.style.width = '0%';
  const bdPct = el('bdPct'); if (bdPct) bdPct.textContent = '0%';
  const bdCurrent = el('bdCurrent'); if (bdCurrent) bdCurrent.textContent = '';
  const bdCounter = el('bdCounter'); if (bdCounter) bdCounter.textContent = '';
  const bdTrackPulse = el('bdTrackPulse'); if (bdTrackPulse) bdTrackPulse.classList.remove('active');
  const bdLogText = el('bdLogText'); if (bdLogText) bdLogText.innerHTML = '';
  const bdLog = el('bdLog'); if (bdLog) bdLog.style.display = 'none';
  const bdLogToggle = el('bdLogToggle'); if (bdLogToggle) bdLogToggle.textContent = '▾ 展开详情';
}

// ── Open / Close ───────────────────────────────────────────────────

export function openBatchDownload() {
  _bdState = 'idle';
  _bdTaskId = null;
  if (_bdPollTimer) { clearInterval(_bdPollTimer); _bdPollTimer = null; }
  bdResetUploadState();
  bdResetProgressState();
  const bdStartBtn = el('bdStartBtn'); if (bdStartBtn) { bdStartBtn.style.display = ''; bdStartBtn.disabled = false; bdStartBtn.textContent = '▶ 开始下载'; }
  const bdCancelBtn = el('bdCancelBtn'); if (bdCancelBtn) { bdCancelBtn.textContent = '取消'; bdCancelBtn.disabled = false; }
  const bdConfig = el('bdConfig'); if (bdConfig) bdConfig.style.opacity = '';
  loadProxyPoolsForBatch();
  loadRecentBatchTasks();
  window.openModal('modalBatchDownload');
}

export function bdClose() {
  window.closeModal('modalBatchDownload');
}

// ── Proxy Pool Loader ──────────────────────────────────────────────

export function loadProxyPoolsForBatch() {
  api('GET', '/proxy-pools').then(r => {
    const sel = el('bdProxy');
    if (!sel) return;
    sel.innerHTML = '<option value="">（按系统默认路由）</option>';
    if (!Array.isArray(r)) return;
    r.forEach(p => {
      if (!p || !p.enabled) return;
      const opt = document.createElement('option');
      opt.value = String(p.id);
      opt.textContent = p.name + (p.proxy_url ? ' (' + p.proxy_url + ')' : '');
      sel.appendChild(opt);
    });
  });
}

// ── Format Switcher ────────────────────────────────────────────────

export function bdSwitchFmt(btn) {
  const bdFmt = el('bdFmt'); if (bdFmt) bdFmt.value = btn.dataset.fmt;
  document.querySelectorAll('.bd-pill').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  bdResetUploadState();
}

// ── File Upload ────────────────────────────────────────────────────

export function bdTriggerFile() {
  const bdFileInput = el('bdFileInput'); if (bdFileInput) bdFileInput.click();
}

export async function bdHandleFile(input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];
  const formData = new FormData();
  formData.append('file', file);
  const r = await apiForm('POST', '/batch/upload', formData);
  if (r && r.ok) {
    _bdUploadId = r.upload_id || null;
    _bdPreviewUrls = Array.isArray(r.preview_urls) ? r.preview_urls : [];
    const bdFileName = el('bdFileName'); if (bdFileName) bdFileName.textContent = r.filename || file.name;
    const bdUrlCount = el('bdUrlCount'); if (bdUrlCount) bdUrlCount.textContent =
      (r.url_count || 0) + ' 条 URL' + (_bdPreviewUrls.length ? '（预览 ' + _bdPreviewUrls.length + ' 条）' : '');
    const bdDropIdle = el('bdDropIdle'); if (bdDropIdle) bdDropIdle.style.display = 'none';
    const bdDropSelected = el('bdDropSelected'); if (bdDropSelected) bdDropSelected.style.display = '';
    const bdDropzone = el('bdDropzone'); if (bdDropzone) bdDropzone.className = 'bd-dropzone selected';
    const bdFileError = el('bdFileError'); if (bdFileError) bdFileError.style.display = 'none';
    return;
  }
  bdResetUploadState();
  const bdDropzone2 = el('bdDropzone');
  const bdFileError2 = el('bdFileError');
  if (r && !r._fetchFailed) {
    if (bdDropzone2) bdDropzone2.className = 'bd-dropzone error';
    if (bdFileError2) { bdFileError2.textContent = '❌ ' + ((r && r.error) || '解析失败'); bdFileError2.style.display = ''; }
    return;
  }
  if (bdDropzone2) bdDropzone2.className = 'bd-dropzone error';
  if (bdFileError2) { bdFileError2.textContent = '❌ 网络错误'; bdFileError2.style.display = ''; }
}

// ── Path Modal (injected styles + helper) ─────────────────────────

(function () {
  let styleInjected = false;

  function injectStyle() {
    if (styleInjected) return;
    styleInjected = true;
    const s = document.createElement('style');
    s.id = 'bd-path-modal-style';
    s.textContent = `
      .bd-path-overlay {
        position: fixed; inset: 0; z-index: 9999;
        background: rgba(0,0,0,0.72); backdrop-filter: blur(6px);
        display: flex; align-items: center; justify-content: center;
        animation: bd-path-fadein 0.18s ease-out;
      }
      .bd-path-overlay.closing { animation: bd-path-fadeout 0.15s ease-in forwards; }
      @keyframes bd-path-fadein { from { opacity: 0; } to { opacity: 1; } }
      @keyframes bd-path-fadeout { from { opacity: 1; } to { opacity: 0; } }
      .bd-path-card {
        background: #1c2333;
        border: 1px solid #2a3549;
        border-radius: 12px;
        width: 520px;
        max-width: calc(100vw - 32px);
        box-shadow: 0 24px 64px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.04);
        overflow: hidden;
        animation: bd-path-rise 0.2s cubic-bezier(0.16,1,0.3,1);
      }
      @keyframes bd-path-rise { from { opacity: 0; transform: translateY(12px) scale(0.97); } to { opacity: 1; transform: none; } }
      .bd-path-card-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 14px 20px;
        border-bottom: 1px solid #2a3549;
      }
      .bd-path-card-title {
        font-size: 14px; font-weight: 600; color: #e2e8f0;
        display: flex; align-items: center; gap: 8px;
      }
      .bd-path-card-title svg { opacity: 0.6; flex-shrink: 0; }
      .bd-path-card-close {
        width: 28px; height: 28px; border-radius: 6px;
        background: transparent; border: none; cursor: pointer;
        color: #64748b; font-size: 16px; line-height: 1;
        display: flex; align-items: center; justify-content: center;
        transition: background 0.15s, color 0.15s;
      }
      .bd-path-card-close:hover { background: #232d42; color: #e2e8f0; }
      .bd-path-card-body { padding: 20px; }
      .bd-path-card-label {
        font-size: 11px; font-weight: 600; color: #64748b;
        text-transform: uppercase; letter-spacing: 0.6px;
        margin-bottom: 8px;
      }
      .bd-path-input-wrap {
        display: flex; gap: 8px; align-items: center;
      }
      .bd-path-input {
        flex: 1; background: #141824; border: 1px solid #2a3549;
        border-radius: 8px; padding: 9px 12px;
        color: #e2e8f0; font-size: 13px; font-family: Consolas, 'Courier New', monospace;
        outline: none; transition: border-color 0.15s, box-shadow 0.15s;
      }
      .bd-path-input:focus {
        border-color: #6366f1;
        box-shadow: 0 0 0 3px rgba(99,102,241,0.15);
      }
      .bd-path-hint {
        font-size: 11px; color: #475569; margin-top: 8px; line-height: 1.5;
      }
      .bd-path-card-footer {
        display: flex; justify-content: flex-end; gap: 8px;
        padding: 12px 20px;
        border-top: 1px solid #1e293b;
        background: #141824;
      }
      .bd-path-btn {
        padding: 7px 18px; border-radius: 8px;
        font-size: 13px; font-weight: 500; cursor: pointer;
        border: none; transition: all 0.15s;
      }
      .bd-path-btn-cancel {
        background: transparent; color: #64748b; border: 1px solid #2a3549;
      }
      .bd-path-btn-cancel:hover { background: #1c2333; color: #94a3b8; border-color: #334155; }
      .bd-path-btn-confirm {
        background: #6366f1; color: #fff;
      }
      .bd-path-btn-confirm:hover { background: #5558e3; }
      .bd-path-btn-confirm:active { transform: scale(0.98); }
    `;
    document.head.appendChild(s);
  }

  function openPathModal(title, icon, placeholder, currentValue, hint, onConfirm) {
    injectStyle();

    const overlay = document.createElement('div');
    overlay.className = 'bd-path-overlay';
    overlay.innerHTML = `
      <div class="bd-path-card" onclick="event.stopPropagation()">
        <div class="bd-path-card-header">
          <div class="bd-path-card-title">${icon}<span>${title}</span></div>
          <button class="bd-path-card-close" id="bdPathCloseBtn">✕</button>
        </div>
        <div class="bd-path-card-body">
          <div class="bd-path-card-label">路径</div>
          <div class="bd-path-input-wrap">
            <input class="bd-path-input" id="bdPathInput" value="${currentValue || ''}" placeholder="${placeholder}" spellcheck="false" autocomplete="off">
          </div>
          ${hint ? `<div class="bd-path-hint">${hint}</div>` : ''}
        </div>
        <div class="bd-path-card-footer">
          <button class="bd-path-btn bd-path-btn-cancel" id="bdPathCancelBtn">取消</button>
          <button class="bd-path-btn bd-path-btn-confirm" id="bdPathConfirmBtn">确认</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const input = document.getElementById('bdPathInput');
    const closeBtn = document.getElementById('bdPathCloseBtn');
    const cancelBtn = document.getElementById('bdPathCancelBtn');
    const confirmBtn = document.getElementById('bdPathConfirmBtn');

    input.focus();
    if (currentValue) { input.select(); }

    function close() {
      overlay.classList.add('closing');
      overlay.addEventListener('animationend', function () { overlay.remove(); }, { once: true });
    }

    function confirm() {
      const val = input.value;
      close();
      onConfirm(val);
    }

    closeBtn.addEventListener('click', close);
    cancelBtn.addEventListener('click', close);
    confirmBtn.addEventListener('click', confirm);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') confirm();
      if (e.key === 'Escape') close();
    });
    overlay.addEventListener('click', close);
  }

  window.bdBrowsePathModal = function () {
    const bdOutputPath = document.getElementById('bdOutputPath');
    const current = bdOutputPath ? bdOutputPath.value.trim() : '';
    openPathModal(
      '保存路径',
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>',
      '例如：D:\\Downloads\\Videos',
      current,
      '留空则使用全局配置。请输入监控服务器可访问的完整路径。',
      function (val) {
        if (bdOutputPath) bdOutputPath.value = val;
      }
    );
  };

  window.bdBrowseCookieModal = function () {
    const bdCookie = document.getElementById('bdCookie');
    const current = bdCookie ? bdCookie.value.trim() : '';
    openPathModal(
      'Cookie 文件路径',
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/><path d="M12 8v4l3 3"/></svg>',
      '例如：C:\\cookies.txt 或留空使用全局配置',
      current,
      '必须是监控服务器本机可访问的文件路径，不支持读取浏览器本地文件。',
      function (val) {
        if (bdCookie) bdCookie.value = val.trim();
      }
    );
  };
})();

export function bdBrowsePath() { window.bdBrowsePathModal(); }
export function bdBrowseCookie() { window.bdBrowseCookieModal(); }

// ── Task Helpers ──────────────────────────────────────────────────

export function bdTaskLabel(task) {
  const statusMap = {
    running: '下载中',
    cancelling: '取消中',
    cancelled: '已取消',
    done: '已完成',
    error: '失败',
  };
  const status = statusMap[task.status] || (task.status || '未知');
  const total = Number(task.total || 0);
  const success = Number(task.success || 0);
  const failed = Number(task.failed || 0);
  const createdAt = (task.created_at || '').replace('T', ' ').slice(5, 16);
  const source = task.source_name ? ' · ' + task.source_name : '';
  return '[' + status + '] ' + total + ' 个 · 成功 ' + success + ' / 失败 ' + failed + (createdAt ? ' · ' + createdAt : '') + source;
}

export function bdFilterRecentTasks(tasks) {
  if (_bdRecentFilter === 'active') {
    return tasks.filter(task => task.status === 'running' || task.status === 'cancelling');
  }
  if (_bdRecentFilter === 'finished') {
    return tasks.filter(task => task.status === 'done' || task.status === 'error');
  }
  if (_bdRecentFilter === 'cancelled') {
    return tasks.filter(task => task.status === 'cancelled');
  }
  return tasks;
}

export function bdUpdateRecentSummary(tasks) {
  const allCount = tasks.length;
  const activeCount = tasks.filter(task => task.status === 'running' || task.status === 'cancelling').length;
  const finishedCount = tasks.filter(task => task.status === 'done' || task.status === 'error').length;
  const cancelledCount = tasks.filter(task => task.status === 'cancelled').length;
  const summary = document.getElementById('bdRecentSummary');
  if (summary) {
    summary.textContent = '全部 ' + allCount + ' · 进行中 ' + activeCount + ' · 已结束 ' + finishedCount + ' · 已取消 ' + cancelledCount;
  }
}

export function bdSetRecentFilter(filter, btn) {
  _bdRecentFilter = filter;
  document.querySelectorAll('#bdRecentFilters .bd-filter-chip').forEach(el => {
    el.classList.toggle('active', el === btn);
  });
  loadRecentBatchTasks();
}

export function bdRenderRecentTaskCards(tasks, activeTaskId) {
  const host = document.getElementById('bdRecentList');
  if (!host) return;
  if (!tasks.length) {
    host.innerHTML = '<div class="bd-recent-empty">暂无最近任务</div>';
    return;
  }
  host.innerHTML = '';
  tasks.slice(0, 6).forEach(task => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'bd-recent-card' + (task.task_id === activeTaskId ? ' active' : '');
    card.onclick = () => bdAttachTask(task.task_id);
    const total = Number(task.total || 0);
    const success = Number(task.success || 0);
    const failed = Number(task.failed || 0);
    const completed = Number(task.completed || 0);
    const pending = Math.max(0, total - completed);
    const status = task.status || 'unknown';
    const statusText = {
      running: '下载中',
      cancelling: '取消中',
      cancelled: '已取消',
      done: '已完成',
      error: '失败',
    }[status] || status;
    const createdAt = (task.created_at || '').replace('T', ' ').slice(5, 16) || '时间未知';
    card.innerHTML =
      '<div class="bd-recent-top">' +
        '<span class="bd-recent-status ' + status + '">' + statusText + '</span>' +
        '<span class="bd-recent-time">' + createdAt + '</span>' +
      '</div>' +
      '<div class="bd-recent-meta">共 ' + total + ' 个 · 成功 ' + success + ' · 失败 ' + failed + ' · 待处理 ' + pending + '</div>' +
      '<div class="bd-recent-sub">' + (task.source_name || '未记录文件名') + ' · ' + (task.current_video || task.cancel_message || '点击查看详情') + '</div>';
    const actions = document.createElement('div');
    actions.className = 'bd-recent-actions';

    const reopenBtn = document.createElement('button');
    reopenBtn.type = 'button';
    reopenBtn.className = 'bd-browse';
    reopenBtn.textContent = '重开';
    reopenBtn.onclick = (event) => {
      event.stopPropagation();
      bdRestartHistoryTask(task.task_id);
    };
    actions.appendChild(reopenBtn);

    if (task.status === 'running' || task.status === 'cancelling') {
      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'bd-browse';
      cancelBtn.textContent = task.status === 'cancelling' ? '取消中...' : '取消';
      cancelBtn.disabled = task.status === 'cancelling';
      cancelBtn.onclick = (event) => {
        event.stopPropagation();
        bdCancelTask(task.task_id);
      };
      actions.appendChild(cancelBtn);
    }

    card.appendChild(actions);
    host.appendChild(card);
  });
}

export function loadRecentBatchTasks(selectedTaskId) {
  const sel = el('bdRecentTasks');
  const hint = el('bdRecentHint');
  if (!sel || !hint) return;
  const currentValue = selectedTaskId || _bdTaskId || sel.value;
  api('GET', '/batch/tasks').then(r => {
    const tasks = r && Array.isArray(r.tasks) ? r.tasks : [];
    bdUpdateRecentSummary(tasks);
    sel.innerHTML = '';
    if (!tasks.length) {
      sel.innerHTML = '<option value="">暂无最近任务</option>';
      hint.textContent = '可恢复查看运行中任务，或打开最近完成/取消的任务结果。';
      bdRenderRecentTaskCards([], '');
      return;
    }
    tasks.forEach(task => {
      const opt = document.createElement('option');
      opt.value = task.task_id;
      opt.textContent = bdTaskLabel(task);
      sel.appendChild(opt);
    });
    if (currentValue && tasks.some(task => task.task_id === currentValue)) {
      sel.value = currentValue;
    } else {
      sel.value = tasks[0].task_id;
    }
    bdRenderRecentTaskCards(bdFilterRecentTasks(tasks), sel.value);
    const runningCount = tasks.filter(task => task.status === 'running' || task.status === 'cancelling').length;
    hint.textContent = runningCount > 0
      ? '当前有 ' + runningCount + ' 个任务仍在运行/取消中，可切换查看实时状态。'
      : '可打开最近完成、失败或已取消的批量任务结果。';
  });
}

export function bdOpenSelectedTask() {
  const sel = el('bdRecentTasks');
  const taskId = sel ? sel.value : '';
  if (!taskId) {
    toast('暂无可查看的批量任务', 'info');
    return;
  }
  bdAttachTask(taskId);
}

/**
 * 无新上传时用于「重新下载」：优先最近任务下拉的选中项，否则为当前已附加查看的任务。
 */
function bdResolveRestartTaskId() {
  const sel = el('bdRecentTasks');
  const v = sel && sel.value ? String(sel.value).trim() : '';
  if (v) return v;
  return _bdTaskId || '';
}

/** 启动成功后统一更新底部按钮、进度区与轮询（与 /batch/start 成功路径共用） */
function _bdApplyRunningAfterStart(taskId) {
  _bdTaskId = taskId;
  _bdState = 'running';
  const btn = el('bdStartBtn');
  if (btn) { btn.textContent = '下载中...'; btn.disabled = true; }
  const bdCancelBtn = el('bdCancelBtn'); if (bdCancelBtn) bdCancelBtn.textContent = '取消';
  const bdConfig = el('bdConfig'); if (bdConfig) bdConfig.style.opacity = '0.5';
  const bdProgressSection = el('bdProgressSection'); if (bdProgressSection) bdProgressSection.style.display = '';
  const bdTrackPulse = el('bdTrackPulse'); if (bdTrackPulse) bdTrackPulse.classList.add('active');
  loadRecentBatchTasks(taskId);
  if (_bdPollTimer) { clearInterval(_bdPollTimer); _bdPollTimer = null; }
  _bdPollTimer = setInterval(bdPoll, 2000);
}

/**
 * 使用服务端已存 URL 重开某条历史批量任务（POST /batch/tasks/:id/restart）。
 * 供底部「重新下载」在无新上传时、以及最近任务卡片「重开」调用。
 */
export function bdRestartHistoryTask(taskId) {
  if (_bdState === 'running' || _bdState === 'cancelling') return;
  if (!taskId) {
    toast('无效的任务', 'err');
    return;
  }
  const btn = el('bdStartBtn');
  if (btn) { btn.disabled = true; btn.textContent = '启动中...'; }
  bdResetProgressState();
  api('POST', '/batch/tasks/' + taskId + '/restart', {}).then(r => {
    if (btn) { btn.disabled = false; }
    if (r && r.task_id) {
      _bdApplyRunningAfterStart(r.task_id);
    } else {
      toast((r && r.error) || '重开失败', 'err');
      if (btn) btn.textContent = '▶ 重新下载';
    }
  }).catch(() => {
    if (btn) { btn.disabled = false; btn.textContent = '▶ 重新下载'; }
    toast('网络错误', 'err');
  });
}

export function bdCancelTask(taskId) {
  api('POST', '/batch/tasks/' + taskId + '/cancel', {}).then(r => {
    if (r && r.error) {
      if (_bdTaskId === taskId) {
        _bdState = 'running';
        const btn = el('bdCancelBtn'); if (btn) { btn.disabled = false; btn.textContent = '取消'; }
      }
      toast(r.error || '取消失败', 'err');
      return;
    }
    if (_bdTaskId === taskId) {
      _bdState = 'cancelling';
      const bdCurrent = el('bdCurrent'); if (bdCurrent) bdCurrent.textContent = (r && r.message) || '正在取消下载任务…';
    }
    loadRecentBatchTasks(taskId);
    if (_bdTaskId === taskId) {
      bdAttachTask(taskId);
    }
  }).catch(() => {
    if (_bdTaskId === taskId) {
      _bdState = 'running';
      const btn = el('bdCancelBtn'); if (btn) { btn.disabled = false; btn.textContent = '取消'; }
    }
    toast('取消请求失败', 'err');
  });
}

export function bdApplyTaskSnapshot(task, startPollingIfNeeded = true) {
  const pct = task.total > 0 ? Math.round((task.completed / task.total) * 100) : 0;
  const success = Number(task.success || 0);
  const failed = Number(task.failed || 0);
  const total = Number(task.total || 0);
  const completed = Number(task.completed || 0);
  const pending = Math.max(0, total - completed);

  const bdProgressSection = el('bdProgressSection'); if (bdProgressSection) bdProgressSection.style.display = '';
  const bdTrackFill = el('bdTrackFill'); if (bdTrackFill) bdTrackFill.style.width = pct + '%';
  const bdPct = el('bdPct'); if (bdPct) bdPct.textContent = pct + '%';
  const bdCurrent = el('bdCurrent'); if (bdCurrent) bdCurrent.textContent = task.current_video || '';
  const bdCounter = el('bdCounter'); if (bdCounter) bdCounter.textContent =
    '✓ ' + success + '/' + total +
    '  ·  ✗ ' + failed +
    '  ·  ⏳ ' + pending;

  const results = Array.isArray(task.results) ? task.results : [];
  if (results.length > _bdLastLogCount) {
    const div = el('bdLogText');
    if (div) {
      results.slice(_bdLastLogCount).forEach(item => {
        const cls = item.status === '成功' ? 'log-success' : item.status === '失败' ? 'log-error' : '';
        const t = new Date().toLocaleTimeString();
        div.innerHTML += '<div class="' + cls + '">[' + t + '] ' + (item.status || '') + ' ' + (item.info || '') + '</div>';
      });
      _bdLastLogCount = results.length;
      div.scrollTop = div.scrollHeight;
    }
  }

  const startBtn = el('bdStartBtn');
  const cancelBtn = el('bdCancelBtn');
  const completeEl = el('bdComplete');

  if (task.status === 'running' || task.status === 'cancelling') {
    _bdState = task.status === 'cancelling' ? 'cancelling' : 'running';
    if (startBtn) { startBtn.disabled = true; startBtn.textContent = '下载中...'; startBtn.style.display = ''; }
    if (cancelBtn) { cancelBtn.disabled = task.status === 'cancelling'; cancelBtn.textContent = task.status === 'cancelling' ? '取消中...' : '取消'; }
    const bdConfig = el('bdConfig'); if (bdConfig) bdConfig.style.opacity = '0.5';
    const bdTrackPulse = el('bdTrackPulse'); if (bdTrackPulse) bdTrackPulse.classList.add('active');
    if (completeEl) completeEl.style.display = 'none';
    if (startPollingIfNeeded && !_bdPollTimer) {
      _bdPollTimer = setInterval(bdPoll, 2000);
    }
    return;
  }

  if (_bdPollTimer) {
    clearInterval(_bdPollTimer);
    _bdPollTimer = null;
  }
  _bdState = 'idle';
  const bdTrackPulse2 = el('bdTrackPulse'); if (bdTrackPulse2) bdTrackPulse2.classList.remove('active');
  if (startBtn) { startBtn.disabled = false; startBtn.textContent = '▶ 重新下载'; }
  if (cancelBtn) { cancelBtn.disabled = false; cancelBtn.textContent = '关闭'; }
  const bdConfig2 = el('bdConfig'); if (bdConfig2) bdConfig2.style.opacity = '';

  if (completeEl) {
    completeEl.style.display = '';
    completeEl.className = 'bd-complete';
    if (task.status === 'cancelled') {
      completeEl.classList.add('warning');
      completeEl.textContent = '已取消 — 成功: ' + success + '  失败: ' + failed + '  已完成: ' + completed + '/' + total;
      if (bdCurrent) bdCurrent.textContent = task.cancel_message || '下载任务已取消';
    } else if (failed === 0 && success > 0) {
      completeEl.classList.add('success');
      completeEl.textContent = '下载成功 — 成功: ' + success + '  失败: ' + failed;
    } else if (success > 0 && failed > 0) {
      completeEl.classList.add('warning');
      completeEl.textContent = '部分成功 — 成功: ' + success + '  失败: ' + failed;
    } else {
      completeEl.classList.add('error');
      completeEl.textContent = '下载失败 — 成功: ' + success + '  失败: ' + failed;
      if (!task.current_video || task.current_video.startsWith('完成第 ')) {
        if (bdCurrent) bdCurrent.textContent = '存在下载失败，请检查 Cookie / 代理 / 目标站点限制';
      }
    }
  }
}

export function bdAttachTask(taskId) {
  _bdTaskId = taskId;
  _bdState = 'idle';
  if (_bdPollTimer) { clearInterval(_bdPollTimer); _bdPollTimer = null; }
  bdResetProgressState();
  api('GET', '/batch/tasks/' + taskId).then(task => {
    if (!task || task.error) {
      toast((task && task.error) || '无法加载任务详情', 'err');
      return;
    }
    loadRecentBatchTasks(taskId);
    bdApplyTaskSnapshot(task, true);
  });
}

export function bdStart() {
  if (_bdState === 'running' || _bdState === 'cancelling') return;
  // 有新上传：走 /batch/start；否则用最近任务选中项（或当前查看任务）重开
  if (!_bdUploadId) {
    const restartTaskId = bdResolveRestartTaskId();
    if (!restartTaskId) {
      toast('请先上传并解析包含 URL 的文件，或在「最近任务」中选择一条任务', 'err');
      return;
    }
    bdRestartHistoryTask(restartTaskId);
    return;
  }
  const bdOutputPath = el('bdOutputPath');
  const bdResolution = el('bdResolution');
  const bdSubEnabled = el('bdSubEnabled');
  const bdSubLang = el('bdSubLang');
  const bdProxy = el('bdProxy');
  const bdCookie = el('bdCookie');
  const body = {
    upload_id: _bdUploadId,
    output_path: (bdOutputPath && bdOutputPath.value.trim()) || '',
    resolution: bdResolution ? bdResolution.value : '',
    sub_langs: (bdSubEnabled && bdSubEnabled.checked && bdSubLang) ? bdSubLang.value.trim() : '',
    no_subs: !bdSubEnabled || !bdSubEnabled.checked,
    proxy_pool_id: bdProxy ? bdProxy.value || null : null,
    cookies_file: (bdCookie && bdCookie.value.trim()) || null,
  };
  const btn = el('bdStartBtn');
  if (btn) { btn.disabled = true; btn.textContent = '启动中...'; }
  bdResetProgressState();
  api('POST', '/batch/start', body).then(r => {
    if (btn) { btn.disabled = false; }
    if (r && r.task_id) {
      _bdApplyRunningAfterStart(r.task_id);
    } else {
      toast((r && r.error) || '启动失败', 'err');
      if (btn) btn.textContent = '▶ 开始下载';
    }
  }).catch(() => {
    if (btn) { btn.disabled = false; btn.textContent = '▶ 开始下载'; }
    toast('网络错误', 'err');
  });
}

export function bdPoll() {
  if (!_bdTaskId) return;
  api('GET', '/batch/tasks/' + _bdTaskId).then(r => {
    if (!r || r.error) return;
    bdApplyTaskSnapshot(r, true);
    if (r.status === 'done' || r.status === 'error' || r.status === 'cancelled') {
      loadRecentBatchTasks(r.task_id);
    }
  });
}

export function bdToggleLog() {
  const logEl = el('bdLog');
  const logTog = el('bdLogToggle');
  if (!logEl || !logTog) return;
  if (logEl.style.display === 'none') {
    logEl.style.display = '';
    logTog.textContent = '▴ 收起详情';
  } else {
    logEl.style.display = 'none';
    logTog.textContent = '▾ 展开详情';
  }
}

export function bdCancel() {
  if (_bdState === 'running') {
    _bdState = 'cancelling';
    const btn = el('bdCancelBtn'); if (btn) { btn.disabled = true; btn.textContent = '取消中...'; }
    const bdCurrent = el('bdCurrent'); if (bdCurrent) bdCurrent.textContent = '正在请求取消下载任务…';
    bdCancelTask(_bdTaskId);
    return;
  }
  if (_bdState === 'cancelling') return;
  if (_bdPollTimer) { clearInterval(_bdPollTimer); _bdPollTimer = null; }
  bdClose();
}
