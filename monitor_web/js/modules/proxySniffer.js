// ── Proxy Sniffer Management ─────────────────────────────────────────
// Enable/disable/configure the local mitmproxy sniffer subprocess.

import { api } from '../api.js';

/** Get proxy sniffer status */
export async function getStatus() {
  return api('GET', '/api/proxy/status');
}

/** Enable the proxy sniffer */
export async function enable() {
  return api('POST', '/api/proxy/enable');
}

/** Disable the proxy sniffer */
export async function disable() {
  return api('POST', '/api/proxy/disable');
}

/** Get proxy sniffer config */
export async function getConfig() {
  return api('GET', '/api/proxy/config');
}

/** Update proxy sniffer config */
export async function updateConfig(cfg) {
  return api('POST', '/api/proxy/config', cfg);
}

/** Trigger a URL capture download */
export async function downloadCapture(url, outputPath = '') {
  return api('POST', '/api/proxy/download', { url, output_path: outputPath });
}

/** Open or unset system HTTP proxy */
export async function setSystemProxy(action) {
  return api('POST', '/api/proxy/system-proxy', { action });
}

/** Install the CA certificate */
export async function installCert() {
  return api('POST', '/api/proxy/cert/install');
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
