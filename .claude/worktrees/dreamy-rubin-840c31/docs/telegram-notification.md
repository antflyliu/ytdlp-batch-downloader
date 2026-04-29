# Telegram 通知实现文档

## 概述

Telegram 是继飞书、钉钉、企业微信之后新增的通知平台。相比其他平台，Telegram 采用 Bot Token + Chat ID 的双字段模式，无需 Webhook URL。

## 架构设计

### 核心文件

| 文件 | 职责 |
|------|------|
| `monitor/notification/telegram.py` | 消息构建与 MarkdownV2 转义 |
| `monitor/notification/renderers.py` | `build_notify_payload` 分派到 telegram |
| `monitor/notification/base.py` | `Platform` 类型定义 |
| `monitor/notifier.py` | 暴露 `Platform` 重新导出 |
| `monitor/quota.py` | 配额不足时尝试 telegram 作为 fallback |
| `monitor/scheduler.py` | 存储/加载 `global_telegram_chat_id` |
| `monitor/db/db_core.py` | `global_telegram_token` 加入加密白名单 |
| `config/settings.py` | 配置默认值 |
| `server/__main__.py` | `/config` API 读写全局字段 |
| `monitor_web/` 前端文件 | Web UI 配置界面 |

### 数据流

```
账户保存 → notify_platform='telegram' + webhook_url=Token → scheduler
scheduler 启动 → 加载 global_telegram_chat_id
扫描完成 → notifier.notify(platform='telegram')
  → renderers.build_notify_payload(platform='telegram')
  → telegram._build_telegram_message()
  → renderers._send_webhook(token, payload, chat_id)
  → Telegram Bot API POST
```

## API 设计

### Telegram Bot API

**端点**: `https://api.telegram.org/bot<TOKEN>/sendMessage`

**请求体**:
```json
{
  "chat_id": "123456789",
  "text": "...",
  "parse_mode": "MarkdownV2"
}
```

**成功响应**: `{"ok": true, "result": {...}}`
**失败响应**: `{"ok": false, "error_code": 400, "description": "..."}`

## 配置字段

### 全局配置 (`config.json` / 全局设置)

| 字段 | 说明 |
|------|------|
| `global_telegram_token` | Bot Token，格式 `123456789:ABCdef...`，加密存储 |
| `global_telegram_chat_id` | 目标 Chat ID，纯数字或负数（如群组 ID） |

### 账户配置 (`accounts` 表)

| 字段 | 说明 |
|------|------|
| `notify_platform` | `'telegram'` 即可触发 |
| `webhook_url` | 填写 Bot Token，优先级高于全局 token |

## 消息格式

使用 `MarkdownV2` 解析模式，文本中特殊字符需转义。

### 转义规则 (`telegram.py::_escape_telegram_markdownv2`)

需要用反斜杠前缀转义的 13 个字符：
```
. ! ( ) [ ] _ - + = { } # | > <
```

### 消息模板

```
🔔 *YouTube Monitor*

📺 *账户名*
👤 @channel_handle

🆕 *1* 个新视频

[2026-04-14] puppy playpen reset 🐶🧺🐾 #shorts
▶️ 观看 38,816 | ⏱ 6,435ms
🔗 https://youtube.com/watch?v=xxx
```

## 与其他平台的区别

| 维度 | 飞书 | 钉钉 | 企业微信 | Telegram |
|------|------|------|----------|----------|
| 认证方式 | Webhook URL | Webhook URL + 加签 | Webhook URL | Bot Token + Chat ID |
| URL 字段 | `global_feishu_url` | `global_dingtalk_url` | `global_wecom_url` | `global_telegram_token` |
| Chat ID | 无 | 无 | 无 | `global_telegram_chat_id`（独立字段） |
| 消息格式 | JSON 卡片 | JSON 卡片 | JSON 卡片 | MarkdownV2 |
| 加密存储 | ✅ | ✅ | ✅ | ✅ (token) |

## 前端 UI 变更

### Web UI

- **modal-config.html**: 新增 `Telegram Bot Token` 和 `Telegram Chat ID` 输入框
- **modal-account.html**: 通知平台按钮组 "企微" → "Telegram"
- **accounts.js**: `selectPlatform()` 支持 `telegram`
- **account-list.js**: 账户列表显示 Telegram tag
- **form.css / common.css / base.css**: 新增 `--telegram` 颜色变量和 `.active-telegram` / `.tag-telegram` 样式

### Tkinter UI (monitor_ui.py)

- 全局设置弹窗新增 Telegram Token 和 Chat ID 字段
- 账户编辑弹窗通知平台按钮组支持 Telegram

## 安全考虑

1. **Token 加密**: `global_telegram_token` 参与配置加密轮询，存储时加密
2. **日志脱敏**: 日志中 Webhook URL 被脱敏显示（见 `monitor/scheduler.py`）
3. **Chat ID 不加密**: Chat ID 本身无敏感信息，仅为标识符

## 配置示例

### 获取 Bot Token

1. 在 Telegram 中搜索 `@BotFather`
2. 发送 `/newbot`，按提示设置机器人名称
3. 获得 Token，格式：`123456789:ABCdefGhIJKlmNoPQRsTUVwxYZ`

### 获取 Chat ID

**私聊机器人**:
1. 搜索并添加机器人
2. 发送任意消息
3. 访问 `https://api.telegram.org/bot<TOKEN>/getUpdates`，在 `message.chat.id` 中找到

**群组**:
1. 将机器人添加进群组
2. 在群组中发送 `/start`
3. 同上获取 Chat ID（通常为负数）

### 配置

**全局配置**（所有账户共用）:
- 全局设置 → 填写 Bot Token + Chat ID

**账户级配置**（覆盖全局）:
- 账户 Webhook URL 填 Token → 使用账户自己的 token