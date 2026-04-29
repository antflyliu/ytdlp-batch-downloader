# 任务计划：UI 风格一致性审查

## 目标
审查项目前端 UI（按钮、弹框、列表、表单等所有元素）是否遵循统一的设计风格，参考 DESIGN.md（Anthropic 设计系统），使用 /frontend-design 和 /ui-ux-pro-max 进行审查与修复。

## 当前阶段
Phase 5 — 全部完成

## 阶段

### Phase 1: 探索与审查
- [x] 1.1 梳理项目前端文件结构（HTML/CSS/JS）
- [x] 1.2 读取核心 CSS 文件（variables.css, base.css, common.css, components.css, modal.css 等）
- [x] 1.3 对比 DESIGN.md 设计语言与当前实现
- [x] 1.4 识别不一致的 UI 元素
- **Status:** complete

### Phase 2: 问题汇总与修复计划
- [x] 2.1 整理 CSS 变量体系
- [x] 2.2 识别风格不一致的元素类型（按钮、弹框、列表、表单等）
- [x] 2.3 制定统一化方案
- [x] 2.4 生成规范化 CSS 代码补丁（variables.css 重构）
- **Status:** complete

### Phase 3: 实施修复
- [x] 3.1 统一 CSS 变量定义 (variables.css ✅)
- [x] 3.2 统一按钮样式 (common.css ✅)
- [x] 3.3 统一弹框/Modal 样式 (modal.css ✅, theme.css ✅)
- [x] 3.4 统一表单样式 (form.css ✅)
- [x] 3.5 统一表格/列表样式 (table.css ✅)
- [x] 3.6 HTML 模板类名迁移 (modal-dynamic-providers.html ✅, modal-proxy-pools.html ✅, header.html ✅, base.css ✅)
- [x] 3.7 proxyPool.js selector 迁移 (`.pp-ghost-action` → `#ppDemoBtn` ✅)
- [x] 3.8 provider.css rgba(45,212,191) 全量 → indigo 替换 ✅
- **Status:** complete

### Phase 4: 验证
- [x] 4.1 CSS 括号匹配检验 — 全部 6 个文件 ✅
- [x] 4.2 monitor_ui.py 启动无错误 ✅
- [x] 4.3 CSS 变量引用一致性检验 — 所有文件使用新的 --r-* 变量 ✅
- **Status:** complete

### Phase 5: 交付
- [x] 5.1 CSS 文件 DEPRECATED 注释已添加
- [x] 5.2 向用户汇报结果
- **Status:** complete

## 关键问题（已全部解答）
1. ✅ CSS 变量体系：variables.css 定义暗色主题，CSS 变量 4 档圆角，远不够用
2. ✅ 按钮变体：7 套独立系统，严重碎片化
3. ✅ 模态框：4 套实现 (#modalAppConfirm/#modalBatchDownload/#modalDynamicProviderForm/通用 .modal)
4. ✅ 表单：聚焦样式不一致（outline vs box-shadow vs border-color）
5. ✅ 表格 hover：.vd-table 左侧加 2px 边线，其他仅变背景
6. ✅ 亮/暗主题：theme.css 提供亮色变量，但暗色主 UI + 亮色次级 共存

## 已做决策
| 决策 | 理由 |
|------|------|
| 参考 DESIGN.md 设计系统 | Anthropic 官方设计语言，但需适配暗色主题 |
| 前端文件集中在 monitor_web/ | 项目主监控界面 |
| CSS 分文件组织 | variables, base, common, components, modal, form, table, toast, drawer |
| 保持暗色主题 | 不做大的主题切换，稳定现有 UI |
| 统一品牌色为 indigo (#6366f1) | 合并 proxy/dyn 双主题，消除第三套色系 |
| 扩展圆角变量至 8 档 | 参照 Anthropic 8px 基准，消除 12 种硬编码 |
| provider.css 是最大问题源 | 1218 行代码，引入 proxy+dyn 双主题，最难修复 |

## 遇到的问题
| 问题 | 尝试 | 解决 |
|------|------|------|
| DESIGN.md 与项目主题冲突 | 深入分析后发现：Anthropic 设计系统是暖色亮色，项目是暗色 | 决定保持暗色主题，建立项目专属规范，参考 DESIGN.md 的结构和原则而非直接复用 |
| provider.css (1218行) 双主题问题严重 | 分析 proxy(青) 和 dyn(靛蓝) 两套独立配色 | 修复方案：合并到统一 indigo 品牌色系，proxy/dyn 仅通过 opacity 区分 |
| common.css 重复定义 .status-chip | base.css 和 common.css 都定义了 .status-chip | 需在修复阶段清理重复定义 |
