# 列表「详情」无反应（三处）

## 现象

在「账户管理」「动态代理」「切片历史」列表中点击「详情」后无可见反馈或弹层不出现。

## 根因

1. **动态代理 — 提供方运行详情抽屉**  
   `openDynamicProviderDetail` 仅对根节点设置 `display` / `.show`，未调用 `openModal`。内层元素带有全局样式 `.modal`：默认 `opacity: 0`、`pointer-events: none`，需配合 `modal--open` 才可见可点。缺少 `modal--open` 时整层不可见，表现为「点了没反应」。

2. **账户管理 — 视频详情**、**切片历史 — 任务详情**  
   外层 `#modalVideoDetail`、`#modalClipDetail` 缺少与账户表单弹层一致的视口级规则：`position: fixed`、`display: none` / `.show` 时 `display: flex`。内层将 `.modal` 或内容区改为非全屏布局后，遮罩层未占满视口，弹层塌陷或不可见（与既有 `tests/test_video_detail_modal_css.py` 预期一致）。

3. **点击遮罩关闭**  
   文档级点击仅移除外层 `.show`，未同步移除内层 `.modal` 的 `modal--open`，与 `closeModal` 行为不一致（顺带修复）。

## 修复

- `monitor_web/static/css/modal.css`：为 `#modalVideoDetail.modal-overlay`、`#modalClipDetail.modal-overlay`、`#dynProviderDetailDrawer.modal-overlay` 补齐视口级遮罩与 `.show` 展示规则。
- `monitor_web/js/modules/dynamicProvider.js`：`openDynamicProviderDetail` 在 DOM 校验通过后调用 `openModal('dynProviderDetailDrawer')`；`closeDynamicProviderDetail` 改为 `closeModal('dynProviderDetailDrawer')`；缺失节点时 `toast` 提示。
- `monitor_web/templates/modals/dyn-provider-detail-drawer.html`：去掉依赖内联 `display:none` 的写法，改由 CSS 控制。
- `monitor_web/js/modules/ui.js`：遮罩点击关闭时同步移除内层 `modal--open`。
- `monitor_web/js/modules/clipHistory.js`：`chViewTask` 在弹层未挂载时提示（与视频详情一致）。

## 验证

- `pytest tests/test_video_detail_modal_css.py`
- 浏览器：三页分别点「详情」— 弹层/抽屉出现并可关闭；其它弹层与列表操作无回归。
