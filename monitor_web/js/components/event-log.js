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
      esc((events && events.error) ? String(events.error) : I18n.t('eventLog.loadFailed')) +
      '</span></div>';
    return;
  }
  if (!events || events.length === 0) {
    area.innerHTML = '<div class="log-line"><span class="log-time">—</span><span class="log-msg">' + I18n.t('eventLog.noEvents') + '</span></div>';
    return;
  }
  const countEl = el('eventCount');
  if (countEl) {
    countEl.textContent = I18n.t('eventLog.recentN').replace('{n}', events.length);
  }
  area.innerHTML = events.map(e => {
    const cls = e.status === 'success' ? 'ok' : e.status === 'error' ? 'err' : 'info';
    const time = e.scan_started_at ? fmtTime(e.scan_started_at) : '—';
    const msg = e.status === 'success'
      ? `${e.account_name}: API ${I18n.t('eventLog.returnedN').replace('{total}', e.total_videos)} ${I18n.t('eventLog.newN').replace('{new}', e.new_videos)} ${I18n.t('eventLog.durationMs').replace('{ms}', e.duration_ms)}`
      : e.status === 'error'
      ? `${e.account_name}: ${I18n.t('eventLog.failed')} ${e.error_message}`
      : `${e.account_name}: ${I18n.t('eventLog.inProgress')}`;
    return `<div class="log-line"><span class="log-time">${time}</span><span class="log-msg ${cls}">${esc(msg)}</span></div>`;
  }).join('');
}
