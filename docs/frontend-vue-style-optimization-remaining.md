# Frontend-Vue 样式优化 — 剩余问题文档

> **目标**: 将所有页面风格统一为 Claude Design System 暖色居中卡片布局（参考 `DESIGN.md`）
> **已完成**: Tailwind 暖色调配置、`layout.css` 12 个全局工具类、12 个视图文件主要清理
> **生成日期**: 2026-04-25

---

## 设计系统速查（Claude Design System）

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg` | `#f5f4ed`（羊皮纸底） | 页面背景 |
| `--surface` / `--card-bg` | `#faf9f5`（象牙白卡片） | 卡片背景 |
| `--accent` | `#c96442`（陶土色） | 强调色/链接/主按钮 |
| `--text` | 暖灰 `#2d2a26` | 主文字 |
| `--text-dim` | 暖灰 `#6b6560` | 次级文字（替代 Tailwind `text-gray-500`） |
| `--text-muted` | 更淡暖灰 | 辅助文字（替代 `text-gray-400`） |
| `--border` | `#e8e5dd` | 边框 |
| `--success` / `--error` / `--warn` | 暖调绿/红/黄 | 状态色 |

**核心规则**:
- `text-gray-500` → `text-dim`（全局 class）
- `text-gray-400` → `text-muted`（全局 class）
- `text-red-500` → 使用 `var(--error)` 内联样式
- `text-blue-*` → 使用 `var(--accent)` 内联样式（或特定业务色）
- `bg-red-50/100` / `bg-green-50/100` → `var(--error-dim)` / `var(--success-dim)`
- `mb-4` on NCard → 移除（Naive UI 自带间距）或在父容器统一处理
- Tailwind `flex gap-*` / `mb-*` / `mt-*` → 保留功能性布局（layout.css 不覆盖功能类）
- `dark:*` 变体 → 统一为单暖色主题（此项目不使用 dark mode）

---

## 修复优先级总览

| 阶段 | 文件数 | 问题数 | 预估工作量 | 说明 |
|------|--------|--------|-----------|------|
| **Phase 1** | 7 设置子页 | ~60 | 中 | 重复 scoped 样式 + Tailwind class 替换 |
| **Phase 2** | 9 组件 | ~40 | 中 | 冷色调颜色 + dark: 变体 + 业务色决断 |
| **Phase 3** | 2 视图 | ~15 | 小 | 残留 Tailwind class 清理 |
| **Phase 4** | 全局验证 | — | 小 | 构建 + 视觉检查 |

---

## Phase 1: 设置子页面（7 文件）

所有设置子页面有三类共性问题：

### 问题模式 A: 重复 scoped 样式定义

以下 6 个文件都在 `<style scoped>` 中重复定义了 `.back-link`、`.page-header`、`.page-title`、`.page-desc`，与 `layout.css` 中的全局定义完全重复，应删除。

| 文件 | 重复样式行数 | 行号范围 |
|------|-------------|----------|
| `settings/NotifySettings.vue` | ~30 行 | L135-163 |
| `settings/GlobalSettings.vue` | ~30 行 | L97-125 |
| `settings/AiSettings.vue` | ~30 行 | L171-199 |
| `settings/ApiSettings.vue` | ~30 行 | L208-236 |
| `settings/DynamicProxySettings.vue` | ~30 行 | L190-218 |
| `settings/ProxySnifferSettings.vue` | ~30 行 | L261-302（保留 `.status-dot` 特有样式） |

**修复方式**: 删除 L135-163 等行的重复样式块，仅保留各页面特有的样式。

### 问题模式 B: `back-link mb-4` / `page-header mb-6`

所有设置子页面的 back-link 和 page-header 都有多余的 `mb-4` / `mb-6` class。

| 文件 | 行号 | 当前代码 | 修复为 |
|------|------|---------|--------|
| `NotifySettings.vue` | L4 | `class="back-link mb-4"` | `class="back-link"` |
| `NotifySettings.vue` | L8 | `class="page-header mb-6"` | `class="page-header"` |
| `GlobalSettings.vue` | L4 | `class="back-link mb-4"` | `class="back-link"` |
| `GlobalSettings.vue` | L8 | `class="page-header mb-6"` | `class="page-header"` |
| `AiSettings.vue` | L4 | `class="back-link mb-4"` | `class="back-link"` |
| `AiSettings.vue` | L8 | `class="page-header mb-6"` | `class="page-header"` |
| `ApiSettings.vue` | L4 | `class="back-link mb-4"` | `class="back-link"` |
| `ApiSettings.vue` | L8 | `class="page-header mb-6"` | `class="page-header"` |
| `DynamicProxySettings.vue` | L4 | `class="back-link mb-4"` | `class="back-link"` |
| `DynamicProxySettings.vue` | L8 | `class="page-header mb-6"` | `class="page-header"` |
| `ProxySnifferSettings.vue` | L4 | `class="back-link mb-4"` | `class="back-link"` |
| `ProxySnifferSettings.vue` | L8 | `class="page-header mb-6"` | `class="page-header"` |
| `DownloadSettings.vue` | — | 已完成（`back-link` / `page-header` 已无 mb 后缀） | — |

### 问题模式 C: `text-xs text-gray-500` → `text-xs text-dim`

这些是表单字段下方的提示文字。`layout.css` 已定义全局 `.text-dim` class。

#### ApiSettings.vue（6 处）

| 行号 | 当前代码 |
|------|---------|
| L25 | `class="text-xs text-gray-500 -mt-2 mb-3"` |
| L39 | `class="text-xs text-gray-500 -mt-2 mb-3"` |
| L60 | `class="text-xs text-gray-500 -mt-2 mb-3"` |
| L70 | `class="text-xs text-gray-500 -mt-2 mb-3"` |
| L91 | `class="text-xs text-gray-500 -mt-2 mb-3"` |
| L118 | `class="text-xs text-gray-500 -mt-2 mb-3"` |

**修复**: `text-gray-500` → `text-dim`（全部替换）

#### DynamicProxySettings.vue（5 处 + 2 处 text-red-500）

| 行号 | 当前代码 | 修复 |
|------|---------|------|
| L19 | `class="text-xs text-gray-500 -mt-2 mb-3"` | `text-gray-500` → `text-dim` |
| L26 | `class="text-xs text-gray-500 -mt-2 mb-3"` | `text-gray-500` → `text-dim` |
| L33 | `class="text-xs text-red-500 -mt-2 mb-3"` | `text-red-500` → `text-dim`（警告提示统一用 dim）或保留红色语义用内联 `style="color:var(--error)"` |
| L59 | `class="text-xs text-gray-500 -mt-2 mb-3"` | `text-gray-500` → `text-dim` |
| L66 | `class="text-xs text-red-500 -mt-2 mb-3"` | 同上 L33 |
| L77 | `class="text-xs text-gray-500 -mt-2 mb-3"` | `text-gray-500` → `text-dim` |
| L88 | `class="text-xs text-gray-500 -mt-2 mb-3"` | `text-gray-500` → `text-dim` |
| L95 | `class="text-sm text-gray-600 mb-3"` | → `text-sm text-dim mb-3` |

**关于 `text-red-500` 的处理**: L33 和 L66 是警告性文字（`Warn`），保留红色语义，使用 `<div style="color:var(--error)" class="text-xs -mt-2 mb-3" style="padding-left:200px">`

#### AiSettings.vue（2 处）

| 行号 | 当前代码 | 修复 |
|------|---------|------|
| L57 | `class="text-xs text-gray-500 -mt-2 mb-3"` | `text-gray-500` → `text-dim` |
| L69 | `class="text-xs text-gray-500 -mt-2 mb-3"` | `text-gray-500` → `text-dim` |

#### ProxySnifferSettings.vue（2 处 + 1 处 text-gray-400 + 1 处 mt-2）

| 行号 | 当前代码 | 修复 |
|------|---------|------|
| L26 | `class="text-xs text-gray-500"` | `text-gray-500` → `text-dim` |
| L58 | `class="text-xs text-gray-400 mt-2"` | → `text-xs text-dim mt-2`（`text-gray-400` → `text-dim`） |
| L72 | `class="text-xs text-gray-500 -mt-2 mb-3"` | `text-gray-500` → `text-dim` |

### 问题模式 D: `NCard class="mb-4"` — NCard 间距

NCard 自带 Naive UI 的 margin，不需要 Tailwind `mb-4`。可以使用 Naive UI 的 `NSpace` 包裹或直接移除。

| 文件 | NCard class="mb-4" 数量 |
|------|------------------------|
| `NotifySettings.vue` | 4 个 (L14, L23, L35, L41) |
| `GlobalSettings.vue` | 1 个 (L14) |
| `AiSettings.vue` | 3 个 (L15, L49, L75) |
| `ApiSettings.vue` | 4 个 (L15, L31, L66, L97) |
| `DynamicProxySettings.vue` | 3 个 (L15, L47, L94) |
| `ProxySnifferSettings.vue` | 3 个 (L14, L64, L92) |
| `DownloadSettings.vue` | 3 个 (L14, L33, L45) — 已完成 text-dim 替换，但 NCard mb-4 未处理 |

**修复方式**: 将 `NCard class="mb-4"` 改为 `NCard`，在外层用 `<NSpace vertical size="medium">` 包裹所有 NCard。

### 问题模式 E: `flex gap-*` 功能性布局

这些是功能性布局 class，layout.css 不覆盖，保留。但审查是否符合设计间距：

| 文件 | 行号 | 当前代码 | 建议 |
|------|------|---------|------|
| `NotifySettings.vue` | L56 | `<div class="flex gap-3">` | 保留（按钮组间距合理） |
| `ProxySnifferSettings.vue` | L15 | `<div class="flex items-center gap-6">` | 保留 |
| `ProxySnifferSettings.vue` | L17 | `<div class="flex items-center gap-3">` | 保留 |
| `ProxySnifferSettings.vue` | L33 | `<div class="flex gap-3 items-center ml-auto">` | 保留 |
| `ProxySnifferSettings.vue` | L77 | `<div class="flex flex-col gap-2">` | 保留 |

### 问题模式 F: ProxySnifferSettings 额外问题

| 行号 | 问题 | 修复 |
|------|------|------|
| L77 | `class="flex flex-col gap-2"` 嵌套在 NCard 中 | 保留（布局功能） |
| L58 | `<div v-if="!configForm.proxy_sniffer_enabled" class="text-xs text-gray-400 mt-2">` | `text-gray-400` → `text-dim` |

---

## Phase 2: 组件文件（9 文件）

### 2.1 Action.vue — 冷色调图标按钮（严重）

**路径**: `src/components/Action.vue`
**问题**: 使用大量属于旧 Wails 应用的冷色调（emerald/sky/blue/orange），包含 `dark:` 变体。

| 行号 | 动作 | 当前颜色 class | 修复后 |
|------|------|---------------|--------|
| L5 | 下载 | `text-emerald-600 dark:text-emerald-400 bg-emerald-500/20 dark:bg-emerald-500/30` | 使用 CSS 变量或 Scoped 样式 |
| L13 | 删除 | `text-red-500 dark:text-red-300 bg-red-500/20 dark:bg-red-500/30` | 保留红色语义，去掉 dark: |
| L21 | 更多操作 | `text-sky-500 dark:text-sky-300 bg-sky-500/20 dark:bg-sky-200/30` | 使用 `var(--accent)` 暖调 |
| L29 | 取消 | `text-red-500 dark:text-red-300 bg-red-500/20 dark:bg-red-500/30` | 保留红色语义 |
| L39 | 复制链接 | `text-blue-300 dark:text-blue-300 bg-blue-300/20 dark:bg-blue-500/30` | 使用 `var(--accent)` 暖调 |
| L49 | 打开链接 | `text-blue-500 dark:text-blue-200 bg-blue-400/20 dark:bg-blue-400/30` | 使用 `var(--accent)` 暖调 |
| L59 | 解码 | `text-orange-400 dark:text-red-300 bg-orange-500/20 dark:bg-orange-200/30` | 保留暖橙色或使用 `var(--accent)` |
| L69 | JSON | `text-sky-400 dark:text-sky-200 bg-sky-500/20 dark:bg-sky-500/30` | 使用 `var(--accent)` 暖调 |

**建议修复策略**: 为此组件创建 scoped 样式，定义每种操作的暖色调 color 变量：

```css
/* Action.vue scoped */
.action-icon--download { color: var(--accent); background: rgba(201,100,66,0.15); }
.action-icon--delete { color: var(--error); background: rgba(220,80,60,0.15); }
.action-icon--cancel { color: var(--error); background: rgba(220,80,60,0.15); }
.action-icon--link { color: var(--accent); background: rgba(201,100,66,0.1); }
.action-icon--open { color: var(--accent); background: rgba(201,100,66,0.1); }
.action-icon--decode { color: #c98042; background: rgba(201,128,66,0.15); }
.action-icon--json { color: var(--accent); background: rgba(201,100,66,0.1); }
```

### 2.2 ActionDesc.vue — 同 Action.vue 的冷色调

**路径**: `src/components/ActionDesc.vue`
**问题**: 与 `Action.vue` 完全相同的颜色方案，还有 `text-gray-500`。

| 行号 | 当前代码 | 修复 |
|------|---------|------|
| L8 | `class="ml-1 text-gray-500"` | → `text-dim` |
| L15 | `text-emerald-600 dark:text-emerald-400 bg-emerald-500/20...` | 同 Action.vue 修复方案 |
| L23 | `text-red-500 dark:text-red-300 bg-red-500/20...` | 保留红色，去掉 dark: |
| L32 | `text-blue-600 dark:text-blue-300 bg-blue-500/20...` | 用 `var(--accent)` |
| L42 | `text-blue-500 dark:text-blue-200 bg-blue-400/20...` | 用 `var(--accent)` |
| L52 | `text-orange-400 dark:text-red-300 bg-orange-500/20...` | 用暖橙色 |
| L62 | `text-sky-400 dark:text-sky-200 bg-sky-500/20...` | 用 `var(--accent)` |
| L72 | `text-red-500 dark:text-red-300 bg-red-500/20...` | 保留红色，去掉 dark: |
| L82 | `text-sky-500 dark:text-sky-300 bg-sky-500/20...` | 用 `var(--accent)` |

**建议**: 与 Action.vue 共享颜色定义，可抽取公共 CSS 变量或复用 scoped class。

### 2.3 ClipDetailModal.vue — 冷色调文字

**路径**: `src/components/ClipDetailModal.vue`

| 行号 | 当前代码 | 修复 |
|------|---------|------|
| L12 | `class="text-sm text-gray-500 mt-2"` | → `text-sm text-dim mt-2` |
| L31 | `class="text-sm text-gray-400"` | → `text-sm text-dim` |
| L44 | `class="clip-duration text-sm text-gray-500 ml-3"` | → `text-sm text-dim ml-3` |
| L62 | `class="text-sm text-gray-400"` | → `text-sm text-dim` |
| L76 | `class="text-red-500"` | → 内联 `style="color:var(--error)"` |

### 2.4 Password.vue — 红色提示 + mt-3 间距

**路径**: `src/components/Password.vue`

| 行号 | 当前代码 | 修复 |
|------|---------|------|
| L15 | `class="text-red-500 text-base"` | → 内联 `style="color:var(--error);font-size:16px"` |
| L18 | `class="mt-3"` | 保留（功能性间距） |
| L26 | `class="mt-3 text-base"` | 保留 mt-3，移除 text-base 或保留 |

### 2.5 ShowLoading.vue — 白色旋转器

**路径**: `src/components/ShowLoading.vue`

| 行号 | 当前代码 | 问题 |
|------|---------|------|
| L2 | `class="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50 z-50"` | 功能性覆盖层，保留 |
| L4 | `class="animate-spin h-10 w-10 text-white mb-4"` | `text-white` → 可改为暖色，或保留（loading overlay 通常用白色） |
| L9 | `class="text-white"` | 同上 |

**建议**: Loading overlay 使用白色是合理的设计选择，保留。可考虑将 `bg-black bg-opacity-50` 改为暖灰半透明：`style="background:rgba(45,42,38,0.5)"`

### 2.6 Footer.vue — 冷色调文字 + Tailwind 布局

**路径**: `src/components/Footer.vue`

| 行号 | 当前代码 | 修复 |
|------|---------|------|
| L16 | `class="text-xs pl-5 text-slate-400"` | → `class="text-xs pl-5" style="color:var(--text-dim)"` |
| L20 | `class="text-slate-400 w-80 pt-2 pb-4"` | → 内联 `style="color:var(--text-dim)" class="w-80 pt-2 pb-4"` |
| L30 | `class="text-2xl font-bold text-emerald-600"` | → 使用 `var(--accent)` 或保留绿色（"支持"标题） |
| L33 | `class="grid grid-cols-5 gap-2 text-sm m-4 text-slate-400"` | → `text-slate-400` 改为 `text-dim` |
| L37 | `class="flex w-full text-sm justify-between pt-8 text-slate-400"` | → `text-slate-400` 改为 `text-dim` |

**说明**: `text-slate-400` 是 Tailwind 的冷灰色，需改为暖色 `text-dim`（即 `var(--text-dim)`）。

### 2.7 Screen.vue — macOS 窗口按钮（保留原色）

**路径**: `src/components/Screen.vue`

| 行号 | 内容 | 处理 |
|------|------|------|
| L4 | `bg-[#ff5c57]` 红色关闭按钮 | **保留**，这是 macOS 窗口控件模拟 |
| L13 | `bg-[#ffbc38]` 黄色最小化按钮 | **保留** |
| L22 | `bg-[#28c840]` 绿色全屏按钮 | **保留** |

**建议**: 无修改，这是 UI 模拟不需要改为暖色。

### 2.8 ResourceAction.vue — 简单 flex gap

**路径**: `src/components/ResourceAction.vue`

| 行号 | 当前代码 | 处理 |
|------|---------|------|
| L2 | `class="flex gap-2"` | 保留（功能性布局） |

**建议**: 无修改。

### 2.9 ImportJson.vue — flex gap justify-end

**路径**: `src/components/ImportJson.vue`

| 行号 | 当前代码 | 处理 |
|------|---------|------|
| L18 | `class="flex gap-2 justify-end"` | 保留（功能性布局） |

**建议**: 无修改。

---

## Phase 3: 残留视图修复

### 3.1 Settings.vue

**路径**: `src/views/Settings.vue`

需要读取确认是否还有 Tailwind class。

### 3.2 DynamicProviders.vue（少量残留）

| 行号 | 当前代码 | 修复 |
|------|---------|------|
| L53 | `<NSpace vertical size="medium" class="mb-4">` | 移除 `class="mb-4"` |

其余 `text-dim` 替换已完成。

### 3.3 Accounts.vue（1 处残留）

| 行号 | 当前代码 | 修复 |
|------|---------|------|
| L157 | `<div class="platform-selector mb-3">` | 保留（功能 class，layout.css 不处理） |

---

## Phase 4: 全局验证清单

完成所有修复后执行：

- [ ] `npx vite build` — 构建成功无错误
- [ ] `npx vue-tsc --noEmit` — TypeScript 无新增错误
- [ ] 视觉走查每页：
  - [ ] 设置 Hub → 各设置子页（回退链接颜色、页面标题、表单布局）
  - [ ] 账号管理（表格、空状态、搜索、模态框）
  - [ ] 批量下载（筛选 chip、状态 pill、表格行）
  - [ ] 资源嗅探（表格、操作按钮、预览）
  - [ ] 动态代理（状态面板、抽屉、表格）
  - [ ] API Keys（卡片列表、表单、骨架屏）
  - [ ] 代理池（表格、状态点、模态框）
  - [ ] 剪辑历史（表格、详情弹框）
  - [ ] 占位页（空状态）

---

## 修复顺序建议

按文件依赖和影响范围排序：

```
1.  settings/NotifySettings.vue       (~10 处)
2.  settings/GlobalSettings.vue       (~4 处)
3.  settings/AiSettings.vue           (~7 处)
4.  settings/ApiSettings.vue          (~10 处)
5.  settings/DynamicProxySettings.vue (~12 处)
6.  settings/ProxySnifferSettings.vue (~10 处)
7.  settings/DownloadSettings.vue     (~3 处 NCard mb-4)
--- Phase 1 完成 ---
8.  components/ClipDetailModal.vue    (~5 处)
9.  components/Password.vue           (~2 处)
10. components/ShowLoading.vue        (~2 处，可选)
11. components/Footer.vue             (~5 处)
12. components/Action.vue             (~8 处颜色方案重定义)
13. components/ActionDesc.vue         (~9 处颜色方案重定义)
--- Phase 2 完成 ---
14. views/DynamicProviders.vue        (~1 处)
--- Phase 3 完成 ---
15. 全局验证
```

---

## 批量查找替换速查表

### replace_all 操作

以下替换可以安全地在全项目执行（已在 layout.css 中有对应 class）：

```
text-gray-500 → text-dim          （27 处，主要在 settings/*.vue 和 components/*.vue）
text-gray-400 → text-dim          （5 处，主要在 ProxySnifferSettings.vue 和 ClipDetailModal.vue）
text-slate-400 → text-dim         （4 处，Footer.vue）
text-gray-600 → text-dim          （1 处，DynamicProxySettings.vue L95）
```

以下替换需要**逐文件人工判断**（保留语义色）：

```
text-red-500 → style="color:var(--error)"    （7 处）
text-blue-*  → 根据业务含义决定               （6 处）
text-sky-*   → 根据业务含义决定               （6 处）
text-emerald-* → 根据业务含义决定             （2 处）
text-orange-* → 根据业务含义决定              （3 处）
```

### dark: 变体清理

仅在两个文件中存在 `dark:` 变体：
- `Action.vue` — 所有 color/bg class 都带 `dark:`
- `ActionDesc.vue` — 所有 color/bg class 都带 `dark:`

**处理**: 移除所有 `dark:*` 变体，统一为单暖色主题样式。

---

## 注意事项

1. **NCard mb-4 移除后**: 设置页面需要在外层包裹 `<NSpace vertical size="medium">` 来保持卡片间距，或依赖 Naive UI 默认间距
2. **Action.vue / ActionDesc.vue 颜色方案**: 这两个组件定义的是操作图标按钮的颜色系统，修改需要保证"下载/删除/复制/打开/解码/JSON"6种操作仍有足够的视觉区分度
3. **不可修改的文件**: `Screen.vue`（macOS 窗口按钮模拟）、`ResourceAction.vue`（仅有 flex gap）、`ImportJson.vue`（仅有 flex gap）
4. **Footer.vue 的 `text-emerald-600`**: 是"支持"标题的颜色，可改为 `var(--accent)` 或保留绿色
