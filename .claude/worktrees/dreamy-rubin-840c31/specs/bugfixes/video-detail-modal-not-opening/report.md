# 账户列表「详情」无反应（视频详情弹层不可见）

## 现象

在账户列表中点击「详情」按钮后，视频详情弹层不出现或看似无反应。

## 根因

`#modalVideoDetail` 仅带有 `modal-overlay` 类名，但未像 `#modalAccount` 一样声明 `position: fixed`、`display: none` / `.show` 时 `display: flex` 等视口级遮罩规则。内层 `#modalVideoDetail > .modal` 将全局 `.modal` 的 `position: fixed` 覆盖为 `position: relative` 且 `height: 100%`，父级遮罩无有效高度与定位，导致整层布局塌陷，弹层不可见。

## 修复

- 在 `monitor_web/static/css/modal.css` 中为 `#modalVideoDetail.modal-overlay` 补齐与账户弹窗一致的毛玻璃遮罩与 `.show` 时 `display: flex`；内层卡片限制在视口高度内并沿用 `border-cream` / `shadow-whisper` 等 Claude 亮色变量。
- 在 `monitor_web/js/modules/ui.js` 的 `closeModal('modalVideoDetail')` 中移除 ESC 监听、去掉内层 `modal--open`，与关闭按钮行为一致。
- 精简 `videoDetail.js`：统一使用 `ui.closeModal`；更新 `modal-video-detail.html` 结构类名（工具栏、分页、kbd 提示）与无障碍属性。

## 验证

- `pytest tests/test_video_detail_modal_css.py`
- 浏览器：账户管理 → 详情 → 弹层出现并可关闭（含 ESC）。
