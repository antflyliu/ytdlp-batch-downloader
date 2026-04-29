// ── Formatting Utilities ───────────────────────────────────────────

/**
 * Escape HTML special characters to prevent XSS.
 * @param {*} s
 * @returns {string}
 */
export function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/**
 * Format an ISO timestamp into a short date+time string (e.g. "4/12 15:30").
 * @param {string} iso
 * @returns {string}
 */
export function fmtTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  } catch { return '—'; }
}

/**
 * Format a duration in seconds into a human-readable string (e.g. "1:23:45" or "23:45").
 * @param {number} sec
 * @returns {string}
 */
export function fmtDuration(sec) {
  if (!sec) return '—';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * Format a number with locale-aware thousand separators.
 * @param {number} n
 * @returns {string}
 */
export function fmtNumber(n) {
  if (!n && n !== 0) return '—';
  return Number(n).toLocaleString();
}
