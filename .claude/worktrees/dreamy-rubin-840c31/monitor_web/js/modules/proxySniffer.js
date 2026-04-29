// ── Proxy Sniffer Management ─────────────────────────────────────────
// Enable/disable/configure the local mitmproxy sniffer subprocess.

import { api } from '../api.js';

/** Get proxy sniffer status */
export async function getStatus() {
  return api('GET', '/proxy/status');
}

/** Enable the proxy sniffer */
export async function enable() {
  return api('POST', '/proxy/enable');
}

/** Disable the proxy sniffer */
export async function disable() {
  return api('POST', '/proxy/disable');
}

/** Get proxy sniffer config */
export async function getConfig() {
  return api('GET', '/proxy/config');
}

/** Update proxy sniffer config */
export async function updateConfig(cfg) {
  return api('POST', '/proxy/config', cfg);
}

/** Trigger a URL capture download */
export async function downloadCapture(url, outputPath = '') {
  return api('POST', '/proxy/download', { url, output_path: outputPath });
}

/** Open or unset system HTTP proxy */
export async function setSystemProxy(action) {
  return api('POST', '/proxy/system-proxy', { action });
}

/** Install the CA certificate */
export async function installCert() {
  return api('POST', '/proxy/cert/install');
}

/** Refresh status and render into the page DOM */
export async function refreshStatus() {
  const status = await getStatus();
  renderStatus(status);
  return status;
}

// ── DOM Rendering ───────────────────────────────────────────────────

/** Render status into status-card elements */
function renderStatus(status) {
  const statusTextEl = document.getElementById('proxy-status-text');
  const portTextEl = document.getElementById('proxy-port-text');
  const enableBtn = document.getElementById('btn-proxy-enable');
  const disableBtn = document.getElementById('btn-proxy-disable');

  if (statusTextEl) {
    statusTextEl.textContent = status.running
      ? (window.I18n ? window.I18n.t('PROXY_SNIFFER.statusRunning') : 'Running')
      : (window.I18n ? window.I18n.t('PROXY_SNIFFER.statusStopped') : 'Stopped');
    statusTextEl.className = 'badge ' + (status.running ? 'badge--success' : 'badge--secondary');
  }
  if (portTextEl) {
    portTextEl.textContent = status.port || 8899;
  }
  if (enableBtn) enableBtn.disabled = !!status.running;
  if (disableBtn) disableBtn.disabled = !status.running;
}

// ── Page Init (called by router.js when page is shown) ───────────────

/** Bind button events for settings-proxy page. Called by router.js. */
export function initSettingsProxyPage() {
  // Refresh
  document.getElementById('btn-proxy-refresh')?.addEventListener('click', () => {
    refreshStatus();
  });

  // Enable
  document.getElementById('btn-proxy-enable')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-proxy-enable');
    if (btn) btn.disabled = true;
    try {
      const r = await enable();
      if (r.error) { alert(r.error); return; }
      await refreshStatus();
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // Disable
  document.getElementById('btn-proxy-disable')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-proxy-disable');
    if (btn) btn.disabled = true;
    try {
      const r = await disable();
      if (r.error) { alert(r.error); return; }
      await refreshStatus();
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // Install cert
  document.getElementById('btn-cert-install')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-cert-install');
    if (btn) btn.disabled = true;
    try {
      const r = await installCert();
      if (r.error) { alert(r.error); return; }
      alert(window.I18n ? window.I18n.t('PROXY_SNIFFER.certInstallSuccess') : '证书安装成功，请重启浏览器生效');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // System proxy on
  document.getElementById('btn-proxy-system-on')?.addEventListener('click', async () => {
    const r = await setSystemProxy('open');
    if (r.error) { alert(r.error); return; }
    alert(window.I18n ? window.I18n.t('PROXY_SNIFFER.systemProxyOnSuccess') : '系统代理已开启');
  });

  // System proxy off
  document.getElementById('btn-proxy-system-off')?.addEventListener('click', async () => {
    const r = await setSystemProxy('unset');
    if (r.error) { alert(r.error); return; }
    alert(window.I18n ? window.I18n.t('PROXY_SNIFFER.systemProxyOffSuccess') : '系统代理已关闭');
  });

  // Initial load
  refreshStatus();
}

// Expose as window.init_settings_proxy_page for router.js
window.init_settings_proxy_page = initSettingsProxyPage;
