# 启动/停止监控误报「网络错误」且按钮不切换

## 现象

点击启动或停止监控后，右下角反复出现「网络错误」toast；调度器状态区与主按钮不随 `loadStatus` / 操作结果更新。

## 根因

`scheduler-panel.js` 从 `ui.js` 导入 `schedulerRunning` 后执行 `schedulerRunning = true/false`。在 ES 模块中，对跨模块导入的绑定赋值会在运行时抛出 **TypeError: Assignment to constant variable**，与 `accounts.js` 中 `_pendingScanNow` 问题相同。

异常被 `toggleScheduler` 的 `catch` 捕获后统一提示「网络错误」，且赋值未生效，UI 状态错乱。

## 修复

- 在 `ui.js` 增加 `setSchedulerRunning(v)`，在定义模块内合法写入 `schedulerRunning`。
- `loadStatus` 改为通过 `setSchedulerRunning` 更新。
- `scheduler-panel.js` 中停止/启动成功分支改为调用 `setSchedulerRunning(false|true)`。

## 验证

- `pytest tests/test_scheduler_panel_no_import_assignment.py`
