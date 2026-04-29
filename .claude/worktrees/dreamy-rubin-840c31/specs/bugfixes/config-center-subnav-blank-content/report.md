# 配置中心子菜单主内容区空白

**日期：** 2026-04-18

## 现象

侧栏「配置中心」下点击「通知与 Webhook」「API 与扫描」等子项时，顶栏标题与侧栏高亮正确，但右侧主内容区空白；点击父级「配置中心」进入 `#/settings` 时全局配置页正常显示。

## 根因

Hash 路由已注册 `settings-notify`、`settings-api` 等子路由，并调用 `showPage('settings-notify')` 等。`showPage` 通过 `document.getElementById('page-' + name)` 查找对应区块，例如 `page-settings-notify`。

`index.html` 中仅存在单个 `section#page-settings`，**没有** `page-settings-notify` 等节点。子路由切换时没有任何 `.page` 被加上 `page--active`，主区域无可见内容。

## 修复

1. **`monitor_web/static/js/router.js`**：将 `settings-*`（且非 `settings` 本身）映射到同一 DOM：`page-settings`。增加 `SETTINGS_SUB_PANEL_ID`，在子路由下对 `#settings-panel-*` 执行 `scrollIntoView`，使主滚动容器（`.main`）滚到对应卡片；`#/settings` 时将 `.main` 滚回顶部。

2. **`monitor_web/index.html`**：在全局配置页内为各功能块增加包裹层 `id="settings-panel-notify"` … `settings-panel-dynamic"`，与子菜单一一对应。

3. **`monitor_web/static/css/sidebar.css`**：为 `.settings-route-panel` 设置 `scroll-margin-top`，避免锚点滚动后贴顶过紧。

## 后续：配置拆分为独立模板

全局配置已从单一大段 `index.html` 拆为 `monitor_web/templates/pages/settings-*.html`，由 `load-partials.js` 注入到各 `#tpl-page-settings*` 挂载点；路由为独立 `section#page-settings`、`#page-settings-notify` 等。`saveConfig()` 在保存前 GET 合并，避免分页时未挂载字段覆盖服务端。

## 后续：切回「数据概览」布局错乱

在配置中心子项使用 `scrollIntoView` 后，`.main` 的 `scrollTop` 会停在页面下方。切回数据概览等较短页面时若未重置滚动，会出现顶部内容被裁切、底部大块空白。

**修复：**在 `showPage` 开头将 `.main`（及 `documentElement`/`body`）的纵向滚动归零，再切换 `page--active`；配置子路由仍在下一帧 `scrollIntoView` 到锚点。

## 验证

- `pytest tests/test_monitor_settings_subroutes.py`
- 浏览器：`#/settings-notify` 等应显示配置表单并滚动到对应区块（非空白）。
- 浏览器：配置子项 → 再点「数据概览」，布局应与首次打开一致。
