// ── Scheduler Panel Component ────────────────────────────────────
import { api } from '../api.js';
import {
  schedulerRunning, loadStatus, updateSchedulerUI, setSchedulerRunning,
  toast, showAppConfirm, showAppConfirmWithCheckbox,
} from '../modules/ui.js';

export { schedulerRunning, loadStatus, updateSchedulerUI };

/**
 * Toggle the scheduler (start/stop).
 */
export async function toggleScheduler() {
  const btn = document.getElementById('btnToggleScheduler');
  if (!btn) return;

  const setBtnLoading = (loading) => {
    if (loading) {
      btn.innerHTML = '<span class="spinner"></span>';
      btn.style.pointerEvents = 'none';
    } else {
      btn.style.pointerEvents = '';
    }
  };

  try {
    if (schedulerRunning) {
      setBtnLoading(true);
      const r = await api('POST', '/scheduler/stop');
      if (r.ok !== false) {
        setSchedulerRunning(false);
        updateSchedulerUI();
        toast(I18n.t('scheduler.schedulerStopped'), 'ok');
      } else {
        toast(r.error || I18n.t('scheduler.operationFailed'), 'err');
        updateSchedulerUI();
      }
    } else {
      const confirmResult = await showAppConfirmWithCheckbox({
        title: I18n.t('scheduler.startMonitor'),
        message: I18n.t('scheduler.startHint'),
        confirmText: I18n.t('scheduler.startMonitor'),
        cancelText: I18n.t('common.close'),
        confirmTone: 'primary',
        checkbox: {
          label: I18n.t('scheduler.autoDownloadDesc'),
          description: I18n.t('scheduler.autoDownloadDesc2'),
          checked: true,
        },
      });
      if (!confirmResult.confirmed) {
        updateSchedulerUI();
        return;
      }
      setBtnLoading(true);
      const r = await api('POST', '/scheduler/start', {
        auto_download: confirmResult.checked
      });
      if (r.ok !== false) {
        setSchedulerRunning(true);
        updateSchedulerUI();
        if (r.already_running) {
          toast(
            confirmResult.checked ? I18n.t('scheduler.schedulerAlreadyRunningAuto') : I18n.t('scheduler.schedulerAlreadyRunningNoAuto'),
            'info'
          );
        } else {
          toast(confirmResult.checked ? I18n.t('scheduler.schedulerStartedAuto') : I18n.t('scheduler.schedulerRunning'), 'ok');
        }
      } else {
        toast(r.error || I18n.t('scheduler.startFailed'), 'err');
        updateSchedulerUI();
      }
    }
  } catch(e) {
    toast(I18n.t('account.networkError'), 'err');
    updateSchedulerUI();
  } finally {
    setBtnLoading(false);
  }
}

/**
 * Reload scheduler jobs.
 */
export async function reloadJobs() {
  const r = await api('POST', '/scheduler/reload');
  toast(r.ok ? I18n.t('scheduler.reloadDone').replace('{n}', r.active_jobs) : I18n.t('scheduler.reloadFailed'), r.ok ? 'ok' : 'err');
}

/**
 * Toggle the dynamic provider scheduler.
 */
export async function toggleDynamicProviderScheduler() {
  const status = await api('GET', '/provider-scheduler/status');
  const running = !!(status && status.running);

  if (running) {
    const ok = await showAppConfirm({
      title: I18n.t('scheduler.stopScheduler'),
      message: I18n.t('scheduler.stopSchedulerMsg'),
      confirmText: I18n.t('common.stop'),
      variant: 'danger',
    });
    if (!ok) return;
    const r = await api('POST', '/provider-scheduler/stop', {});
    if (r.ok !== false) {
      await window.updateProviderSchedulerHint();
      toast(I18n.t('scheduler.dynSchedulerStopped'), 'ok');
    } else {
      toast(r.error || I18n.t('scheduler.operationFailed'), 'err');
    }
    return;
  }

  const ok = await showAppConfirm({
    title: I18n.t('scheduler.startScheduler'),
    message: I18n.t('scheduler.startSchedulerMsg'),
    confirmText: I18n.t('common.start'),
  });
  if (!ok) return;
  const r = await api('POST', '/provider-scheduler/start', {});
  if (r.ok !== false) {
    await window.updateProviderSchedulerHint();
    toast(I18n.t('scheduler.dynSchedulerStarted'), 'ok');
  } else {
    toast(r.error || I18n.t('scheduler.startFailed'), 'err');
  }
}

/**
 * Reload dynamic provider jobs.
 */
export async function reloadDynamicProviderJobs() {
  const r = await api('POST', '/provider-scheduler/reload', {});
  toast(r.ok ? I18n.t('scheduler.dynJobsReloaded').replace('{n}', r.active_jobs) : I18n.t('scheduler.reloadFailed'), r.ok ? 'ok' : 'err');
  await window.updateProviderSchedulerHint();
}

/**
 * Run dynamic provider jobs once immediately.
 */
export async function runDynamicProviderJobsOnce() {
  const ok = await showAppConfirm({
    title: I18n.t('scheduler.refreshAllProviders'),
    message: I18n.t('scheduler.refreshAllProvidersMsg'),
    confirmText: I18n.t('scheduler.refreshNow'),
  });
  if (!ok) return;
  const r = await api('POST', '/provider-scheduler/run-once', {});
  if (!r || r.error) {
    toast(I18n.t('scheduler.execFailed') + (r && r.error ? ': ' + r.error : ''), 'err');
    return;
  }
  const count = r.provider_count || 0;
  const results = r.results || [];
  const rawTotal = results.reduce((sum, x) => sum + (x.raw_count || 0), 0);
  const validTotal = results.reduce((sum, x) => sum + (x.valid_count || 0), 0);
  toast(I18n.t('scheduler.execDone').replace('{n}', count).replace('{raw}', rawTotal).replace('{valid}', validTotal), 'ok');
  await window.updateProviderSchedulerHint();
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}
