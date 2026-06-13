# Bugfix Report: RSS 内容源「订阅源库」新增自定义源模块 i18n key 缺失

**Date:** 2026-06-13
**Status:** Fixed
**Bug name:** rss-catalog-source-i18n-missing
**Severity:** P1（用户可见、文案直接显示为 i18n 路径而非翻译）

## 问题描述

在 RSS 内容源主页「订阅源库」模块中，UI 上一批新增的「自定义源」相关文案（按钮、Modal 标题、字段标签、toast 提示等）直接以 i18n key 路径字符串渲染，例如 `rssPipeline.catalogSources`、`rssPipeline.catalogAddSource`、`rssPipeline.catalogSourceName` 等。中文与英文模式下都出现该问题。

**复现步骤：**

1. 启动前端 dev server，访问 `Rss Sources` 页面。
2. 查看「订阅源库」卡片：
   - 卡片右上角出现字面量 `rssPipeline.catalogSources`（应为「自定义源」/「Custom Sources」）。
   - 子区块标题、右侧「添加源」按钮文字均为字面量 `rssPipeline.catalogSources` / `rssPipeline.catalogAddSource`。
3. 点击「rssPipeline.catalogAddSource」按钮（实际是「添加源」），在弹出 Modal 中：
   - Modal 标题、各 `NFormItem` 标签均为 `rssPipeline.catalogSourceName` / `rssPipeline.catalogSourceFeedsUrl` / `rssPipeline.catalogSourceHomepageUrl` / `rssPipeline.catalogSourceStatusUrl` 字面量。
   - 弹窗底部提交按钮文字为 `rssPipeline.catalogAddSource`。
4. 列表为空时显示 `rssPipeline.catalogSourceEmpty`；点击删除按钮时确认气泡显示 `rssPipeline.catalogSourceDeleteConfirm`。
5. 触发添加/删除成功或失败时，对应 `message.success / message.error` 弹出 `rssPipeline.catalogSourceAdded` / `rssPipeline.catalogSourceAddFailed` / `rssPipeline.catalogSourceDeleteFailed` / `rssPipeline.catalogSourceDeleteFailed` / `rssPipeline.catalogSourceAddError` 字面量。

**影响范围：**

- 同一「自定义源」子功能涉及的 13 个 i18n key 在 `zh.json` / `en.json` 双侧均缺失，覆盖了 4 个 UI 区域：卡片 header-extra 按钮、子区块标题/空态、Modal 表单字段与提交按钮、toast 提示与删除确认气泡。
- 由于两侧都缺，vue-i18n 的 `fallbackLocale` 不会回退到任一语言，最终直接以 key 字符串回显到 DOM。

## 调查摘要

- **症状检查：** 在 `RssPipeline.vue` 中收集所有 `rssPipeline.catalog*` 引用（34 个），与 `zh.json` / `en.json` 中 `rssPipeline` 节点的实际 key 集合求差集，得到 13 个 key 在两侧同时缺失。
- **代码检查：**
  - `frontend-vue/src/views/RssPipeline.vue`（git status M，本次新增了「自定义源」卡片 + Modal，但 i18n 字符串未同步进语言包）。
  - `frontend-vue/src/locales/zh.json`、`frontend-vue/src/locales/en.json`（`rssPipeline` 节点最新到 `articleTaskFailed`，未追加 `catalogAddSource` / `catalogSources` / `catalogSource*`）。
  - `frontend-vue/src/i18n.ts`（`createI18n` 未配置 `missing` 处理器，`fallbackLocale: 'en'` 只在「zh 缺、en 有」时回退，两侧都缺则命中 vue-i18n 9.x 的默认「直接回显 key 字符串」行为）。
  - `frontend-vue/package.json` 中 `vue-i18n: 9.10.0`。
- **假设验证：** 问题不是网络/数据加载问题，不是组件渲染问题，是纯字符串表缺漏。回显的字符串与 `t('rssPipeline.xxx')` 的入参完全一致，证明 `t()` 直接返回了原始 key。

## 根本原因

`RssPipeline.vue` 在「订阅源库」卡片里新增了「自定义源」子模块（行 102-265），这些 UI 元素全部通过 `t('rssPipeline.catalog*')` 取文案，但对应的 key 没有写进 `frontend-vue/src/locales/zh.json` 和 `frontend-vue/src/locales/en.json` 的 `rssPipeline` 节点。

vue-i18n 9.x 在 key 缺失时默认行为是**直接以 key 字符串返回**，且本项目 i18n 配置 `fallbackLocale: 'en'` 只会处理「zh 缺、en 有」这一种情况，**两侧都缺时不会回退**。所以中英文用户都看到 `rssPipeline.xxx` 字面量。

### 缺陷类型

i18n 字符串表配置缺陷（新增 UI 元素时未同步补全翻译条目）。

### 缺陷如何产生

本次工作区对 `RssPipeline.vue` 做了非原子性修改：UI 部分（`catalogSources` 卡片、`rssCatalogSource*` Modal、新事件处理函数）已经写好，但 `zh.json` / `en.json` 的 `rssPipeline` 节点只在 `git diff` 中表现为「BOM 调整 + 全文件格式化」，实际没有同步追加新增 key。同批新增的 `catalogSourceAddError`、`catalogSourceAddFailed`、`catalogSourceAdded` 等 5 个 toast key、4 个 Modal 字段 key、3 个按钮/标题/确认气泡 key、1 个空态 key（合计 13 个）全部漏补。

### 促成因素

- `i18n.ts` 没有自定义 `missing` 处理器，缺 key 不会在开发期报警，安静地回显字符串。
- 项目内暂无「模板内引用的 i18n key 必须在双侧 locale 中存在」的自动化校验。
- `zh.json` / `en.json` 此前经历过一次「整文件行尾/空白整理」式的 diff（参看 `git diff frontend-vue/src/locales/zh.json` 顶部 `+-    "refresh": "刷新"` 这种纯空白变更），掩盖了真正的 key 缺漏，使 PR 评审难以发现。

## 解决方案

仅做最小修复：在 `frontend-vue/src/locales/zh.json` 与 `frontend-vue/src/locales/en.json` 的 `rssPipeline` 节点末尾追加缺失的 13 条翻译，保持现有字母序（按 key 字符串升序插入，文件其余部分不动）。不修改 `RssPipeline.vue`、不调整 `i18n.ts`、不引入新依赖。

### 新增 key（中 / 英）

| key | zh | en |
|---|---|---|
| `catalogAddSource` | 添加源 | Add Source |
| `catalogSourceAddError` | 请填写名称和 feeds URL | Please fill in name and feeds URL |
| `catalogSourceAddFailed` | 源添加失败 | Failed to add source |
| `catalogSourceAdded` | 源已添加 | Source added |
| `catalogSourceDeleteConfirm` | 删除该自定义源及其条目？ | Delete this custom source and its entries? |
| `catalogSourceDeleteFailed` | 源删除失败 | Failed to delete source |
| `catalogSourceDeleted` | 源已删除 | Source deleted |
| `catalogSourceEmpty` | 尚未添加自定义源 | No custom sources added yet |
| `catalogSourceFeedsUrl` | Feeds URL | Feeds URL |
| `catalogSourceHomepageUrl` | 主页 URL | Homepage URL |
| `catalogSourceName` | 源名称 | Source Name |
| `catalogSourceStatusUrl` | 状态 URL | Status URL |
| `catalogSources` | 自定义源 | Custom Sources |

## 验证

- `python -m json.tool frontend-vue/src/locales/zh.json` / `en.json`：两个文件均通过 JSON 语法校验。
- 引用-定义差集校验：从 `RssPipeline.vue` 抽出 34 个 `rssPipeline.catalog*` 引用，与 `zh.json` / `en.json` 的 `rssPipeline` 节点求差集，结果均为空集；`zh` 与 `en` 两侧的 `rssPipeline` key 集合完全一致。
- 完整性校验：所有新增 value 均为非空字符串。
- 人工核对：UI 上原先显示 `rssPipeline.catalogSources` 的位置现在显示「自定义源」/`Custom Sources`；Modal 字段标签、toast 提示与确认气泡均恢复正常文案。

## 改动文件

- `frontend-vue/src/locales/zh.json` — `rssPipeline` 节点追加 13 条翻译。
- `frontend-vue/src/locales/en.json` — `rssPipeline` 节点追加 13 条翻译。

## 后续建议（不在本次修复范围）

1. 在 `frontend-vue/src/i18n.ts` 的 `createI18n` 配置中加 `missing: (_, key) => console.warn(`[i18n] missing: ${key}`)`，开发期即可感知漏 key；构建模式下可升级为 `console.error` 让 CI 失败。
2. 写一条 vitest 断言，枚举 `RssPipeline.vue`（以及其它 view）模板中所有 `rssPipeline.*` 引用，断言它们在 `zh.json` / `en.json` 双侧均存在，参考 `specs/bugfixes/vue-i18n-invalid-linked-format` 的思路。
3. 考虑将 `zh.json` / `en.json` 在 PR 中以「仅追加」形式 diff（按 key 字母序自动整理），避免出现「整文件行尾/空白变更」掩盖真正的 key 缺漏。
