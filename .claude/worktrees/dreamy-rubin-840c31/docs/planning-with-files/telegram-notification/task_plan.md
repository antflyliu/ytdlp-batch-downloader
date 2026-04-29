# 任务计划：企微 → Telegram 通知平台替换

## 目标
将"编辑监控账户"页面中通知平台的"企微"替换为"Telegram"，实现同等功能。保持架构不变（Webhook POST 模式），仅替换底层实现。wecom.py 保留不删。

## 当前阶段
**Phase 2 ✅ 全部完成**

---

## Phase 1: 可行性分析
- [x] 1.1 探查现有 wecom 相关代码分布（20个文件）
- [x] 1.2 分析影响范围和迁移成本
- [x] 1.3 制定替换方案
- **Status:** ✅ complete

## Phase 2: 后端重构
- [x] 2.1 新建 `monitor/notification/telegram.py`
- [x] 2.2 更新 `monitor/notification/base.py` — Platform 类型
- [x] 2.3 更新 `monitor/notification/renderers.py` — Telegram 分支
- [x] 2.4 更新 `monitor/scheduler.py` — `set_global_telegram_chat_id`
- [x] 2.5 更新 `monitor/quota.py` — 3 个告警函数均加入 telegram 分支
- [x] 2.6 更新 `monitor/db/db_core.py` — `global_telegram_token` 加入加密白名单
- [x] 2.7 更新 `monitor/__init__.py` — 导出
- [x] ~~2.8 删除废弃 `monitor/notification/wecom.py`~~ — 决定保留 wecom.py
- **Status:** ✅ complete

## Phase 3: 配置层
- [x] 3.1 `config/settings.py` — `global_telegram_token` + `global_telegram_chat_id`
- [x] 3.2 `config.json` — 两个字段
- [x] 3.3 `monitor/config.json` — 两个字段
- [x] 3.4 `server/__main__.py` — config API 支持 telegram 字段
- **Status:** ✅ complete

## Phase 4: 前端 Web UI
- [x] 4.1 `modal-account.html` — 企微按钮 → Telegram
- [x] 4.2 `modal-config.html` — 新增 Bot Token + Chat ID 输入框
- [x] 4.3 `accounts.js` — `selectPlatform` 支持 telegram
- [x] 4.4 `account-list.js` — 账户列表 Telegram tag
- [x] 4.5 `config.js` — openConfig/saveConfig 支持 telegram 字段
- [x] 4.6 CSS 变量和样式 — `--telegram`, `.active-telegram`, `.tag-telegram`
- **Status:** ✅ complete

## Phase 5: Tkinter UI
- [x] 5.1 `monitor_ui.py` — 通知平台按钮组加入 Telegram
- [x] 5.2 全局设置弹窗新增 Telegram Token + Chat ID 字段
- **Status:** ✅ complete

## Phase 6: 数据库（注释更新）
- [x] 6.1 `monitor/schema.sql` — platform 注释加入 telegram
- **Status:** ✅ complete

## Phase 7: 测试
- [x] 7.1 `tests/test_quota_alert_payload.py` — 新增 telegram 测试用例
- **Status:** ✅ complete

---

## 关键架构决策

| 决策 | 理由 |
|------|------|
| 保持 wecom.py 不删 | 前端"企微"替换为"Telegram"，后端 wecom.py 保留完整，用户仍可使用企业微信 |
| 配置项: `global_telegram_token` + `global_telegram_chat_id` | Telegram Bot Token + Chat ID 双字段模式 |
| 前端显示 "Telegram" | 保持英文，无歧义 |
| Schema.sql 只改注释 | 避免数据库迁移 |
| `wecom` 关键字保留在前端 | 企业微信标签保留在 account-list 和 config 中，用户仍可看到使用企微的账户 |

## Telegram vs 企微 核心差异

| 维度 | 企微 | Telegram |
|------|------|----------|
| 凭证 | Webhook URL（含 KEY） | Bot Token + Chat ID |
| API 端点 | `https://qyapi.weixin.qq.com/...` | `https://api.telegram.org/bot<TOKEN>/sendMessage` |
| 消息体 | `msgtype: textcard` + textcard 对象 | `chat_id` + `text` + `parse_mode: MarkdownV2` |
| 格式支持 | 有限 Markdown | MarkdownV2 / HTML |
| 特殊字符转义 | 无 | 需转义 13 个特殊字符 |

## 影响文件清单

**新建：**
- `monitor/notification/telegram.py` (NEW)

**修改（后端）：**
- `monitor/notification/base.py`
- `monitor/notification/renderers.py`
- `monitor/notification/__init__.py`
- `monitor/scheduler.py`
- `monitor/notifier.py`
- `monitor/quota.py`
- `monitor/db/db_core.py`
- `monitor/__init__.py`
- `monitor/schema.sql`

**修改（配置）：**
- `config/settings.py`
- `config.json`
- `monitor/config.json`
- `server/__main__.py`

**修改（前端 Web）：**
- `monitor_web/templates/modals/modal-account.html`
- `monitor_web/templates/modals/modal-config.html`
- `monitor_web/js/modules/accounts.js`
- `monitor_web/js/components/account-list.js`
- `monitor_web/js/modules/config.js`
- `monitor_web/static/css/variables.css`
- `monitor_web/static/css/form.css`
- `monitor_web/static/css/common.css`
- `monitor_web/static/css/base.css`

**修改（Tkinter）：**
- `monitor_ui.py`

**新增文档：**
- `docs/telegram-notification.md`

**新增测试：**
- `tests/test_quota_alert_payload.py` (telegram 测试用例)