# 通知平台字段隔离：Telegram Bot Token 与 Webhook URL

## 现象

### Bug 1：标签硬编码

账户编辑模态框中，无论选择哪种通知平台，"Webhook URL" 输入框对应的标签始终显示"Bot Token"，飞书/钉钉/企微用户无法理解此标签含义。

### Bug 2：字段串值

填写 Telegram Bot Token 后切换到飞书/钉钉，"Webhook URL" 输入框被自动填充为 Telegram Bot Token；编辑已有账户后切换平台同样出现此问题。三个平台共用同一个数据库字段，导致数据相互污染。

### Bug 3：Telegram 平台仍显示 Webhook URL 字段

修复 Bug 1/2 后，切换到 Telegram 平台时，`#accWebhook` 输入框仍显示且带有飞书 placeholder（`https://open.feishu.cn/...`）。Telegram 通知不需要 Webhook URL，应完全不显示该字段。

### Bug 4：生产数据库迁移未执行

上线后用户提交 Telegram 账户时报错：`sqlite3.OperationalError: no such column: telegram_bot_token`。根因是 `init_db()` 调用 `monitor/db.py` 内的 `_migrate_monitor_accounts()`，但 v14 迁移只写在 `monitor/db/migrations.py` 的 `run_all_migrations()` 里——后者从未被 `init_db()` 调用。

### Bug 5：钉钉加签密钥无法保存

页面填写钉钉 `dingtalk_sign_secret` 后保存成功，但数据库中字段为空（`id=6`）；前端 UI 和 API 均支持该字段，但 `server/__main__.py` 的 `update_account`/`add_account` 调用缺少该参数，`monitor/db.py` 的对应函数也没有 INSERT/UPDATE 逻辑。

### Bug 6：钉钉签名不匹配

即使 `dingtalk_sign_secret` 能正确保存，发送通知时仍报"签名不匹配"。根因是 `scheduler.py` 通知决策逻辑：`use_global_dingtalk_secret = platform=="dingtalk" and not account.webhook_url`，即**只有当账户级 Webhook URL 为空时才用全局密钥**。用户填写了账户级 Webhook URL，走 else 分支，`dingtalk_sign_secret=None`，签名不匹配。

## 修复

### Schema 层

- `monitor/schema.sql`：新增 `telegram_bot_token TEXT DEFAULT NULL` 列，与 `webhook_url` 完全解耦。

### 迁移层（两处同步）

- `monitor/db/migrations.py`：新增 v14 迁移（idempotent）
- `monitor/db.py` `_migrate_monitor_accounts()`：同步添加 v14（**Bug 4 修复**）

### 数据库操作层（两处实现）

- `monitor/db.py`：`add_account` / `update_account` / `_decrypt_account_webhook` 新增 `telegram_bot_token` 和 `dingtalk_sign_secret` 参数及加解密逻辑（**Bug 5 修复**）。
- `monitor/db/queries/accounts.py`：同步更新。

### 调度器层

- `monitor/scheduler.py`（**Bug 6 修复**）：
  - 通知决策优先级：`account.dingtalk_sign_secret` > 全局密钥（当账户 Webhook 非空时仍可用全局密钥）
  - 修复三处：`dingtalk_sign_secret=` 参数从 `global?secret:None` 改为 `account.secret or (global if use_global else None)`

### API 层

- `server/__main__.py`：`add_account` / `update_account` / `GET accounts` 序列化均新增 `telegram_bot_token` 和 `dingtalk_sign_secret` 字段（**Bug 5 修复**）。

### 前端模态框

- `monitor_web/templates/modals/modal-account.html`：
  - 标签改为动态文本（`id="accWebhookLabel"`），平台切换时更新
  - 新增独立 Bot Token 输入框（`id="accTelegramToken"`），仅 Telegram 平台显示
  - Webhook URL 字段组包裹在 `id="accWebhookGroup"` 中（Bug 3 修复）
- `monitor_web/js/modules/accounts.js`：
  - `selectPlatform()`：Telegram 平台时隐藏 `#accWebhookGroup` 整个字段组（Bug 3）
  - `selectPlatform()`：控制两输入框的显示/隐藏，清除 Telegram 特定占位符
  - `openEditAccount()`：分别加载 `webhook_url` 和 `telegram_bot_token`
  - `saveAccount()`：Telegram 平台时 `webhook_url` 强制为 `null`，避免提交无意义数据

## 验证

- `pytest tests/test_account_telegram_token_isolation.py` — 17/17 通过
- `pytest tests/test_monitor_schema_bootstrap.py` — 2/2 通过
- `pytest tests/` — 299/299 通过，无回归

回归测试覆盖：
1. `add_account` 支持 `telegram_bot_token` 参数
2. `get_account` 正确解密 `telegram_bot_token`
3. `webhook_url` 与 `telegram_bot_token` 两字段独立互不影响
4. 仅更新 `telegram_bot_token` 时 `webhook_url` 保持不变
5. 仅更新 `webhook_url` 时 `telegram_bot_token` 保持不变
6. 未传入 `telegram_bot_token` 时为 NULL
7. `list_accounts` 返回两字段的解密值
8. Telegram 平台使用 `telegram_bot_token`
9. 飞书平台使用 `webhook_url`（不受 Telegram 字段影响）
10. 账户级 `telegram_bot_token` 优先于全局 `global_telegram_token`
11. Telegram 账户的 `webhook_url` 可以为 NULL（Bug 3 验证）
12. `add_account` 支持 `dingtalk_sign_secret`（Bug 5 验证）
13. `update_account` 保存 `dingtalk_sign_secret`（Bug 5 验证）
14. `dingtalk_sign_secret` 与 `webhook_url` 独立（Bug 5 验证）
15. 账户级 `dingtalk_sign_secret` 优先于全局密钥（Bug 6 验证）
16. 无账户级 Webhook 时回退到全局密钥（Bug 6 验证）
17. 无账户级密钥且 Webhook 非空时正确处理（Bug 6 验证）

### Bug 7：平台切换字段污染

**现象**：填写钉钉 Webhook URL 后切换到飞书，Webhook URL 被填充钉钉的值；填写飞书 Webhook URL 后切换到钉钉亦然。

**根因**：`openEditAccount()` 从数据库加载 `webhook_url` 后，`selectPlatform()` 只控制显示/隐藏，未清除跨平台残留值。

**修复**：`monitor_web/js/modules/accounts.js` `selectPlatform()`：离开 Telegram 时清除 `accTelegramToken`，离开 Feishu/Dingtalk 时不自动清除 Webhook（两者共用同一字段，各自填写自己的 URL 是合理行为）。

### Bug 8：三个平台消息模板字段不一致

**现象**：飞书消息包含时长/观看数/点赞数/评论数，钉钉和 Telegram 消息缺少时长和评论数。

**根因**：`dingtalk.py` 的 `_build_dingtalk_markdown()` 和 `telegram.py` 的 `_build_telegram_text()` 最初实现时未与飞书对齐。

**修复**：
- `monitor/notification/dingtalk.py`：`_build_dingtalk_markdown()` 添加 `duration_sec`、`like_count`、`comment_count` 字段，使用 `_format_duration_sec()` 格式化时长。
- `monitor/notification/telegram.py`：`_build_telegram_text()` 添加 `duration_sec`、`comment_count` 字段（`like_count` 原本就有），使用 `_format_duration_sec()` 格式化时长。

**验证**：`tests/test_notification_message_consistency.py` — 7/7 通过
- 三个平台均包含：时长⏱、观看数👁、点赞数👍、评论数💬
- 三个平台均包含频道信息
- 三个平台均限制展示数量（钉钉/Telegram 最多10条）
