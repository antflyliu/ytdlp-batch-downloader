// sidebar.js — Sidebar toggle + collapse state
const Sidebar = {
  COLLAPSED_KEY: 'sidebar_collapsed',
  /** 配置中心子菜单：在「配置中心」概览页是否展开（子路由页会强制展开） */
  SETTINGS_SUBNAV_EXPANDED_KEY: 'sidebar_settings_subnav_expanded',

  init() {
    const collapsed = localStorage.getItem(this.COLLAPSED_KEY) === 'true';
    this.toggle(collapsed, false);  // false = don't animate on init
    const footerBtn = document.getElementById('sidebarToggle');
    if (footerBtn) footerBtn.addEventListener('click', () => this.toggle());
    const logoBtn = document.getElementById('sidebarLogoToggle');
    if (logoBtn) logoBtn.addEventListener('click', () => this.toggle());
    this.initSettingsGroupToggle();
  },

  /**
   * 根据当前路由同步「配置中心」子菜单展开状态。
   * - 在任意 `settings-*` 子页：展开，便于看到当前入口。
   * - 在 `settings` 概览：沿用用户偏好（默认收起）。
   * - 离开配置相关页：收起。
   * @param {string} pageName
   */
  syncSettingsGroupFromRoute(pageName) {
    const group = document.getElementById('sidebarSettingsGroup');
    const btn = document.getElementById('sidebarSettingsToggle');
    if (!group || !btn) return;
    let open = false;
    if (pageName.startsWith('settings-')) {
      open = true;
    } else if (pageName === 'settings') {
      open = localStorage.getItem(this.SETTINGS_SUBNAV_EXPANDED_KEY) === 'true';
    }
    group.classList.toggle('sidebar__group--expanded', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  },

  initSettingsGroupToggle() {
    const group = document.getElementById('sidebarSettingsGroup');
    const btn = document.getElementById('sidebarSettingsToggle');
    if (!group || !btn) return;
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const next = !group.classList.contains('sidebar__group--expanded');
      group.classList.toggle('sidebar__group--expanded', next);
      localStorage.setItem(this.SETTINGS_SUBNAV_EXPANDED_KEY, next ? 'true' : 'false');
      btn.setAttribute('aria-expanded', next ? 'true' : 'false');
    });
  },

  toggle(forceCollapsed = null, animate = true) {
    const sidebar = document.getElementById('sidebar');
    const main = document.getElementById('appMain');
    if (!sidebar) return;

    const collapsed = forceCollapsed !== null ? forceCollapsed
      : !sidebar.classList.contains('sidebar--collapsed');

    sidebar.classList.toggle('sidebar--collapsed', collapsed);
    main.classList.toggle('app__main--sidebar-collapsed', collapsed);
    localStorage.setItem(this.COLLAPSED_KEY, collapsed);

    const icon = document.querySelector('#sidebarToggle .sidebar__toggle-icon');
    if (icon) icon.textContent = collapsed ? '>>' : '<<';
  }
};

window.Sidebar = Sidebar;
