// ── HTML partials: fetch server templates into placeholder nodes ─────
// 与 /templates/*.html 约定一致（见 server/__main__.py 静态目录说明）。

/** @typedef {{ mountId: string, url: string }} PartialSpec */

/**
 * 顶部栏与弹窗子模板的挂载点与 URL 映射（顺序无关，并行加载）。
 * @type {readonly PartialSpec[]}
 */
const PARTIAL_SPECS = [
  { mountId: 'app-header', url: '/templates/header.html' },
  { mountId: 'tpl-modal-account', url: '/templates/modals/modal-account.html' },
  { mountId: 'tpl-modal-proxy-pools', url: '/templates/modals/modal-proxy-pools.html' },
  { mountId: 'tpl-modal-proxy-pool-form', url: '/templates/modals/modal-proxy-pool-form.html' },
  { mountId: 'tpl-modal-proxy-pool-demo', url: '/templates/modals/modal-proxy-pool-demo.html' },
  { mountId: 'tpl-modal-video-detail', url: '/templates/modals/modal-video-detail.html' },
  { mountId: 'tpl-modal-scan-confirm', url: '/templates/modals/modal-scan-confirm.html' },
  { mountId: 'tpl-modal-api-keys', url: '/templates/modals/modal-api-keys.html' },
  { mountId: 'tpl-modal-api-key-form', url: '/templates/modals/modal-api-key-form.html' },
  { mountId: 'tpl-modal-cache', url: '/templates/modals/modal-cache.html' },
  { mountId: 'tpl-modal-config', url: '/templates/modals/modal-config.html' },
  { mountId: 'tpl-modal-dynamic-providers', url: '/templates/modals/modal-dynamic-providers.html' },
  { mountId: 'tpl-dyn-provider-detail-drawer', url: '/templates/modals/dyn-provider-detail-drawer.html' },
  { mountId: 'tpl-modal-dynamic-provider-form', url: '/templates/modals/modal-dynamic-provider-form.html' },
  { mountId: 'tpl-modal-batch-download', url: '/templates/modals/modal-batch-download.html' },
  { mountId: 'tpl-modal-confirm', url: '/templates/modals/modal-confirm.html' },
  { mountId: 'tpl-modal-clip-history', url: '/templates/modals/modal-clip-history.html' },
  { mountId: 'tpl-modal-clip-detail', url: '/templates/modals/modal-clip-detail.html' },
  { mountId: 'tpl-page-settings', url: '/templates/pages/settings-hub.html' },
  { mountId: 'tpl-page-settings-notify', url: '/templates/pages/settings-notify.html' },
  { mountId: 'tpl-page-settings-api', url: '/templates/pages/settings-api.html' },
  { mountId: 'tpl-page-settings-download', url: '/templates/pages/settings-download.html' },
  { mountId: 'tpl-page-settings-ai', url: '/templates/pages/settings-ai.html' },
  { mountId: 'tpl-page-settings-dynamic', url: '/templates/pages/settings-dynamic.html' },
  { mountId: 'tpl-page-settings-proxy', url: '/templates/pages/settings-proxy.html' },
];

/**
 * 从服务端拉取各 partial HTML 并写入对应占位节点。须在首屏数据和交互（refresh）之前完成。
 * @returns {Promise<void>}
 */
export async function loadPartials() {
  await Promise.all(
    PARTIAL_SPECS.map(async ({ mountId, url }) => {
      const node = document.getElementById(mountId);
      if (!node) return;
      const res = await fetch(url, { credentials: 'same-origin' });
      if (!res.ok) {
        throw new Error(`加载模板失败 ${url} (${res.status})`);
      }
      const html = await res.text();
      node.innerHTML = html;
    }),
  );
}
