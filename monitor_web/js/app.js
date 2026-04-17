// ── Main Application Entry Point ───────────────────────────────────
// Bootstrap: import all feature modules, re-export to window for
// inline HTML onclick access, and wire up the initial refresh cycle.

import { api, _promptToken, API_BASE } from './api.js';
import { esc, fmtTime, fmtDuration } from './utils/format.js';

// ── Feature modules ────────────────────────────────────────────────
import { toast, openModal, closeModal, showAppConfirm, closeAppConfirm, showAppConfirmWithCheckbox, closeScanConfirm } from './modules/ui.js';
import { refresh, loadStats, refreshAccounts, openAddAccount, openEditAccount, onApiKeySelectChanged, toggleProxySection, onAccountProxyModeChange, onDynamicProxySettingChange, previewAccountRouting, refreshProxyPoolSelectors, saveAccount, deleteAccount, scanNow, confirmScanNow, selectPlatform, updateFeishuModeUI, PROXY_MODE_HELP, startAutoRefresh, stopAutoRefresh } from './modules/accounts.js';
import { openVideoDetail, vdLoad, vdSearch, vdGoPage, vdChangePageSize, vdClearFilters, vdToggle, vdToggleAll, vdBatchDownload, _updateVdSubLabelText, _getVdSubPayload, _vdDlDone } from './modules/videoDetail.js';
import { openConfig, saveConfig, openApiKeys, loadApiKeysList, openAddApiKey, openEditApiKey, saveApiKey, deleteApiKey, refreshApiKeySelectors } from './modules/config.js';
import { openProxyDemo, closeProxyDemo, openProxyPools, loadProxyPoolTable, openAddProxyPool, openEditProxyPool, saveProxyPool, toggleProxyPool, deleteProxyPool } from './modules/proxyPool.js';
import { openCache, loadCacheList, refreshCacheItem, refreshCacheItemByHandle, deleteCacheItem, clearAllCache } from './modules/cache.js';
import { openDynamicProviders, updateProviderSchedulerHint, loadProviderSchedulerLogs, loadDynamicProviderTable, onDynAdapterTypeChange, onDynListApiAuthToggle, onDynListApiAdvToggle, onDynBillingTierChange, openAddDynamicProvider, openEditDynamicProvider, _buildDynConfigJson, saveDynamicProvider, toggleDynamicProvider, deleteDynamicProvider, healthCheckDynamicProvider, clearCooldownDynamicProvider, refreshDynamicProvider, previewCandidatesDynamicProvider, openDynamicProviderDetail, refreshDynamicProviderDetail, healthCheckDynamicProviderDetail, clearCooldownDynamicProviderDetail, toggleProviderFailureList, closeDynamicProviderDetail, healthCheckAllProviders } from './modules/dynamicProvider.js';
import { openClipHistory } from './modules/clipHistory.js';

// ── Component modules ───────────────────────────────────────────────
import { loadAccounts, filterAccountTable } from './components/account-list.js';
import { loadEvents } from './components/event-log.js';
import { schedulerRunning, loadStatus, updateSchedulerUI } from './modules/ui.js';
import { toggleScheduler, reloadJobs, toggleDynamicProviderScheduler, reloadDynamicProviderJobs, runDynamicProviderJobsOnce } from './components/scheduler-panel.js';
import { openBatchDownload, bdClose, bdCancel, bdStart, bdRestartHistoryTask, bdSwitchFmt, bdTriggerFile, bdHandleFile, bdBrowsePath, bdBrowseCookie, bdOpenSelectedTask, bdToggleLog, bdSetRecentFilter, loadRecentBatchTasks } from './components/batch-download-modal.js';
import { loadPartials } from './load-partials.js';

// ── Re-exports / globals needed by inline HTML onclick ────────────────
window.api = api;
window.API_BASE = API_BASE;
window._promptToken = _promptToken;
window.esc = esc;
window.fmtTime = fmtTime;
window.fmtDuration = fmtDuration;

// UI
window.toast = toast;
window.openModal = openModal;
window.closeModal = closeModal;
window.showAppConfirm = showAppConfirm;
window.closeAppConfirm = closeAppConfirm;
window.showAppConfirmWithCheckbox = showAppConfirmWithCheckbox;
window.closeScanConfirm = closeScanConfirm;
window.selectPlatform = selectPlatform;
window.updateFeishuModeUI = updateFeishuModeUI;
window.toggleScheduler = toggleScheduler;
window.reloadJobs = reloadJobs;
window.toggleDynamicProviderScheduler = toggleDynamicProviderScheduler;
window.reloadDynamicProviderJobs = reloadDynamicProviderJobs;
window.runDynamicProviderJobsOnce = runDynamicProviderJobsOnce;

// Accounts
window.refreshAccounts = refreshAccounts;
window.filterAccountTable = filterAccountTable;
window.loadStats = loadStats;
window.refresh = refresh;
window.openAddAccount = openAddAccount;
window.openEditAccount = openEditAccount;
window.onApiKeySelectChanged = onApiKeySelectChanged;
window.toggleProxySection = toggleProxySection;
window.onAccountProxyModeChange = onAccountProxyModeChange;
window.onDynamicProxySettingChange = onDynamicProxySettingChange;
window.PROXY_MODE_HELP = PROXY_MODE_HELP;
window.previewAccountRouting = previewAccountRouting;
window.refreshProxyPoolSelectors = refreshProxyPoolSelectors;
window.saveAccount = saveAccount;
window.deleteAccount = deleteAccount;
window.scanNow = scanNow;
window.confirmScanNow = confirmScanNow;
window.startAutoRefresh = startAutoRefresh;
window.stopAutoRefresh = stopAutoRefresh;

// Video Detail
window.openVideoDetail = openVideoDetail;
window.vdLoad = vdLoad;
window.vdSearch = vdSearch;
window.vdGoPage = vdGoPage;
window.vdChangePageSize = vdChangePageSize;
window.vdClearFilters = vdClearFilters;
window.vdToggle = vdToggle;
window.vdToggleAll = vdToggleAll;
window.vdBatchDownload = vdBatchDownload;
window._updateVdSubLabelText = _updateVdSubLabelText;
window._getVdSubPayload = _getVdSubPayload;
window._vdDlDone = _vdDlDone;

// Config & API Keys
window.openConfig = openConfig;
window.saveConfig = saveConfig;
window.openApiKeys = openApiKeys;
window.loadApiKeysList = loadApiKeysList;
window.openAddApiKey = openAddApiKey;
window.openEditApiKey = openEditApiKey;
window.saveApiKey = saveApiKey;
window.deleteApiKey = deleteApiKey;
window.refreshApiKeySelectors = refreshApiKeySelectors;

// Proxy Pools
window.openProxyDemo = openProxyDemo;
window.closeProxyDemo = closeProxyDemo;
window.openProxyPools = openProxyPools;
window.loadProxyPoolTable = loadProxyPoolTable;
window.openAddProxyPool = openAddProxyPool;
window.openEditProxyPool = openEditProxyPool;
window.saveProxyPool = saveProxyPool;
window.toggleProxyPool = toggleProxyPool;
window.deleteProxyPool = deleteProxyPool;

// Cache
window.openCache = openCache;
window.loadCacheList = loadCacheList;
window.refreshCacheItem = refreshCacheItem;
window.refreshCacheItemByHandle = refreshCacheItemByHandle;
window.deleteCacheItem = deleteCacheItem;
window.clearAllCache = clearAllCache;

// Dynamic Providers
window.openDynamicProviders = openDynamicProviders;
window.updateProviderSchedulerHint = updateProviderSchedulerHint;
window.loadProviderSchedulerLogs = loadProviderSchedulerLogs;
window.loadDynamicProviderTable = loadDynamicProviderTable;
window.onDynAdapterTypeChange = onDynAdapterTypeChange;
window.onDynListApiAuthToggle = onDynListApiAuthToggle;
window.onDynListApiAdvToggle = onDynListApiAdvToggle;
window.onDynBillingTierChange = onDynBillingTierChange;
window.openAddDynamicProvider = openAddDynamicProvider;
window.openEditDynamicProvider = openEditDynamicProvider;
window._buildDynConfigJson = _buildDynConfigJson;
window.saveDynamicProvider = saveDynamicProvider;
window.toggleDynamicProvider = toggleDynamicProvider;
window.deleteDynamicProvider = deleteDynamicProvider;
window.healthCheckDynamicProvider = healthCheckDynamicProvider;
window.clearCooldownDynamicProvider = clearCooldownDynamicProvider;
window.refreshDynamicProvider = refreshDynamicProvider;
window.previewCandidatesDynamicProvider = previewCandidatesDynamicProvider;
window.openDynamicProviderDetail = openDynamicProviderDetail;
window.refreshDynamicProviderDetail = refreshDynamicProviderDetail;
window.healthCheckDynamicProviderDetail = healthCheckDynamicProviderDetail;
window.clearCooldownDynamicProviderDetail = clearCooldownDynamicProviderDetail;
window.toggleProviderFailureList = toggleProviderFailureList;
window.closeDynamicProviderDetail = closeDynamicProviderDetail;
window.healthCheckAllProviders = healthCheckAllProviders;

// Batch Download
window.openBatchDownload = openBatchDownload;
window.bdClose = bdClose;
window.bdCancel = bdCancel;
window.bdStart = bdStart;
window.bdRestartHistoryTask = bdRestartHistoryTask;
window.bdSwitchFmt = bdSwitchFmt;
window.bdTriggerFile = bdTriggerFile;
window.bdHandleFile = bdHandleFile;
window.bdBrowsePath = bdBrowsePath;
window.bdBrowseCookie = bdBrowseCookie;
window.bdOpenSelectedTask = bdOpenSelectedTask;
window.bdToggleLog = bdToggleLog;
window.bdSetRecentFilter = bdSetRecentFilter;
window.loadRecentBatchTasks = loadRecentBatchTasks;

// Clip History
window.openClipHistory = openClipHistory;

// ── Boot: 先注入 header / modal 模板，再拉取数据并启动定时刷新 ───────────
loadPartials()
  .then(() => {
    refresh();
    startAutoRefresh();
  })
  .catch((err) => {
    console.error(err);
    try {
      toast(String(err && err.message ? err.message : err), 'err');
    } catch (_) { /* ignore */ }
  });
