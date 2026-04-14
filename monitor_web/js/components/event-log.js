// ── Event Log Component ────────────────────────────────────────────
import { api } from '../api.js';
import { fmtTime, esc } from '../utils/format.js';

const el = (id) => document.getElementById(id);

/**
 * Load and render recent scan events into the log area.
 * @returns {Promise<void>}
 */
export async function loadEvents() {
  const events = await api('GET', '/events?limit=20');
  const area = el('logArea');
  if (!area) return;
  if (!Array.isArray(events)) {
    area.innerHTML =
      '<div class="log-line"><span class="log-time">—</span><span class="log-msg err">' +
      esc((events && events.error) ? String(events.error) : '事件加载失败') +
      '</span></div>';
    return;
  }
  if (!events || events.length === 0) {
    area.innerHTML = '<div class="log-line"><span class="log-time">—</span><span class="log-msg">暂无扫描记录</span></div>';
    return;
  }
  const countEl = el('eventCount');
  if (countEl) {
    countEl.textContent = `最近 ${events.length} 条`;
  }
  area.innerHTML = events.map(e => {
    const cls = e.status === 'success' ? 'ok' : e.status === 'error' ? 'err' : 'info';
    const time = e.scan_started_at ? fmtTime(e.scan_started_at) : '—';
    const msg = e.status === 'success'
      ? `${e.account_name}: API返回${e.total_videos} 新增${e.new_videos} 耗时${e.duration_ms}ms`
      : e.status === 'error'
      ? `${e.account_name}: 失败 ${e.error_message}`
      : `${e.account_name}: 进行中...`;
    return `<div class="log-line"><span class="log-time">${time}</span><span class="log-msg ${cls}">${esc(msg)}</span></div>`;
  }).join('');
}
