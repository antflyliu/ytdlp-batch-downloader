# 发现：企微 → Telegram 替换可行性分析

## 结论：✅ 完全可行，生产级别可实施

**预估工作量：2-3小时，影响范围可控**

---

## 一、现有通知架构分析

### 平台抽象层（设计良好，扩展成本低）
```
Platform = Literal["feishu", "dingtalk", "wecom"]

build_notify_payload(platform, ...) → payload dict
_send_webhook(url, payload, platform) → (bool, str)
```

每个平台只需要实现：
1. `build_*` 函数：构造消息 payload
2. 配置获取：`global_{platform}_url` 或 `{platform}_sign_secret`
3. 响应解析：各平台错误码格式不同

### 现有平台对比

| 平台 | 凭证类型 | 消息构造文件 | 复杂度 |
|------|---------|-------------|--------|
| feishu | Webhook URL | renderers.py (card_json / template) | 高 |
| dingtalk | Webhook URL + Sign Secret | renderers.py + dingtalk.py | 中 |
| wecom | Webhook URL | wecom.py | 低（TextCard） |
| **telegram** | Bot Token | **新建 telegram.py** | **低** |

---

## 二、Telegram Bot API 核心信息

### 发送消息（最基础）

```
POST https://api.telegram.org/bot<TOKEN>/sendMessage

Body (JSON):
{
  "chat_id": "123456789",
  "text": "Hello from bot!",
  "parse_mode": "MarkdownV2"
}
```

### 与企微对比

| | 企微 | Telegram |
|--|------|---------|
| **端点** | 每个企业不同（`qyapi.weixin.qq.com`） | 固定 `api.telegram.org` |
| **凭证** | Webhook URL 本身含密钥 | Bot Token（URL-safe base64） |
| **必要参数** | 无需 chat_id（从 URL 推导） | `chat_id` 必需 |
| **消息格式** | TextCard JSON | 纯文本或 MarkdownV2 |
| **频率限制** | 企业在限流 | 全局 30 msg/s |

### 项目需新增：chat_id 配置

企微 Webhook URL 格式：`https://qyapi.weixin.qq.com/.../opendata/syncuserinfo?access_key=XXX`

Telegram 格式：`https://api.telegram.org/bot<TOKEN>/sendMessage`，需要单独传 `chat_id`。

**结论：配置模型需要增加 `chat_id` 字段。**

有两种方案：
- **方案 A**：token 格式嵌入 `bot<TOKEN>:<chat_id>`（配置简单但格式不标准）
- **方案 B**：新增独立 `global_telegram_chat_id` 配置项（推荐，清晰）

---

## 三、配置模型变更（最小化方案）

现有企微配置：
```json
"global_wecom_url": "https://qyapi.weixin.qq.com/..."
```

Telegram 配置：
```json
"global_telegram_token": "123456789:ABCdefGHI...",
"global_telegram_chat_id": "123456789"
```

**推荐：方案 B** — 增加两个独立配置项，不破坏现有 URL 语义。

---

## 四、受影响模块详细分析

### 4.1 monitor/notification/wecom.py（删除）
- 约 35 行 TextCard 构建代码
- 可直接参考新建 telegram.py

### 4.2 monitor/notification/base.py（改）
```python
# 改：Platform 类型
Platform = Literal["feishu", "dingtalk", "telegram"]
```

### 4.3 monitor/notification/renderers.py（改）
- 添加 `from .telegram import _build_telegram_message`
- 添加 `platform == "telegram"` 分支

### 4.4 monitor/scheduler.py（改）
```python
# 改：新增
_GLOBAL_WEBHOOKS["telegram"] = cfg.get("global_telegram_token") or None
def set_global_telegram_url(url: str | None) -> None:
    _GLOBAL_WEBHOOKS["telegram"] = url
```

### 4.5 monitor/quota.py（改）
```python
# 改：两处 wecom_url → telegram_token + telegram_chat_id
elif cfg.get("global_telegram_token"):
    webhook_url = f"https://api.telegram.org/bot{cfg['global_telegram_token']}/sendMessage"
    chat_id = cfg.get("global_telegram_chat_id", "")
```

### 4.6 monitor_ui.py（改）
```python
# 改：UI label + 字段名
("Telegram Bot Token", "global_telegram_token", "#26A5E4", False),
("Telegram Chat ID",  "global_telegram_chat_id", "#26A5E4", False),
```

### 4.7 schema.sql（改注释）
```sql
-- 改：platform 枚举注释
-- 平台：feishu / dingtalk / telegram
```

---

## 五、Telegram 消息格式建议

由于企微是 TextCard（标题+描述+链接），Telegram 对应使用 MarkdownV2：

```json
{
  "chat_id": "123456",
  "text": "🎬 *账户名 — 1 个新视频*\n\n频道：@channel_name\n\n1. *视频标题*\n   📅 2026-04-14 | 👁 38,816 | 👍 1,200\n   🔗 [观看](https://youtube.com/watch?v=xxx)",
  "parse_mode": "MarkdownV2"
}
```

**注意**：Telegram MarkdownV2 需要对特殊字符转义（`[`, `]`, `(`, `)`, `.` 等），`_build_telegram_message` 需要处理。

---

## 六、风险评估

| 风险 | 级别 | 缓解 |
|------|------|------|
| Telegram 在国内访问受限 | 中 | 与企微同样问题，用户需自备代理/VPS |
| chat_id 配置增加复杂度 | 低 | 提供明确 UI 指引 |
| MarkdownV2 转义出错 | 低 | 参考 `renderers.py` 已有 `_escape_lark_md` 模式 |
| 已有监控账户数据迁移 | 无 | Schema 不变，企微配置静默废弃 |

**无数据库迁移风险**：schema.sql 中 `platform TEXT` 已是字符串，无约束变更。
