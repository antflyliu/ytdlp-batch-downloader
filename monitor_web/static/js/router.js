// router.js — SPA hash routing
const Router = {
  routes: {},

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
  });
}

function showPage(name) {
  document.querySelectorAll('.page').forEach(el => el.classList.remove('page--active'));
  const page = document.getElementById('page-' + name);
  if (page) page.classList.add('page--active');

  document.querySelectorAll('.sidebar__item').forEach(el => el.classList.remove('sidebar__item--active'));
  const navItem = document.querySelector(`.sidebar__item[data-page="${name}"]`);
  if (navItem) navItem.classList.add('sidebar__item--active');
}
