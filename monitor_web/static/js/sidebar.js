// sidebar.js — Sidebar toggle + collapse state
const Sidebar = {
  COLLAPSED_KEY: 'sidebar_collapsed',

  init() {
    const collapsed = localStorage.getItem(this.COLLAPSED_KEY) === 'true';
    this.toggle(collapsed, false);  // false = don't animate on init
    document.getElementById('sidebarToggle').addEventListener('click', () => this.toggle());
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
  }
};
