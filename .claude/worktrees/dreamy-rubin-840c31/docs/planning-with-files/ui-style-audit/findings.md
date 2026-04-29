# 发现与决策

## 需求理解
- 审查项目前端 UI 页面风格一致性
- 参考 DESIGN.md (Anthropic 设计系统)
- 使用 /frontend-design 和 /ui-ux-pro-max 进行 UI 设计
- 覆盖范围：按钮、弹框、列表、表单等所有页面元素

## 研究发现

### 项目前端结构
- 主监控界面：`monitor_web/index.html`
- CSS 文件：`monitor_web/static/css/` 下分文件组织
  - `variables.css` — CSS 变量定义
  - `base.css` — 基础样式重置
  - `common.css` — 通用组件样式
  - `components.css` — 通用组件（按钮、标签、徽章等）
  - `modal.css` — 弹框样式
  - `form.css` — 表单样式
  - `table.css` — 表格样式
  - `toast.css` — 通知样式
  - `drawer.css` — 侧边抽屉样式
  - `layout.css` — 布局样式
  - `api-key.css` — API Key 管理页面样式
  - `batch.css` — 批量下载样式
  - `provider.css` — Provider 样式
  - `theme.css` — 主题相关样式

### CSS 文件全览（13个文件）

| 文件 | 行数 | 核心内容 | 关键问题 |
|------|------|----------|----------|
| variables.css | ~200行 | CSS 变量定义（暗色主题） | 仅4档圆角变量，严重不足 |
| base.css | ~176行 | reset + layout + card | 与 common.css 功能重叠 |
| common.css | ~182行 | 按钮/标签/状态/表格基础 | 存在大量 .status-chip 重复定义 |
| modal.css | ~80行 | 通用 .modal 系统 | 与 #modalAppConfirm/#modalBatchDownload 分离 |
| form.css | ~200行 | 表单/checkbox/toggle | 聚焦样式不统一 |
| table.css | ~50行 | vd-table/ak-card/ak-ring | ak-ring 与其他卡片脱节 |
| toast.css | ~35行 | 通知系统 | 简洁，与其他组件脱节 |
| drawer.css | ~80行 | settings-section (proxy主题) | proxy 专属配色，与主色冲突 |
| layout.css | ~175行 | 布局/header/footer/card | 与 base.css 职责边界模糊 |
| api-key.css | ~287行 | API Key 卡片/表单/空状态 | 钉钉表单独立样式 |
| batch.css | ~300行 | 批量下载 bd-* 组件 | 独立按钮系统 bd-btn |
| provider.css | ~1218行 | proxy+dyn 双主题组件 | 最严重的问题源：1218行 |
| theme.css | 少量 | 亮色主题覆盖变量 | 与暗色主题并存 |

### DESIGN.md 设计系统关键要求
- **主题**：暖色羊皮纸 (#f5f4ed) 或深暖色 (#141413)，所有灰色带暖黄褐基调
- **品牌色**：Terracotta (#c96442) — 暖橙褐，非 indigo
- **字体**：Georgia (衬线标题) + system-ui (正文/UI)
- **圆角档位**：8px(舒适)/12px(充裕)/16-32px(特色)，基于 8px 基准
- **深度系统**：ring-shadow `0px 0px 0px 1px` 而非 drop-shadow

### 两套设计语言并存（最严重冲突）

#### 主题一：主 UI（Indigo 系）
```
--accent: #6366f1 (indigo)
--accent-hover: #818cf8
--accent-dim: rgba(99,102,241,0.12)
```

#### 主题二：Proxy（青色系）
```
--proxy-text: #2dd4bf
--proxy-bg: rgba(45,212,191,0.08)
--proxy-border: rgba(45,212,191,0.18)
--proxy-dot-on: #2dd4bf
--proxy-tint: rgba(45,212,191,0.10)
```

#### 主题三：Dyn Provider（靛蓝系）
```
--dyn-text: #818cf8
--dyn-bg: rgba(99,102,241,0.08)
--dyn-border: rgba(99,102,241,0.18)
--dyn-dot-on: #818cf8
```

**分析**：三套主题并存于同一视觉空间，proxy 用青色 (#2dd4bf)，dyn 用靛蓝 (#818cf8)，主 UI 用 indigo (#6366f1) — 三者都是蓝紫系但色值不同，造成视觉混乱。

## 问题严重程度评估

### 🔴 严重问题（需立即修复）

**问题1：proxy/dyn 双主题与主 UI 冲突**
- 严重度：HIGH
- 影响：同一页面出现三套强调色，视觉不统一
- 根因：provider.css 独立引入了青色 (#2dd4bf) 和靛蓝 (#818cf8) 主题
- 修复：统一为一套 --accent 色系，proxy/dyn 仅通过 opacity 变化区分

**问题2：按钮类名碎片化（7套独立按钮系统）**
- 严重度：HIGH
- 影响：维护困难，hover/active 行为不一致
- 根因：历史累积，各功能模块独立定义
- 修复：统一为一套 BEM 规范的按钮系统

**问题3：圆角值散落 12 种硬编码**
- 严重度：MEDIUM-HIGH
- 影响：同一组件在不同文件中 border-radius 不一致
- 根因：variables.css 仅定义 4 档（4/6/10/16px），远不够用
- 修复：扩展圆角变量档位至 8 档，迁移所有硬编码值

### 🟡 中等问题（计划修复）

**问题4：模态框多套实现**
- 严重度：MEDIUM
- #modalAppConfirm / #modalBatchDownload / #modalDynamicProviderForm 各有独立样式
- 修复：统一到通用 .modal 系统，通过 modifier class 区分

**问题5：表单聚焦样式不一致**
- 严重度：MEDIUM
- 部分用 `outline`，部分用 `box-shadow`，部分用 `border-color`
- 修复：统一为 `box-shadow` + `border-color` 组合

**问题6：硬编码 rgba 值泛滥**
- 严重度：MEDIUM
- provider.css 中大量 `rgba(42,53,73,0.8)`、`rgba(255,255,255,0.06)` 等硬编码
- 修复：提取为 CSS 变量

### 🟢 轻微问题（建议修复）

**问题7：卡片/空状态样式参差**
- .card (layout.css) vs .ak-card vs .proxy-empty vs .dyn-empty
- 修复：建立标准 card 组件，empty 状态基于此扩展

**问题8：表格 hover 行为不一致**
- .vd-table 左侧加 2px 边线，其他仅背景变化
- 修复：统一 hover 行为模式

## 修复方案（保持暗色主题，规范化设计系统）

### 方案核心原则
1. **保持暗色主题**：不做大的主题切换
2. **单一品牌色**：以现有 indigo (#6366f1) 为基准
3. **扩展圆角变量**：参照 Anthropic 8px 基准体系
4. **消除硬编码**：所有颜色值迁移到 CSS 变量

### 关键 CSS 变量重定义建议

```css
/* 圆角变量扩展（8档） */
:root {
  --r-xs: 3px;    /* 微小元素 */
  --r-sm: 6px;    /* 小按钮/输入框 */
  --r-md: 8px;    /* 标准按钮/卡片 */
  --r-lg: 12px;    /* 大按钮/模态框 */
  --r-xl: 16px;   /* 特色卡片 */
  --r-2xl: 20px;  /* 大容器 */
  --r-full: 9999px; /* 胶囊/圆点 */
}

/* 品牌色统一 */
:root {
  --brand: #6366f1;
  --brand-hover: #818cf8;
  --brand-dim: rgba(99,102,241,0.12);
  --brand-ring: rgba(99,102,241,0.30);
}

/* 合并 proxy/dyn 到统一语义 */
:root {
  /* proxy 和 dyn 组件不再有独立主题色 */
  /* 仅通过 surface-bg/surface-border 变化来区分不同区域 */
  --region-proxy-bg: rgba(99,102,241,0.04);
  --region-proxy-border: rgba(99,102,241,0.15);
}

/* 消除硬编码色 */
:root {
  --surface-raised: rgba(255,255,255,0.04);
  --border-subtle: rgba(255,255,255,0.06);
  --border-medium: rgba(255,255,255,0.10);
  --border-strong: rgba(255,255,255,0.15);
}
```

### 统一按钮系统

```css
/* 基础按钮 */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: var(--r-md);
  font-size: 13px; font-weight: 500; cursor: pointer;
  border: 1px solid transparent; transition: all 0.15s;
}
.btn-primary { background: var(--brand); color: #fff; }
.btn-primary:hover { background: var(--brand-hover); }
.btn-ghost {
  background: transparent; color: var(--text-muted);
  border-color: var(--border-medium);
}
.btn-ghost:hover { background: var(--surface2); color: var(--text); }
.btn-sm { padding: 5px 10px; font-size: 11px; border-radius: var(--r-sm); }
.btn-icon { width: 36px; height: 36px; padding: 0; border-radius: var(--r-sm); }

/* 废弃的按钮系统（统一迁移） */
/* .bd-btn-*  → 统一使用 .btn / .btn-sm / .btn-ghost */
/* .btn-ghost-proxy  → 统一使用 .btn-ghost */
/* .dyn-ghost-btn  → 统一使用 .btn-ghost */
/* .btn-dyn-primary  → 统一使用 .btn-primary */
/* .pp-ghost-action  → 统一使用 .btn-ghost */
```

### 统一模态框

```css
/* 所有模态框共用通用结构 */
.modal-overlay { z-index: 1000; /* 层级可通过 CSS 变量覆盖 */ }
.modal {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r-lg); box-shadow: var(--shadow);
}
.modal-header { padding: 16px 20px; border-bottom: 1px solid var(--border); }
.modal-body { padding: 20px; }
.modal-footer { padding: 16px 20px; border-top: 1px solid var(--border); display: flex; gap: 8px; justify-content: flex-end; }

/* 特殊模态框通过 modifier class */
.modal--danger { border-left: 3px solid var(--error); }
.modal--warning { border-left: 3px solid var(--warning); }
.modal--large { max-width: 800px; }
```

## 资源
| 决策 | 理由 |
|------|------|
| 参考 DESIGN.md | Anthropic 官方设计系统 |

## 遇到的问题
| 问题 | 解决 |
|------|------|
| — | — |

## 资源
- 项目前端：`monitor_web/`
- 设计参考：`DESIGN.md`
- CSS 目录：`monitor_web/static/css/`
