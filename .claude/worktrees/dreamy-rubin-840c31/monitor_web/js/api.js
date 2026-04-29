// ── API Client ──────────────────────────────────────────────────────
// API base URL
export const API_BASE = '/api';

// ── Token Management ───────────────────────────────────────────────
// 本机调试/自动化：?api_token=xxx 写入 sessionStorage 并从地址栏移除（避免误分享带 token 的 URL）
(function bootstrapTokenFromQuery() {
  try {
    const host = window.location.hostname;
    if (host !== '127.0.0.1' && host !== 'localhost') return;
    const p = new URLSearchParams(window.location.search);
    const t = (p.get('api_token') || '').trim();
    if (!t) return;
    sessionStorage.setItem('monitor_api_token', t);
    p.delete('api_token');
    const qs = p.toString();
    const path = window.location.pathname || '/';
    history.replaceState(null, '', path + (qs ? '?' + qs : '') + window.location.hash);
  } catch (_) { /* ignore */ }
})();

/**
 * 获取当前 Bearer token。
 * 优先级：sessionStorage（浏览器 URL 传入） > window.__MONITOR_API_TOKEN__（服务端注入，pywebview 场景）
 * 每次调用时动态读取，避免 ES module 静态初始化时机问题。
 */
function getBearerToken() {
  return (
    sessionStorage.getItem('monitor_api_token') ||
    (typeof window !== 'undefined' && window.__MONITOR_API_TOKEN__) ||
    ''
  );
}

/** @type {Promise<void>|null} 并行 api() 共用的「先拿到 token」屏障，避免竞态导致大量无 Authorization 请求 */
let _ensureBearerPromise = null;

/**
 * 在发起需认证的请求前确保已有 Bearer（或用户已取消提示）。
 * 冷启动无 session token 时不请求 GET /api/token：服务端该接口也需 Bearer，无 token 时必然 401，徒增日志与往返。
 * 并行 api() 仍通过 _ensureBearerPromise 共用一个 prompt，避免竞态。
 */
export async function ensureBearerBeforeApi() {
  if (getBearerToken()) return;
  if (_ensureBearerPromise) return _ensureBearerPromise;
  _ensureBearerPromise = (async () => {
    _promptToken();
  })().finally(() => {
    _ensureBearerPromise = null;
  });
  return _ensureBearerPromise;
}

export function _promptToken() {
  const t = prompt('请输入 API Token:');
  if (t && t.trim()) {
    sessionStorage.setItem('monitor_api_token', t.trim());
  }
  return getBearerToken();
}

/**
 * 多个并行 api() 同时 401 时共用的「重新登录」屏障，只弹一次输入框，全部 await 后再各自重试。
 */
let _reauth401Promise = null;

export function ensureReauthAfter401() {
  if (!_reauth401Promise) {
    _reauth401Promise = (async () => {
      _promptToken();
    })().finally(() => {
      _reauth401Promise = null;
    });
  }
  return _reauth401Promise;
}

export async function api(method, path, body, _retry = false) {
  if (!_retry) await ensureBearerBeforeApi();
  const token = getBearerToken();
  const opts = {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': 'Bearer ' + token } : {}),
    },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  let r;
  try {
    r = await fetch(API_BASE + path, opts);
  } catch (e) {
    const msg = (e && e.message) ? e.message : String(e);
    return { error: '网络错误: ' + msg + '（若正在「刷新提供方」，可稍后再试；或确认本机监控服务已启动）', _fetchFailed: true };
  }
  if (r.status === 401 && !_retry) {
    await ensureReauthAfter401();
    return api(method, path, body, true);
  }
  const text = await r.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return { error: text || '请求失败', _httpStatus: r.status };
  }
  if (data !== null && typeof data === 'object' && !Array.isArray(data)) {
    data._httpStatus = r.status;
  }
  return data;
}

export async function apiForm(method, path, formData, _retry = false) {
  if (!_retry) await ensureBearerBeforeApi();
  const token = getBearerToken();
  const opts = {
    method,
    headers: {
      ...(token ? { 'Authorization': 'Bearer ' + token } : {}),
    },
    body: formData,
  };
  let r;
  try {
    r = await fetch(API_BASE + path, opts);
  } catch (e) {
    const msg = (e && e.message) ? e.message : String(e);
    return { error: '网络错误: ' + msg, _fetchFailed: 1, _httpStatus: 0 };
  }
  if (r.status === 401 && !_retry) {
    await ensureReauthAfter401();
    return apiForm(method, path, formData, true);
  }
  const text = await r.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return { error: text || '请求失败', _httpStatus: r.status };
  }
  if (data !== null && typeof data === 'object' && !Array.isArray(data)) {
    data._httpStatus = r.status;
  }
  return data;
}
