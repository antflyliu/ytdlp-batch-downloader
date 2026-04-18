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
        toast('调度器已停止', 'ok');
      } else {
        toast(r.error || '操作失败', 'err');
        updateSchedulerUI();
      }
    } else {
      const confirmResult = await showAppConfirmWithCheckbox({
        title: '启动监控',
        message: '开始按计划扫描账号更新。',
        confirmText: '启动监控',
        cancelText: '取消',
        confirmTone: 'primary',
        checkbox: {
          label: '扫描到新视频后自动下载',
          description: '每轮扫描完成后自动开始下载，最多 2 个视频同时下载',
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
            '调度器已在运行' + (confirmResult.checked ? '（已按本次选择同步自动下载选项）' : '（已按本次选择关闭自动下载）'),
            'info'
          );
        } else {
          toast('调度器已启动' + (confirmResult.checked ? '（含自动下载）' : ''), 'ok');
        }
      } else {
        toast(r.error || '启动失败', 'err');
        updateSchedulerUI();
      }
    }
  } catch(e) {
    toast('网络错误', 'err');
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
  toast(r.ok ? `重载完成，活跃任务: ${r.active_jobs}` : '重载失败', r.ok ? 'ok' : 'err');
}

/**
 * Toggle the dynamic provider scheduler.
 */
export async function toggleDynamicProviderScheduler() {
  const status = await api('GET', '/provider-scheduler/status');
  const running = !!(status && status.running);

  if (running) {
    const ok = await showAppConfirm({
      title: '停止动态代理调度？',
      message: '停止后，仅提供方 refresh / cleanup 任务会暂停；账号监控扫描不会受到影响。',
      confirmText: '停止',
      variant: 'danger',
    });
    if (!ok) return;
    const r = await api('POST', '/provider-scheduler/stop', {});
    if (r.ok !== false) {
      await window.updateProviderSchedulerHint();
      toast('动态代理调度已停止', 'ok');
    } else {
      toast(r.error || '操作失败', 'err');
    }
    return;
  }

  const ok = await showAppConfirm({
    title: '启动动态代理调度？',
    message: '启动后，将按提供方配置的刷新间隔执行列表拉取与候选清理。',
    confirmText: '启动',
  });
  if (!ok) return;
  const r = await api('POST', '/provider-scheduler/start', {});
  if (r.ok !== false) {
    await window.updateProviderSchedulerHint();
    toast('动态代理调度已启动', 'ok');
  } else {
    toast(r.error || '启动失败', 'err');
  }
}

/**
 * Reload dynamic provider jobs.
 */
export async function reloadDynamicProviderJobs() {
  const r = await api('POST', '/provider-scheduler/reload', {});
  toast(r.ok ? `动态代理任务已重载，活跃任务: ${r.active_jobs}` : '重载失败', r.ok ? 'ok' : 'err');
  await window.updateProviderSchedulerHint();
}

/**
 * Run dynamic provider jobs once immediately.
 */
export async function runDynamicProviderJobsOnce() {
  const ok = await showAppConfirm({
    title: '立即刷新全部列表 API？',
    message: '这会立刻对所有启用的列表拉取型提供方执行一次 refresh。',
    confirmText: '立即刷新',
  });
  if (!ok) return;
  const r = await api('POST', '/provider-scheduler/run-once', {});
  if (!r || r.error) {
    toast('执行失败: ' + (r && r.error ? r.error : '未知错误'), 'err');
    return;
  }
  const count = r.provider_count || 0;
  const results = r.results || [];
  const rawTotal = results.reduce((sum, x) => sum + (x.raw_count || 0), 0);
  const validTotal = results.reduce((sum, x) => sum + (x.valid_count || 0), 0);
  toast(`已执行 ${count} 个提供方的立即刷新 · raw ${rawTotal} / valid ${validTotal}`, 'ok');
  await window.updateProviderSchedulerHint();
  await Promise.all([window.loadDynamicProviderTable(), window.loadProviderSchedulerLogs()]);
}
