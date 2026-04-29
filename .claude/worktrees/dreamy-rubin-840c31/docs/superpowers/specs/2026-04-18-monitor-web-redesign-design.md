# 设计文档：Monitor Web UI 重构 — 左侧导航 + Claude 亮色

---

## 1. 概念与愿景

将当前平铺式监控界面重构为**左侧可折叠图标导航 + 右侧内容区**的仪表盘布局，换用 Claude Design System 暖色羊皮纸色系，营造专业、温暖、可信赖的监控体验。所有功能入口集中到左侧导航，顶部栏仅保留 Logo + 标题 + 语言切换。

---

## 2. 设计语言

### 配色（Claude Design System — 亮色主题）

| 角色 | 颜色 | 用途 |
|------|------|------|
| Parchment | `#f5f4ed` | 页面背景 |
| Ivory | `#faf9f5` | 卡片 / 容器背景 |
| Warm Sand | `#e8e6dc` | 次要按钮背景 |
| Near Black | `#141413` | 侧边栏背景（深色） |
| Dark Surface | `#30302e` | 侧边栏hover / 深色容器 |
| Terracotta Brand | `#c96442` | 当前选中项、强调色 |
| Charcoal Warm | `#4d4c48` | 按钮文字 |
| Olive Gray | `#5e5d59` | 正文次要文字 |
| Stone Gray | `#87867f` | 辅助文字 |
| Border Cream | `#f0eee6` | 浅色边框 |
| Focus Blue | `#3898ec` | 输入聚焦环（唯一冷色） |
| Warm Silver | `#b0aea5` | 深色表面文字 |
| Coral Accent | `#d97757` | 次要强调 |

### 字体

- **Headline / 标题**: Georgia（衬线，回退 Anthropic Serif）
- **Body / UI**: system-ui / Arial（无衬线）
- **Code / 固定宽度**: JetBrains Mono（已有）

### 圆角系统

| 级别 | 半径 | 用途 |
|------|------|------|
| 舒适 | 8px | 标准按钮、卡片 |
| 充裕 | 12px | 主要按钮、输入框 |
| 特色 | 16-32px | 大容器、媒体 |

### 深度系统

- **Level 1**: `1px solid #f0eee6`（卡片边框）
- **Level 2**: `0px 0px 0px 1px` ring shadow（交互状态）
- **Level 3**: `rgba(0,0,0,0.05) 0px 4px 24px`（悬浮卡片）

---

## 3. 布局结构

```
┌─────────────────────────────────────────────────────────────────┐
│  顶部栏（56px，高度固定）                                         │
│  ┌──────┐  YouTube 监控         [语言切换 CN/EN]  [+ 用户操作]    │
│  │ Logo │                                                       │
├──┴──────┴───────────────────────────────────────────────────────┤
│        │                                                        │
│  侧    │    主内容区（根据左侧选中项动态渲染）                    │
│  边    │                                                        │
│  栏    │    ┌──────────────────────────────────────────────┐   │
│        │    │  页面标题                                     │   │
│  56px  │    ├──────────────────────────────────────────────┤   │
│  或    │    │                                              │   │
│ 220px  │    │  页面内容                                     │   │
│        │    │                                              │   │
│        │    └──────────────────────────────────────────────┘   │
│        │                                                        │
└────────┴────────────────────────────────────────────────────────┘
```

### 左侧边栏

- **折叠态**：56px 宽，仅图标，tooltip 提示
- **展开态**：220px 宽，图标 + 文字
- **折叠按钮**：底部一个 chevron 按钮切换
- **状态持久化**：`localStorage.sidebar_collapsed`

### 顶部栏

- 左侧：Logo + "YouTube 监控" 标题
- 右侧：语言切换按钮（CN/EN）+ 用户操作按钮

---

## 4. 左侧导航项

| 图标 | ID | 中文名 | 英文名 |
|------|----|--------|--------|
| 📊 | dashboard | 数据概览 | Dashboard |
| 📺 | channels | 账户管理 | Channels |
| ⬇️ | downloads | 批量下载 | Downloads |
| 🔑 | api-keys | API Keys | API Keys |
| 🌐 | proxy-pools | 代理池 | Proxy Pools |
| 🔄 | dynamic-providers | 动态代理 | Dynamic Providers |
| ✂️ | clip-history | 切片历史 | Clip History |
| ⚙️ | settings | 全局配置 | Settings |

每个导航项对应一个独立页面内容，通过 SPA 路由切换。

---

## 5. 国际化方案

### 语言文件

```json
// static/i18n/zh.json
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
    "noData": "暂无数据"
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

### 切换机制

- 顶部栏右侧语言按钮：`CN` ↔ `EN`
- 切换后：`localStorage.lang = 'zh' | 'en'`
- JS 获取：直接取 `localStorage.lang || 'zh'`
- HTML 属性：`<html lang="zh-CN">` 动态更新
- 文本渲染：已有中文文本暂时保留，英文翻译作为增量

### 国际化范围

- 导航项名称
- 页面标题
- 按钮文字
- 输入框 placeholder
- 空状态提示
- Toast 消息

（初期以中文为主，英文作为扩展，不影响现有功能）

---

## 6. 页面内容映射

### Dashboard（数据概览）
- 统计卡片（账户数 / 扫描次数 / 新增视频 / Quota / 最后扫描）
- 扫描事件日志

### Channels（账户管理）
- 搜索栏 + 账户表格
- 顶部操作栏（添加账户 / 启动监控 / 重载任务）

### Downloads（批量下载）
- 批量下载弹窗内容 → 独立页面

### API Keys
- API Keys 管理弹窗内容 → 独立页面

### Proxy Pools
- 固定代理管理弹窗内容 → 独立页面

### Dynamic Providers
- 动态代理提供方管理弹窗内容 → 独立页面

### Clip History
- 切片历史弹窗内容 → 独立页面

### Settings
- 全局配置弹窗内容 → 独立页面

---

## 7. 路由方案

SPA 路由通过 URL hash 实现：

| 路径 | 页面 |
|------|------|
| `#/` 或 `#/dashboard` | Dashboard |
| `#/channels` | Channels |
| `#/downloads` | Downloads |
| `#/api-keys` | API Keys |
| `#/proxy-pools` | Proxy Pools |
| `#/dynamic-providers` | Dynamic Providers |
| `#/clip-history` | Clip History |
| `#/settings` | Settings |

---

## 8. 实现计划

### Phase 1：布局框架
1. 新建 `static/css/layout-new.css` — 侧边栏 + 顶部栏 CSS 变量
2. 修改 `index.html` — 引入新 layout，提取 header 为独立组件
3. 新建 `js/router.js` — SPA hash 路由
4. 实现 Sidebar 组件（折叠/展开，状态持久化）

### Phase 2：内容迁移
1. 将现有 index.html 中的主内容区按功能拆分到独立 section
2. 每个导航项对应一个 `section id="page-xxx"`
3. 通过 hash 路由控制显示/隐藏

### Phase 3：样式换肤
1. 更新 `variables.css` CSS 变量为 Claude 色系
2. 重写 `common.css` / `modal.css` / `form.css` / `table.css` 按钮/卡片/表单/表格样式
3. 统一圆角、边框、深度系统

### Phase 4：国际化
1. 新建 `static/i18n/` 目录
2. 创建 `zh.json` / `en.json`
3. 实现 `I18n` 模块（加载、切换、保存）
4. 顶部栏语言切换按钮

### Phase 5：测试与优化
1. 手动测试所有导航切换
2. 验证响应式布局（768px+）
3. 检查所有弹窗/抽屉是否正常
4. 语言切换后刷新保持

---

## 9. 统一组件规范（Design Tokens + BEM 命名）

### CSS 变量（Design Tokens）

所有组件共享同一套 CSS 变量，通过 `variables.css` 统一管理：

```css
:root {
  /* 颜色 */
  --color-parchment: #f5f4ed;
  --color-ivory: #faf9f5;
  --color-warm-sand: #e8e6dc;
  --color-near-black: #141413;
  --color-dark-surface: #30302e;
  --color-terracotta: #c96442;
  --color-charcoal-warm: #4d4c48;
  --color-olive-gray: #5e5d59;
  --color-stone-gray: #87867f;
  --color-border-cream: #f0eee6;
  --color-focus-blue: #3898ec;
  --color-warm-silver: #b0aea5;
  --color-coral: #d97757;

  /* 圆角 */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-2xl: 32px;

  /* 阴影 */
  --shadow-ring: 0px 0px 0px 1px;
  --shadow-whisper: 0px 4px 24px rgba(0,0,0,0.05);

  /* 过渡 */
  --transition-fast: 150ms ease-out;
  --transition-normal: 250ms ease-out;
  --transition-slow: 350ms ease-out;

  /* 滚动条 */
  --scrollbar-thumb: #d1cfc5;
  --scrollbar-track: #f5f4ed;
}
```

### BEM 组件命名

统一使用 BEM 命名规范，避免类名碎片化：

```css
/* 按钮 */
.btn { background: var(--color-warm-sand); color: var(--color-charcoal-warm); border-radius: var(--radius-md); }
.btn--primary { background: var(--color-terracotta); color: var(--color-ivory); }
.btn--ghost { background: transparent; border: 1px solid var(--color-border-cream); }
.btn--danger { background: #b53333; color: #fff; }
.btn--sm { padding: 4px 12px; font-size: 13px; }

/* 输入框 */
.form-input { background: var(--color-ivory); border: 1px solid var(--color-border-cream); border-radius: var(--radius-lg); }
.form-input:focus { border-color: var(--color-focus-blue); box-shadow: var(--shadow-ring) var(--color-focus-blue); }
.form-input--error { border-color: #b53333; }

/* 卡片 */
.card { background: var(--color-ivory); border: 1px solid var(--color-border-cream); border-radius: var(--radius-md); }
.card__header { padding: 16px 20px; border-bottom: 1px solid var(--color-border-cream); }
.card__title { font-size: 16px; font-weight: 500; }
.card__body { padding: 20px; }

/* 表格 */
.table { width: 100%; border-collapse: collapse; }
.table__row { border-bottom: 1px solid var(--color-border-cream); }
.table__row:hover { background: var(--color-parchment); }
.table__cell { padding: 12px 16px; }
.table__header { text-align: left; font-size: 13px; color: var(--color-olive-gray); }

/* 模态框 */
.modal { background: var(--color-ivory); border-radius: var(--radius-xl); box-shadow: var(--shadow-whisper); }
.modal__header { padding: 20px 24px; border-bottom: 1px solid var(--color-border-cream); }
.modal__body { padding: 24px; }
.modal__footer { padding: 16px 24px; border-top: 1px solid var(--color-border-cream); }

/* 标签 */
.tag { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: var(--radius-sm); font-size: 12px; }
.tag--success { background: #dcfce7; color: #166534; }
.tag--warning { background: #fef3c7; color: #92400e; }
.tag--error { background: #fee2e2; color: #991b1b; }

/* 滚动条 */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 3px; }
::-webkit-scrollbar-track { background: var(--scrollbar-track); }
```

### 动效规范

| 场景 | 时长 | 缓动 |
|------|------|------|
| 按钮 hover | 150ms | ease-out |
| 弹窗出现 | 250ms | ease-out |
| 侧边栏折叠 | 250ms | ease-out |
| Toast 滑入 | 300ms | ease-out |
| 页面切换 | 200ms | ease-out |

---

## 10. 约束与风险

- **向后兼容**：所有现有功能必须保持可用，不能破坏现有 URL 行为
- **渐进增强**：先布局后换肤，逐步迭代
- **CSS 冲突**：新 CSS 变量需覆盖现有变量，避免重复定义
- **国际化范围**：初期仅导航和关键文字，中文内容翻译作为后续工作
