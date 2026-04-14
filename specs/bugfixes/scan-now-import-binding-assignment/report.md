# 立即扫描点击无效：`Assignment to constant variable`

## 现象

重启后点击「立即扫描」，无请求；控制台：`Uncaught TypeError: Assignment to constant variable at scanNow (accounts.js:362:19)`。

## 根因

`monitor_web/js/modules/accounts.js` 从 `state.js` 导入 `_pendingScanNow`、`_scanNowSubmitting` 后直接赋值。在 ES 模块中，对 **从其他模块导入的绑定** 在消费方视为只读，赋值会在运行时抛错（与 `const` 类似）。

`state.js` 已提供 `setPendingScanNow`、`setScanNowSubmitting`（`ui._resetScanNowState` 已正确使用）。

## 修复

- `scanNow`：`_pendingScanNow = {...}` → `setPendingScanNow({...})`
- `confirmScanNow`：`_scanNowSubmitting = true` → `setScanNowSubmitting(true)`
- 补充从 `./state.js` 导入上述 setter。

## 验证

- `pytest tests/test_accounts_scan_now_es_module_bindings.py`