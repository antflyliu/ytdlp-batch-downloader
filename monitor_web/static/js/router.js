// router.js — SPA hash routing

/** 路由 page id → i18n key（与 static/i18n/*.json 中 nav.* 一致） */
const PAGE_TO_NAV_I18N = {
  dashboard: 'nav.dashboard',
  channels: 'nav.channels',
  downloads: 'nav.downloads',
  'api-keys': 'nav.apiKeys',
  'proxy-pools': 'nav.proxyPools',
  'dynamic-providers': 'nav.dynamicProviders',
  'clip-history': 'nav.clipHistory',
  settings: 'nav.settings',
  'settings-notify': 'nav.settingsNotify',
  'settings-api': 'nav.settingsApi',
  'settings-download': 'nav.settingsDownload',
  'settings-ai': 'nav.settingsAi',
  'settings-dynamic': 'nav.settingsDynamic',
};

/**
 * 顶栏副标题与当前侧栏选中项文案一致（随语言包切换）。
 * @param {string} pageName
 */
function updateHeaderNavTitle(pageName) {
  const el = document.getElementById('headerNavTitle');
  if (!el) return;
  const key = PAGE_TO_NAV_I18N[pageName] || 'nav.dashboard';
  el.setAttribute('data-i18n', key);
  const I = window.I18n;
  if (I && typeof I.t === 'function') {
    const text = I.t(key);
    if (text && text !== key) {
      el.textContent = text;
      return;
    }
  }
  const navLbl = document.querySelector(`.sidebar__item[data-page="${pageName}"] .sidebar__item-label`);
  if (navLbl) el.textContent = navLbl.textContent.trim();
}

const Router = {
  routes: {},
  _activePage: null,

  init(routes) {
    this.routes = routes;
    window.addEventListener('hashchange', () => this.render());
    this.render();
  },

  navigate(hash) {
    window.location.hash = hash;
  },

  render() {
    const hash = window.location.hash || '#/dashboard';
    const page = hash.replace('#/', '') || 'dashboard';
    const handler = this.routes[page];
    if (handler) handler();
  }
};

export function initRouter() {
  Router.init({
    dashboard: () => showPage('dashboard'),
    channels: () => showPage('channels'),
    downloads: () => showPage('downloads'),
    'api-keys': () => showPage('api-keys'),
    'proxy-pools': () => showPage('proxy-pools'),
    'dynamic-providers': () => showPage('dynamic-providers'),
    'clip-history': () => showPage('clip-history'),
    settings: () => showPage('settings'),
    'settings-notify': () => showPage('settings-notify'),
    'settings-api': () => showPage('settings-api'),
    'settings-download': () => showPage('settings-download'),
    'settings-ai': () => showPage('settings-ai'),
    'settings-dynamic': () => showPage('settings-dynamic'),
  });
}

function showPage(name) {
  // 离开配置页或其它长页后必须重置主滚动条，否则 .main.scrollTop 保留在底部，
  // 切回「数据概览」等短页会出现顶部被裁切、底部大块空白（影响所有栏目）。
  const mainEl = document.querySelector('.main');
  if (mainEl) mainEl.scrollTop = 0;
  if (typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.scrollTop = 0;
  }
  if (typeof document !== 'undefined' && document.body) {
    document.body.scrollTop = 0;
  }

  document.querySelectorAll('.page').forEach(el => el.classList.remove('page--active'));
  const pageDomId = 'page-' + name;
  const page = document.getElementById(pageDomId);
  if (page) page.classList.add('page--active');

  document.querySelectorAll('.sidebar__item').forEach(el => {
    el.classList.remove('sidebar__item--active');
    el.classList.remove('sidebar__item--active-parent');
  });
  const navItem = document.querySelector(`.sidebar__item[data-page="${name}"]`);
  if (navItem) navItem.classList.add('sidebar__item--active');
  if (name.startsWith('settings-')) {
    const parent = document.querySelector('.sidebar__item[data-page="settings"]');
    if (parent) parent.classList.add('sidebar__item--active-parent');
  }

  updateHeaderNavTitle(name);

  if (window.Sidebar && typeof window.Sidebar.syncSettingsGroupFromRoute === 'function') {
    window.Sidebar.syncSettingsGroupFromRoute(name);
  }

  // Call page-specific init if exists (avoids re-initing same page)
  if (Router._activePage !== name) {
    Router._activePage = name;
    const initFn = window[`init_${name.replace(/-/g, '_')}_page`];
    if (typeof initFn === 'function') initFn();
  }
}
