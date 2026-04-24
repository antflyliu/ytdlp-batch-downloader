# Downloads 批量上传格式 pill 英文显示为裸键名

## 现象

英文模式下，**Downloads → Batch Download → Upload URL List** 中 Excel / CSV / TXT 三个 pill 显示 `batchDownload.formatExcel` 等完整键路径，而非标签文案。

## 根因

`index.html` 中三处使用 `data-i18n="batchDownload.formatExcel"` 等键；`zh.json` 的 `batchDownload` 已包含 `formatExcel` / `formatCsv` / `formatTxt`，而 **`en.json` 的 `batchDownload` 缺少这三项**。`I18n` 在缺失时回退为键名字符串，故出现裸键名。

## 修复

在 `monitor_web/static/i18n/en.json` 的 `batchDownload` 下补充：

- `formatExcel`: `"Excel"`
- `formatCsv`: `"CSV"`
- `formatTxt`: `"TXT"`

## 验证

- `pytest tests/test_monitor_i18n_en_batch_download_format_pills.py`
- 浏览器：语言切到 EN，Downloads 页三 pill 显示 Excel / CSV / TXT。
