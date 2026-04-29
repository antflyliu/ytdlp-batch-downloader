# Monitor Web：UI/UX Pro Max 风格统一（实施计划）

> 与 `2026-04-18-monitor-web-redesign-plan.md` 并行：该文档侧重布局与 Claude Design Tokens；本文侧重 **ui-ux-pro-max** 方法论下的交互、无障碍与视觉一致性。

**日期说明：** 文档标题日期与仓库当日开发迭代对齐；具体排期以任务跟踪为准。

---

## 目标

- 在**不推翻**现有 `variables.css` / 侧栏布局的前提下，把列表页、表格操作区、弹层/抽屉的观感统一到「专业后台」水准。
- 满足 **Accessibility / Touch / Performance / Layout** 等优先级规则（见技能 `ui-ux-pro-max`）。

---

## 步骤 1：生成设计系统基线（必做）

在已安装 Python 的环境中，于 **ui-ux-pro-max** 技能目录执行（路径以本机 `skills/ui-ux-pro-max` 为准）：

```bash
python3 skills/ui-ux-pro-max/scripts/search.py "SaaS admin dashboard YouTube monitoring professional warm light" --design-system -p "Monitor Web" -f markdown
```

将输出中的 **pattern / style / color / typography / anti-patterns** 摘录到项目内 `design-system/MASTER.md`（若采用 `--persist` 则由脚本生成），作为后续改样式的「单一事实来源」。

**补充检索（按需）：**

- `ux` 域：`animation accessibility z-index loading`
- `typography` 域：`dashboard data dense`
- Stack：当前为纯 HTML/CSS/JS，使用 `--stack html-tailwind` **仅作原则参考**（本项目无 Tailwind，需手工映射到 CSS 变量）。

---

## 步骤 2：与现有 Tokens 对齐（映射表）

| Pro Max 关注点 | 本项目落点 |
|----------------|------------|
| 主文字对比度 ≥ 4.5:1 | `--text` / `--text-muted` 已在 `variables.css`，改表头/次要信息时校验对比度 |
| 可点击区域 ≥ 44×44px | `.btn-sm`、表格内操作按钮：最小高度与 padding |
| `cursor-pointer` | 所有 `button`、`[role="button"]`、可点行 |
| 焦点环 | `:focus-visible` 与现有 `--accent` 协调 |
| z-index | 沿用 `modal.css` 中 `--z-modal` / `--z-toast` 层级，避免魔法数 |

---

## 步骤 3：分阶段改 UI（降低回归风险）

1. **表格操作列**（账户 / 动态代理 / 切片历史）：统一 `.actions` 内按钮尺寸、间距、hover/active；与 `table.css` 中已有规则一致扩展。
2. **弹层与抽屉**：`modal.css` + `clip-detail.css` 已区分场景；新改动以「遮罩 + 内容卡片」两层结构为准，避免再出现仅改内层、外层无 `fixed` 的布局问题。
3. **加载与空状态**：异步操作按钮 `disabled` + 文案（技能 loading-buttons）。

---

## 验收标准（可测）

- 三处列表「详情」及主要操作在小屏下可点、不重叠；键盘 Tab 可聚焦到关闭按钮与主操作。
- 无新增横向滚动条（常见 375 / 768 / 1440 宽度）。
- 与本次 bugfix 相关的回归：`pytest tests/test_video_detail_modal_css.py` 通过。

---

## 与本次 Bug 修复的关系

本次「详情无反应」根因是 **JS 未走 `openModal` + 遮罩 CSS 未视口化**；风格统一计划**不重复**修复逻辑，但要求在后续改样式时**保留** `#modalVideoDetail.modal-overlay`、`#modalClipDetail.modal-overlay`、`#dynProviderDetailDrawer.modal-overlay` 的 `position: fixed` + `.show` 展示约定。
