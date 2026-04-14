// ── Global Mutable State ───────────────────────────────────────────────
// Central state module — all module-level mutable variables live here.
// Imported by other modules that need read/write access.

export let _pendingScanNow = { accountId: null, button: null };
export let _scanNowSubmitting = false;
export const _scanNowCooldown = new Map(); // accountId -> Date.now() of when cooldown ends

export let _appConfirmResolve = null;
export let _appConfirmEscHandler = null;
export let _appConfirmGeneration = 0;

export let _vdAccId = null;
export let _vdPage = 1;
export const _vdSel = new Set();
export let _gConfig = null;  // 全局配置缓存
export let _vdEscHandler = null;
export let _vdDlPollTimer = null;

export let _refreshChain = Promise.resolve();
export let _mainRefreshTimer = null;  // 主页面定时刷新 timer

// Setters to avoid reassigning ES Module live bindings from other modules
export function setGConfig(cfg) { _gConfig = cfg; }
export function setRefreshChain(p) { _refreshChain = p; }
export function setMainRefreshTimer(t) { _mainRefreshTimer = t; }
export function setVdAccId(v) { _vdAccId = v; }
export function setVdPage(v) { _vdPage = v; }
export function setVdSelClear() { _vdSel.clear(); }
export function setPendingScanNow(v) { _pendingScanNow = v; }
export function setScanNowSubmitting(v) { _scanNowSubmitting = v; }
export function setAppConfirmResolve(v) { _appConfirmResolve = v; }
export function setAppConfirmEscHandler(v) { _appConfirmEscHandler = v; }
export function setAppConfirmGeneration(v) { _appConfirmGeneration = v; }
