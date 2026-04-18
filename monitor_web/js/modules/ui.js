// ── Toast & Modal UI ─────────────────────────────────────────────────
// Toast notifications and modal open/close management.

import {
  _appConfirmResolve,
  _appConfirmEscHandler,
  _appConfirmGeneration,
  _scanNowCooldown,
  _scanNowSubmitting,
  _pendingScanNow,
  setAppConfirmResolve,
  setAppConfirmEscHandler,
  setAppConfirmGeneration,
  setScanNowSubmitting,
  setPendingScanNow,
} from './state.js';
import { api } from '../api.js';
import { toggleScheduler } from '../components/scheduler-panel.js';

// ── DOM Helpers ──────────────────────────────────────────────────────
const el = (id) => document.getElementById(id);

// ── Toast ────────────────────────────────────────────────────────────
export function toast(msg, type = 'info') {
  const c = el('toasts');
  if (!c) return;
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.textContent = msg;
  c.appendChild(node);
  setTimeout(() => node.remove(), 3500);
}

// ── Modal Management ─────────────────────────────────────────────────

function resetAppConfirmCheckbox() {
  const row = el('appConfirmCheckboxRow');
  const checkbox = el('appConfirmCheckbox');
  const label = el('appConfirmCheckboxLabel');
  const hint = el('appConfirmCheckboxHint');
  if (row) row.hidden = true;
  if (checkbox) checkbox.checked = false;
  if (label) label.textContent = '';
  if (hint) { hint.textContent = ''; hint.hidden = true; }
}

export function openModal(id) {
  const m = el(id);
  if (!m) return;
  // Remove display:none if present on overlay (some modals use display:none as default)
  m.style.display = '';
  // Generic modal: .modal inside .modal-overlay
  const inner = m.querySelector('.modal');
  if (inner) inner.classList.add('modal--open');
  m.classList.add('show');
}

export function closeModal(id) {
  const m = el(id);
  if (!m) return;
  if (id === 'modalVideoDetail') {
    const escHandler = window._vdEscHandlerRef;
    if (escHandler) {
      document.removeEventListener('keydown', escHandler);
      window._vdEscHandlerRef = null;
    }
    const inner = m.querySelector('.modal');
    if (inner) inner.classList.remove('modal--open');
    m.classList.remove('show');
    m.style.display = '';
    return;
  }
  const inner = m.querySelector('.modal');
  if (inner) inner.classList.remove('modal--open');
  m.classList.remove('show');
}

/**
 * Promise-style confirm dialog matching .modal-overlay style.
 * @param {{ title: string, message: string, confirmText?: string, cancelText?: string, variant?: 'primary'|'danger', confirmTone?: 'primary'|'danger'|'success' }} options
 */
export function showAppConfirm(options) {
  return new Promise((resolve) => {
    setAppConfirmGeneration(_appConfirmGeneration + 1);
    if (_appConfirmResolve) {
      const prev = _appConfirmResolve;
      setAppConfirmResolve(null);
      prev(false);
    }
    setAppConfirmResolve(resolve);
    resetAppConfirmCheckbox();
    const titleEl = el('appConfirmTitle');
    const bodyEl = el('appConfirmBody');
    const primaryBtn = el('appConfirmPrimaryBtn');
    const cancelBtn = el('appConfirmCancelBtn');
    if (!titleEl || !bodyEl || !primaryBtn || !cancelBtn) return;
    titleEl.textContent = options.title || '确认';
    bodyEl.textContent = options.message || '';
    primaryBtn.textContent = options.confirmText || '确定';
    cancelBtn.textContent = options.cancelText || '取消';
    const tone = options.confirmTone || (options.variant === 'danger' ? 'danger' : 'primary');
    primaryBtn.className = 'btn ' + (tone === 'danger' ? 'btn-danger' : tone === 'success' ? 'btn-success' : 'btn-primary');
    const appConfirmOverlay = el('modalAppConfirm');
    if (appConfirmOverlay) appConfirmOverlay.classList.toggle('modal-app-confirm--danger', tone === 'danger');
    if (_appConfirmEscHandler) document.removeEventListener('keydown', _appConfirmEscHandler);
    const handler = (e) => { if (e.key === 'Escape') closeAppConfirm(false); };
    setAppConfirmEscHandler(handler);
    document.addEventListener('keydown', handler);
    openModal('modalAppConfirm');
    requestAnimationFrame(() => { try { primaryBtn.focus(); } catch (e) { /* ignore */ } });
  });
}

export function closeAppConfirm(confirmed) {
  if (_appConfirmEscHandler) {
    document.removeEventListener('keydown', _appConfirmEscHandler);
    setAppConfirmEscHandler(null);
  }
  const fn = _appConfirmResolve;
  setAppConfirmResolve(null);
  const appConfirmEl = el('modalAppConfirm');
  if (appConfirmEl) appConfirmEl.classList.remove('modal-app-confirm--danger');
  closeModal('modalAppConfirm');
  if (fn) fn(!!confirmed);
}

/**
 * @param {{ title: string, message: string, confirmText?: string, cancelText?: string, variant?: 'primary'|'danger', confirmTone?: 'primary'|'danger'|'success', checkbox?: { label: string, description?: string, checked?: boolean } }} options
 * @returns {Promise<{ confirmed: boolean, checked?: boolean }>}
 */
export async function showAppConfirmWithCheckbox(options) {
  const confirmPromise = showAppConfirm(options);
  const generation = _appConfirmGeneration;
  const row = el('appConfirmCheckboxRow');
  const checkbox = el('appConfirmCheckbox');
  const label = el('appConfirmCheckboxLabel');
  const hint = el('appConfirmCheckboxHint');
  if (row && checkbox && label && hint) {
    row.hidden = false;
    checkbox.checked = options.checkbox.checked !== false;
    label.textContent = options.checkbox.label || '';
    hint.textContent = options.checkbox.description || '';
    hint.hidden = !options.checkbox.description;
  }

  const confirmed = await confirmPromise;
  const checked = checkbox ? checkbox.checked : false;
  if (_appConfirmGeneration === generation) {
    resetAppConfirmCheckbox();
  }
  return confirmed ? { confirmed: true, checked } : { confirmed: false };
}

// ── Scan Now State ───────────────────────────────────────────────────

export function _resetScanNowState() {
  setPendingScanNow({ accountId: null, button: null });
  setScanNowSubmitting(false);
}

export function closeScanConfirm(resetState = true) {
  closeModal('modalScanConfirm');
  if (resetState) _resetScanNowState();
}

// ── Scheduler UI ───────────────────────────────────────────────────────
export let schedulerRunning = false;

/** 更新调度器运行状态（其它模块不可对导入的 schedulerRunning 直接赋值，须用此 setter） */
export function setSchedulerRunning(v) {
  schedulerRunning = !!v;
}

export async function loadStatus() {
  const data = await api('GET', '/status');
  setSchedulerRunning(data && data.running);
  updateSchedulerUI();
}

export function updateSchedulerUI() {
  const chip = el('statusChip');
  const btn = el('btnToggleScheduler');
  // 顶栏可能无 #statusChip（内联 header 未含 chip），但必须仍能更新账户页的启动/停止按钮
  if (!btn) return;
  if (schedulerRunning) {
    if (chip) {
      chip.className = 'status-chip running';
      chip.innerHTML = '<span class="status-dot"></span><span>调度器运行中</span>';
    }
    btn.textContent = '■ 停止监控';
    btn.className = 'btn btn-danger';
    btn.onclick = toggleScheduler;
  } else {
    if (chip) {
      chip.className = 'status-chip stopped';
      chip.innerHTML = '<span class="status-dot"></span><span>调度器已停止</span>';
    }
    btn.textContent = '▶ 启动监控';
    btn.className = 'btn btn-success';
    btn.onclick = toggleScheduler;
  }
}

// ── Modal overlay click-outside handler ─────────────────────────────
// Uses event delegation on document so it works even if modal HTML is lazy-loaded
document.addEventListener('click', e => {
  const target = e.target;
  if (!target.classList.contains('modal-overlay') || target.id === 'modalVideoDetail') return;
  if (target.id === 'modalScanConfirm') {
    closeScanConfirm();
  } else if (target.id === 'modalAppConfirm') {
    closeAppConfirm(false);
  } else {
    const innerModal = target.querySelector('.modal');
    if (innerModal) innerModal.classList.remove('modal--open');
    target.classList.remove('show');
  }
});
