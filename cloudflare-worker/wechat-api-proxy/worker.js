/**
 * Cloudflare Worker — WeChat API transparent proxy.
 *
 * Solves the dynamic-IP problem by routing WeChat API calls through
 * Cloudflare's network (whose IP ranges can be whitelisted once).
 *
 * Environment variables (set via `wrangler secret put`):
 *   PROXY_TOKEN  — shared bearer token for authenticating callers
 */

const WECHAT_API_ORIGIN = 'https://api.weixin.qq.com';
const MAX_REQUEST_BYTES = 10 * 1024 * 1024; // 10 MB

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const authResult = authenticate(request, env);
    if (authResult) return authResult;

    const url = new URL(request.url);
    const target = `${WECHAT_API_ORIGIN}${url.pathname}${url.search}`;

    const headers = new Headers();
    for (const [key, value] of request.headers) {
      if (['host', 'authorization', 'cf-connecting-ip', 'cf-ray'].includes(key.toLowerCase())) continue;
      headers.set(key, value);
    }

    const init = { method: request.method, headers };
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      init.body = request.body;
    }

    try {
      const resp = await fetch(target, init);
      const responseHeaders = new Headers(resp.headers);
      applyCors(responseHeaders);
      return new Response(resp.body, {
        status: resp.status,
        headers: responseHeaders,
      });
    } catch (err) {
      return jsonError(502, `upstream error: ${err.message}`);
    }
  },
};

function authenticate(request, env) {
  const token = env.PROXY_TOKEN;
  if (!token) return jsonError(500, 'PROXY_TOKEN not configured');

  const auth = request.headers.get('Authorization') || '';
  if (auth !== `Bearer ${token}`) {
    return jsonError(401, 'unauthorized');
  }
  return null;
}

function jsonError(status, message) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders() },
  });
}

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
  };
}

function applyCors(headers) {
  headers.set('Access-Control-Allow-Origin', '*');
}
