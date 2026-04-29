# Monitor Web UI 重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Monitor Web UI 重构为左侧可折叠导航 + 右侧内容区，采用 Claude Design System 暖色亮色主题，统一所有组件 Design Tokens。

**Architecture:**
- 纯 HTML/CSS/JS 单页应用，通过 URL hash 路由切换页面
- CSS 变量统一管理 Design Tokens，覆盖现有 variables.css
- 左侧 Sidebar 组件支持折叠/展开，状态持久化到 localStorage
- 国际化通过 `static/i18n/` JSON 文件实现中英文切换

**Tech Stack:** 纯 HTML/CSS/JS（无框架），现有 ffmpeg + Python backend 不变

---

## 文件结构

```
monitor_web/
├── index.html                      # 主 HTML（需重构布局）
├── static/
│   ├── css/
│   │   ├── variables.css           # [重构] CSS 变量（Claude 色系）
│   │   ├── layout.css             # [重构] 整体布局（Sidebar + TopBar）
│   │   ├── sidebar.css            # [新建] 侧边栏样式
│   │   ├── common.css             # [重构] 统一组件类（BEM）
│   │   ├── modal.css              # [重构] 模态框样式
│   │   ├── form.css               # [重构] 表单样式
│   │   ├── table.css              # [重构] 表格样式
│   │   ├── toast.css              # [重构] Toast 样式
│   │   └── components.css         # [保留] 其他组件
│   ├── js/
│   │   ├── app.js                 # [重构] 主入口（路由初始化）
│   │   ├── router.js              # [新建] SPA hash 路由
│   │   ├── sidebar.js             # [新建] Sidebar 组件
│   │   ├── i18n.js                # [新建] 国际化模块
│   │   └── modules/
│   │       └── config.js          # [修改] 配置读写
│   └── i18n/
│       ├── zh.json                # [新建] 中文翻译
│       └── en.json                # [新建] 英文翻译
└── templates/
    └── header.html                # [保留] 顶部栏模板
```

---

## 任务列表

### Phase 1：布局框架

#### Task 1: 重写 variables.css（Claude Design System 色系）

**Files:**
- Modify: `monitor_web/static/css/variables.css`

- [ ] **Step 1: 备份并重写 variables.css**

将现有的暗色变量替换为 Claude Design System 亮色变量：

```css
:root {
  /* === Claude Design System === */
  /* Surface & Background */
  --bg: #f5f4ed;                  /* Parchment: 页面背景 */
  --surface: #faf9f5;              /* Ivory: 卡片/容器背景 */
  --surface2: #f0eee6;             /* Border Cream: 次级表面 */
  --surface3: #e8e6dc;             /* Warm Sand: 按钮/交互表面 */
  --border: #e8e6dc;              /* Border Warm: 边框色 */

  /* Text */
  --text: #141413;                /* Near Black: 主文字 */
  --text-muted: #5e5d59;          /* Olive Gray: 次要文字 */
  --text-dim: #87867f;            /* Stone Gray: 辅助文字 */

  /* Brand Accent */
  --accent: #c96442;              /* Terracotta Brand: 主强调色 */
  --accent-hover: #d97757;        /* Coral Accent: 悬浮态 */
  --accent-dim: rgba(201,100,66,0.12);
  --accent-ring: rgba(201,100,66,0.30);

  /* Semantic */
  --success: #22c55e;
  --success-dim: rgba(34,197,94,0.12);
  --error: #b53333;
  --error-dim: rgba(181,51,51,0.12);
  --warning: #f59e0b;
  --warning-dim: rgba(245,158,11,0.12);

  /* Platform */
  --feishu: #7B68EE;
  --dingtalk: #1677FF;
  --wecom: #52C41A;
  --telegram: #26A5E4;

  /* Radius — 8档 */
  --r-xs:   4px;   /* micro badges */
  --r-sm:   6px;   /* small inputs / tags */
  --r-md:   8px;   /* standard buttons / cards */
  --r-lg:   12px;  /* modals / large cards */
  --r-xl:   16px;  /* featured containers */
  --r-2xl:  24px;  /* special containers */
  --r-full: 9999px; /* pills / chips */

  /* Depth */
  --shadow-whisper: 0px 4px 24px rgba(0,0,0,0.05);
  --shadow-ring: 0px 0px 0px 1px;

  /* Ring */
  --ring-subtle: 0 0 0 1px rgba(0,0,0,0.06);
  --ring-medium: 0 0 0 1px rgba(0,0,0,0.12);

  /* Typography */
  --font: 'Georgia', -apple-system, BlinkMacSystemFont, 'Segoe UI', serif;
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --mono: 'JetBrains Mono', 'Cascadia Code', monospace;

  /* Sidebar (Dark) */
  --sidebar-bg: #141413;
  --sidebar-surface: #1c1c1a;
  --sidebar-border: #30302e;
  --sidebar-text: #b0aea5;
  --sidebar-text-active: #faf9f5;
  --sidebar-hover: #30302e;
  --sidebar-active: #c96442;  /* Terracotta left border */

  /* Scrollbar */
  --scrollbar-thumb: #d1cfc5;
  --scrollbar-track: #f5f4ed;
}
```

- [ ] **Step 2: 验证变量覆盖**

运行：`grep -r "var(--" monitor_web/static/css/ | head -20` 确认所有 CSS 使用 CSS 变量

---

#### Task 2: 新建 sidebar.css

**Files:**
- Create: `monitor_web/static/css/sidebar.css`

- [ ] **Step 1: 编写侧边栏 CSS**

```css
/* ── Sidebar ─────────────────────────────────────────────────────────── */
.sidebar {
  position: fixed;
  left: 0; top: 0; bottom: 0;
  width: var(--sidebar-width, 220px);
  background: var(--sidebar-bg);
  border-right: 1px solid var(--sidebar-border);
  display: flex;
  flex-direction: column;
  transition: width 250ms ease-out;
  z-index: 100;
  overflow: hidden;
}

.sidebar--collapsed {
  width: 56px;
}

.sidebar__logo {
  padding: 16px;
  border-bottom: 1px solid var(--sidebar-border);
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 60px;
}

.sidebar__logo-icon {
  width: 28px; height: 28px;
  background: var(--accent);
  border-radius: var(--r-md);
  display: flex; align-items: center; justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}

.sidebar__logo-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--sidebar-text-active);
  white-space: nowrap;
}

.sidebar--collapsed .sidebar__logo-text { display: none; }

.sidebar__nav {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px 0;
}

.sidebar__item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  color: var(--sidebar-text);
  text-decoration: none;
  font-size: 14px;
  border-left: 3px solid transparent;
  transition: all 150ms ease-out;
  cursor: pointer;
  white-space: nowrap;
}

.sidebar__item:hover {
  background: var(--sidebar-hover);
  color: var(--sidebar-text-active);
}

.sidebar__item--active {
  background: var(--sidebar-hover);
  color: var(--sidebar-text-active);
  border-left-color: var(--sidebar-active);
}

.sidebar__item-icon {
  width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.sidebar__item-label {
  flex: 1;
  overflow: hidden;
}

.sidebar--collapsed .sidebar__item-label { display: none; }
.sidebar--collapsed .sidebar__item { padding: 10px 18px; justify-content: center; }

.sidebar__footer {
  padding: 8px 0;
  border-top: 1px solid var(--sidebar-border);
}

.sidebar__toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 10px 16px;
  background: none;
  border: none;
  color: var(--sidebar-text);
  font-size: 13px;
  cursor: pointer;
  transition: all 150ms ease-out;
}

.sidebar__toggle:hover { background: var(--sidebar-hover); color: var(--sidebar-text-active); }
.sidebar__toggle-icon { transition: transform 250ms ease-out; }
.sidebar--collapsed .sidebar__toggle-icon { transform: rotate(180deg); }
.sidebar--collapsed .sidebar__toggle-label { display: none; }

/* ── Layout with Sidebar ────────────────────────────────────────────── */
.app {
  display: flex;
  height: 100vh;
  height: 100dvh;
}

.app__main {
  margin-left: var(--sidebar-width, 220px);
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  transition: margin-left 250ms ease-out;
}

.app__main--sidebar-collapsed {
  margin-left: 56px;
}

/* ── Header ─────────────────────────────────────────────────────────── */
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  gap: 16px;
  flex: 0 0 60px;
}

.header-left { display: flex; align-items: center; gap: 16px; }
.header-right { display: flex; align-items: center; gap: 8px; }

/* ── Main Content ──────────────────────────────────────────────────── */
.main {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ── Page Sections ─────────────────────────────────────────────────── */
.page { display: none; }
.page--active { display: block; }

/* ── Scrollbar ─────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--scrollbar-track); }
::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--ring-medium); }
```

---

#### Task 3: 新建 router.js

**Files:**
- Create: `monitor_web/static/js/router.js`

- [ ] **Step 1: 实现 SPA Hash 路由**

```javascript
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
```

---

#### Task 4: 新建 sidebar.js

**Files:**
- Create: `monitor_web/static/js/sidebar.js`

- [ ] **Step 1: 实现 Sidebar 组件**

```javascript
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
```

---

#### Task 5: 重构 index.html（添加 Sidebar + 页面 Section）

**Files:**
- Modify: `monitor_web/index.html`

- [ ] **Step 1: 替换 body 内容为 Sidebar + Main 结构**

```html
<body>
<div class="app" id="app">
  <!-- 侧边栏 -->
  <nav class="sidebar" id="sidebar">
    <div class="sidebar__logo">
      <div class="sidebar__logo-icon">▶</div>
      <span class="sidebar__logo-text">YouTube 监控</span>
    </div>
    <div class="sidebar__nav">
      <a class="sidebar__item sidebar__item--active" data-page="dashboard">
        <span class="sidebar__item-icon">📊</span>
        <span class="sidebar__item-label">数据概览</span>
      </a>
      <a class="sidebar__item" data-page="channels">
        <span class="sidebar__item-icon">📺</span>
        <span class="sidebar__item-label">账户管理</span>
      </a>
      <a class="sidebar__item" data-page="downloads">
        <span class="sidebar__item-icon">⬇️</span>
        <span class="sidebar__item-label">批量下载</span>
      </a>
      <a class="sidebar__item" data-page="api-keys">
        <span class="sidebar__item-icon">🔑</span>
        <span class="sidebar__item-label">API Keys</span>
      </a>
      <a class="sidebar__item" data-page="proxy-pools">
        <span class="sidebar__item-icon">🌐</span>
        <span class="sidebar__item-label">代理池</span>
      </a>
      <a class="sidebar__item" data-page="dynamic-providers">
        <span class="sidebar__item-icon">🔄</span>
        <span class="sidebar__item-label">动态代理</span>
      </a>
      <a class="sidebar__item" data-page="clip-history">
        <span class="sidebar__item-icon">✂️</span>
        <span class="sidebar__item-label">切片历史</span>
      </a>
      <a class="sidebar__item" data-page="settings">
        <span class="sidebar__item-icon">⚙️</span>
        <span class="sidebar__item-label">全局配置</span>
      </a>
    </div>
    <div class="sidebar__footer">
      <button class="sidebar__toggle" id="sidebarToggle">
        <span class="sidebar__toggle-icon">‹</span>
        <span class="sidebar__toggle-label">收起</span>
      </button>
    </div>
  </nav>

  <!-- 主内容区 -->
  <div class="app__main" id="appMain">
    <!-- 顶部栏 -->
    <header class="header">
      <div class="header-left">
        <span style="font-size:13px;color:var(--text-muted)">YouTube 监控</span>
      </div>
      <div class="header-right">
        <button class="btn btn--sm btn--ghost" id="langToggle">CN / EN</button>
      </div>
    </header>

    <!-- 页面内容 -->
    <main class="main">
      <!-- Dashboard -->
      <section class="page page--active" id="page-dashboard">
        <div class="card">
          <div class="stats-grid" id="statsGrid">
            <div class="stat-card">...</div>
          </div>
        </div>
        <div class="card">
          <div class="card-header">扫描事件日志</div>
          <div class="card-body">
            <div class="log-area" id="logArea">...</div>
          </div>
        </div>
      </section>

      <!-- Channels -->
      <section class="page" id="page-channels">
        <!-- 账户列表完整内容迁移至此 -->
      </section>

      <!-- Downloads -->
      <section class="page" id="page-downloads"></section>

      <!-- API Keys -->
      <section class="page" id="page-api-keys"></section>

      <!-- Proxy Pools -->
      <section class="page" id="page-proxy-pools"></section>

      <!-- Dynamic Providers -->
      <section class="page" id="page-dynamic-providers"></section>

      <!-- Clip History -->
      <section class="page" id="page-clip-history"></section>

      <!-- Settings -->
      <section class="page" id="page-settings"></section>
    </main>
  </div>
</div>

<!-- 所有弹窗保留在 body 最后 -->
<!-- ... modals ... -->

<script type="module" src="/js/app.js"></script>
</body>
```

- [ ] **Step 2: 更新 CSS 引用**

在 `<head>` 中添加 `sidebar.css` 引用：

```html
<link rel="stylesheet" href="/static/css/sidebar.css">
```

---

### Phase 2: 样式换肤

#### Task 6: 重构 common.css（统一 BEM 组件）

**Files:**
- Modify: `monitor_web/static/css/common.css`

- [ ] **Step 1: 重构按钮系统为 BEM**

```css
/* ── Buttons (BEM) ──────────────────────────────────────────────────── */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: var(--r-md);
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all var(--transition-fast, 150ms ease-out);
  text-decoration: none;
  white-space: nowrap;
}

.btn--primary { background: var(--accent); color: var(--surface); }
.btn--primary:hover { background: var(--accent-hover); }
.btn--success { background: var(--success); color: #fff; }
.btn--success:hover { filter: brightness(1.1); }
.btn--danger { background: var(--error); color: #fff; }
.btn--danger:hover { filter: brightness(1.1); }
.btn--warning { background: var(--warning); color: #fff; }
.btn--warning:hover { filter: brightness(1.1); }
.btn--ghost {
  background: transparent;
  color: var(--text-muted);
  border: 1px solid var(--border);
}
.btn--ghost:hover { background: var(--surface2); color: var(--text); }
.btn--sm { padding: 4px 12px; font-size: 12px; }
.btn--icon {
  width: 36px; height: 36px; padding: 0;
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--r-sm);
  background: var(--surface2);
  color: var(--text-muted);
  border: 1px solid var(--border);
  cursor: pointer;
  font-size: 16px;
}
.btn--icon:hover { background: var(--surface3); color: var(--text); }
```

- [ ] **Step 2: 重构 Tag 系统为 BEM**

```css
/* ── Tags (BEM) ─────────────────────────────────────────────────────── */
.tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--r-xs);
  font-size: 12px;
  font-weight: 500;
}
.tag--success { background: #dcfce7; color: #166534; }
.tag--warning { background: #fef3c7; color: #92400e; }
.tag--error { background: #fee2e2; color: #991b1b; }
.tag--info { background: var(--accent-dim); color: var(--accent); }
```

- [ ] **Step 3: 重构 Status 系统为 BEM**

```css
/* ── Status (BEM) ──────────────────────────────────────────────────── */
.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--r-full);
  font-size: 12px;
  font-weight: 500;
}
.status__dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: currentColor;
}
.status--running { background: var(--success-dim); color: var(--success); }
.status--stopped { background: var(--surface2); color: var(--text-muted); }
.status--running .status__dot { animation: pulse 2s ease-in-out infinite; }
```

---

#### Task 7: 重构 modal.css

**Files:**
- Modify: `monitor_web/static/css/modal.css`

- [ ] **Step 1: 统一模态框 BEM 结构**

```css
/* ── Modal (BEM) ───────────────────────────────────────────────────── */
.modal {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0,0,0,0.3);
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--transition-normal, 250ms ease-out);
}
.modal--open { opacity: 1; pointer-events: auto; }

.modal__container {
  background: var(--surface);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-whisper);
  width: 90%;
  max-width: 560px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  transform: translateY(8px);
  transition: transform var(--transition-normal, 250ms ease-out);
}
.modal--open .modal__container { transform: translateY(0); }

.modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.modal__title { font-size: 15px; font-weight: 600; color: var(--text); }
.modal__close {
  width: 28px; height: 28px;
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--r-sm);
  background: none; border: none;
  color: var(--text-muted); cursor: pointer; font-size: 18px;
}
.modal__close:hover { background: var(--surface2); color: var(--text); }

.modal__body { padding: 20px; overflow-y: auto; flex: 1; }
.modal__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border);
}
```

---

#### Task 8: 重构 form.css

**Files:**
- Modify: `monitor_web/static/css/form.css`

- [ ] **Step 1: 统一表单输入框 BEM**

```css
/* ── Form Inputs (BEM) ──────────────────────────────────────────────── */
.form-input {
  width: 100%;
  padding: 8px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  font-family: var(--font-sans);
  font-size: 14px;
  color: var(--text);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  outline: none;
}
.form-input:focus {
  border-color: var(--accent);
  box-shadow: var(--shadow-ring) var(--accent);
}
.form-input::placeholder { color: var(--text-dim); }
.form-input--error { border-color: var(--error); }

.form-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 6px;
}

.form-group { margin-bottom: 16px; }

.form-hint {
  font-size: 12px;
  color: var(--text-dim);
  margin-top: 4px;
}

/* Checkbox */
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 14px;
  color: var(--text);
}
.checkbox-box {
  width: 18px; height: 18px;
  border: 1px solid var(--border);
  border-radius: var(--r-xs);
  background: var(--surface);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}
.checkbox-label input:checked + .checkbox-box {
  background: var(--accent);
  border-color: var(--accent);
}
```

---

#### Task 9: 重构 table.css

**Files:**
- Modify: `monitor_web/static/css/table.css`

- [ ] **Step 1: 统一表格 BEM**

```css
/* ── Table (BEM) ─────────────────────────────────────────────────────── */
.table-wrap { overflow-x: auto; border-radius: var(--r-md); }
.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.table__header-cell {
  text-align: left;
  padding: 10px 16px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
  background: var(--surface2);
  white-space: nowrap;
}
.table__cell {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
}
.table__row:last-child .table__cell { border-bottom: none; }
.table__row:hover .table__cell { background: var(--bg); }
```

---

### Phase 3: 国际化

#### Task 10: 新建 i18n 模块

**Files:**
- Create: `monitor_web/static/i18n/zh.json`
- Create: `monitor_web/static/i18n/en.json`
- Create: `monitor_web/static/js/i18n.js`

- [ ] **Step 1: 创建中文翻译文件**

```json
{
  "nav": {
    "dashboard": "数据概览",
    "channels": "账户管理",
    "downloads": "批量下载",
    "apiKeys": "API Keys",
    "proxyPools": "代理池",
    "dynamicProviders": "动态代理",
    "clipHistory": "切片历史",
    "settings": "全局配置"
  },
  "common": {
    "add": "添加",
    "edit": "编辑",
    "delete": "删除",
    "save": "保存",
    "cancel": "取消",
    "confirm": "确认",
    "search": "搜索",
    "loading": "加载中...",
    "noData": "暂无数据",
    "actions": "操作"
  },
  "dashboard": {
    "title": "数据概览",
    "accounts": "监控账户",
    "totalScans": "总扫描次数",
    "newVideos": "新增视频",
    "quota": "API Quota",
    "lastScan": "最后扫描"
  }
}
```

- [ ] **Step 2: 创建英文翻译文件**

```json
{
  "nav": {
    "dashboard": "Dashboard",
    "channels": "Channels",
    "downloads": "Downloads",
    "apiKeys": "API Keys",
    "proxyPools": "Proxy Pools",
    "dynamicProviders": "Dynamic Providers",
    "clipHistory": "Clip History",
    "settings": "Settings"
  },
  "common": {
    "add": "Add",
    "edit": "Edit",
    "delete": "Delete",
    "save": "Save",
    "cancel": "Cancel",
    "confirm": "Confirm",
    "search": "Search",
    "loading": "Loading...",
    "noData": "No Data",
    "actions": "Actions"
  },
  "dashboard": {
    "title": "Dashboard",
    "accounts": "Monitored Accounts",
    "totalScans": "Total Scans",
    "newVideos": "New Videos",
    "quota": "API Quota",
    "lastScan": "Last Scan"
  }
}
```

- [ ] **Step 3: 实现 i18n.js**

```javascript
// i18n.js
const I18n = {
  lang: localStorage.getItem('lang') || 'zh',
  translations: {},

  async init() {
    const res = await fetch(`/i18n/${this.lang}.json`);
    this.translations = await res.json();
    this.apply();
    document.documentElement.lang = this.lang;
  },

  t(key) {
    const keys = key.split('.');
    let val = this.translations;
    for (const k of keys) val = val?.[k];
    return val || key;
  },

  async switchLang() {
    this.lang = this.lang === 'zh' ? 'en' : 'zh';
    localStorage.setItem('lang', this.lang);
    await this.init();
  },

  apply() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      el.textContent = this.t(key);
    });
  }
};

window.I18n = I18n;
```

- [ ] **Step 4: 添加语言切换按钮事件**

在 `sidebar.js` 或 `app.js` 中：

```javascript
document.getElementById('langToggle').addEventListener('click', () => I18n.switchLang());
```

---

### Phase 4: 内容迁移

#### Task 11: 迁移 Channels 页面

**Files:**
- Modify: `monitor_web/index.html` (将现有账户表格迁移到 `#page-channels` section)
- Modify: `monitor_web/js/app.js` (路由初始化 + 内容加载)

- [ ] **Step 1: 将现有 index.html 中的账户表格 HTML 迁移到 `#page-channels` section**

---

#### Task 12: 迁移其他页面内容

**Files:**
- Modify: `monitor_web/index.html` (各 `#page-xxx` section 填充对应弹窗内容)

- [ ] **Step 1: 将现有弹窗内容提取到对应页面 section**

---

### Phase 5: 测试验证

#### Task 13: 手动测试所有导航切换

- [ ] **Step 1: 测试侧边栏折叠/展开**
- [ ] **Step 2: 测试所有 8 个导航项切换**
- [ ] **Step 3: 测试语言切换（CN ↔ EN）**
- [ ] **Step 4: 测试刷新后路由状态保持**
- [ ] **Step 5: 验证所有弹窗/抽屉是否正常弹出**

---

**预计文件变更:**
- 新建: 4 个文件（sidebar.css, router.js, sidebar.js, i18n.js）
- 新建: 2 个翻译文件（zh.json, en.json）
- 修改: 8 个 CSS 文件（variables, common, modal, form, table, toast, layout, index.html）
- 测试: 手动测试为主（无自动化 E2E）