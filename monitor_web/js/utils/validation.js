// ── Validation Utilities ────────────────────────────────────────────

/**
 * Validate that a string is not empty.
 * @param {string} value
 * @returns {boolean}
 */
export function isNotEmpty(value) {
  return value && String(value).trim().length > 0;
}

/**
 * Validate YouTube channel URL (handles both /channel/ and /@ handles).
 * @param {string} url
 * @returns {boolean}
 */
export function isValidChannelUrl(url) {
  if (!url) return false;
  const trimmed = url.trim();
  // Accept URLs starting with http(s):// and containing youtube.com or youtu.be
  if (/^https?:\/\//.test(trimmed)) {
    return /youtube\.com|youtu\.be/.test(trimmed);
  }
  // Accept bare channel IDs or @ handles
  return /^(@[a-zA-Z0-9_-]+|UC[a-zA-Z0-9_-]{22})$/.test(trimmed);
}

/**
 * Validate scan interval (minutes, must be between 1 and 1440).
 * @param {number|string} interval
 * @returns {boolean}
 */
export function isValidScanInterval(interval) {
  const n = parseInt(interval, 10);
  return !isNaN(n) && n >= 1 && n <= 1440;
}

/**
 * Validate fetch limit (must be a positive integer).
 * @param {number|string} limit
 * @returns {boolean}
 */
export function isValidFetchLimit(limit) {
  const n = parseInt(limit, 10);
  return !isNaN(n) && n > 0;
}

/**
 * Validate a proxy URL (basic format check).
 * @param {string} url
 * @returns {boolean}
 */
export function isValidProxyUrl(url) {
  if (!url) return false;
  return /^https?:\/\//.test(url.trim()) || /^(socks5?|http|https):\/\//.test(url.trim());
}

/**
 * Validate API key (basic non-empty check for UI-level validation).
 * @param {string} key
 * @returns {boolean}
 */
export function isValidApiKey(key) {
  return isNotEmpty(key);
}

/**
 * Check if a required field is present and not empty.
 * @param {string} value
 * @param {string} fieldName
 * @returns {{ valid: boolean, message?: string }}
 */
export function validateRequired(value, fieldName) {
  if (!isNotEmpty(value)) {
    return { valid: false, message: fieldName + '不能为空' };
  }
  return { valid: true };
}
