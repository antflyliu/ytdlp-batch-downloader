# baoyu-post-to-wechat 集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 baoyu-post-to-wechat 的 API 发布模式集成到 ytdlp-batch-downloader，实现 AI 文章生成完成后一键保存到公众号草稿箱（默认），或可选立即群发发布。

**Architecture:** 复用 baoyu-wechat-api.ts 的 TypeScript 脚本逻辑，改写为 Python 模块。在 monitor/ 下新增 wechat_publisher.py，封装公众号 API 调用（草稿新建、提交发布两个独立操作）。数据库新增 wechat_publish_tasks 表记录发布状态，支持两种模式：draft（仅保存草稿）和 publish（群发发布，订阅号每月限额 4 次需明确提示）。API 层新增 /api/wechat/draft（默认）、/api/wechat/publish（需确认配额）和 /api/wechat/tasks/{task_id} 端点。前端在设置中心新增微信公众号配置页（settings-hub/wechat）和文章发布面板（AiCreation.vue），默认操作保存草稿，可选手动群发并显示配额警告。

**Tech Stack:** Python (wechat-publisher module), SQLite (wechat_publish_tasks), Vanilla HTTP API (server/__main__.py), Vue 3 + Naive UI (frontend-vue)

---

## File Map

### 新增文件

- `monitor/wechat_publisher.py` — 微信公众号 API 发布封装（save_to_draft 仅创建草稿、publish_now 创建草稿+立即群发两个独立方法）
- `frontend-vue/src/views/settings/WechatPublishSettings.vue` — 公众号凭证配置页（AppID/AppSecret、主题配色、默认作者）
- `frontend-vue/src/locales/en.json` — 新增 wechatPublish 英文 i18n（追加 key）
- `frontend-vue/src/locales/zh.json` — 新增 wechatPublish 中文 i18n（追加 key）
- `tests/test_wechat_publish_api.py` — API 端点测试
- `tests/test_wechat_publisher.py` — 发布器单元测试

### 修改文件

- `config/settings.py` — 新增 wechat 凭证和发布配置 key（wechat_app_id、wechat_app_secret、wechat_default_author 等）
- `config/validation.py` — 新增 wechat 配置字段验证（可选）
- `monitor/schema.sql` — 新增 wechat_publish_tasks 表 + 索引
- `monitor/db.py` — 新增 v18 wechat_publish_tasks 迁移 + CRUD 函数
- `server/__main__.py` — 新增 wechat publish API 路由（do_GET/do_POST）
- `frontend-vue/src/api/config.ts` — AppConfig 新增 wechat 配置字段
- `frontend-vue/src/api/wechatPublish.ts` — 新增发布相关 API 方法
- `frontend-vue/src/router/index.ts` — 新增 /settings-hub/wechat 路由
- `frontend-vue/src/components/layout/AppSider.vue` — 侧边栏新增公众号配置入口

---

## Phase 0: 依赖验证

> 在 Task 0 中执行，不影响主流程。

- [ ] **Step 0.1: 确认 bun 可用**

Run: `bun --version` 或 `npx bun --version`
Expected: 版本号输出（任意版本即可）

- [ ] **Step 0.2: 获取 baoyu-wechat-api.ts 脚本源码**

从 baoyu-post-to-wechat skill 的 `scripts/wechat-api.ts` 读取关键逻辑：
- 微信公众号 API 调用方式（access_token 获取、草稿新建、封面图上传、正文 HTML 上传、提交发布）
- API 端点：`https://api.weixin.qq.com/cgi-bin/draft/add?access_token=xxx`
- 图片上传：`https://api.weixin.qq.com/cgi-bin/media/upload?access_token=xxx&type=image`
- 提交发布：`https://api.weixin.qq.com/cgi-bin/freepublish/submit?access_token=xxx`

- [ ] **Step 0.3: 创建本地测试草稿（手动验证 API 可用）**

使用 curl 手动调用一次微信公众号 API（access_token 刷新、草稿新建），确认凭证有效。

---

## Phase 1: 配置层

### Task 1: config/settings.py — 新增 wechat 配置 key

**Files:**
- Modify: `config/settings.py:46-150`

- [ ] **Step 1.1: 添加 wechat 默认配置到 _config_default()**

在 `_config_default()` 字典末尾添加：

```python
# ── 微信公众号发布配置 ─────────────────────────────────────
"wechat_app_id": "",
"wechat_app_secret": "",
"wechat_default_author": "",
"wechat_default_theme": "default",
"wechat_default_color": "blue",
"wechat_need_open_comment": True,
"wechat_only_fans_can_comment": False,
```

- [ ] **Step 1.2: 将 wechat_app_secret 加入加密 key 列表**

找到 `_SECRET_CONFIG_KEYS`，添加 `"wechat_app_secret"`：

```python
_SECRET_CONFIG_KEYS = (
    "llm_api_key",
    "whisper_api_key",
    "comfyui_api_key",
    "runninghub_api_key",
    "wechat_app_secret",  # 新增
)
```

- [ ] **Step 1.3: 提交**

```bash
git add config/settings.py
git commit -m "config: add wechat publish config keys"
```

### Task 2: config/validation.py — 新增 wechat 配置验证

**Files:**
- Modify: `config/validation.py`

- [ ] **Step 2.1: 读取现有 validation.py 结构**

Run: `head -50 config/validation.py`

- [ ] **Step 2.2: 添加 wechat 配置验证函数**

在文件末尾添加：

```python
def validate_wechat_config(cfg: dict) -> list[str]:
    """验证微信公众号配置，返回错误列表。"""
    errors = []
    app_id = cfg.get("wechat_app_id") or ""
    app_secret = cfg.get("wechat_app_secret") or ""
    if app_id and not re.match(r"^wx[a-zA-Z0-9]{16}$", app_id):
        errors.append("wechat_app_id 格式不正确，应为 wx 开头 18 位字母数字")
    if app_secret and len(app_secret) < 16:
        errors.append("wechat_app_secret 过短")
    valid_themes = {"default", "grace", "simple", "modern"}
    theme = cfg.get("wechat_default_theme") or "default"
    if theme not in valid_themes:
        errors.append(f"wechat_default_theme 必须是 {valid_themes} 之一")
    valid_colors = {"blue", "green", "vermilion", "yellow", "purple", "sky",
                    "rose", "olive", "black", "gray", "pink", "red", "orange"}
    color = cfg.get("wechat_default_color") or "blue"
    if color not in valid_colors:
        errors.append(f"wechat_default_color 必须是 {valid_colors} 之一")
    return errors
```

- [ ] **Step 2.3: 提交**

```bash
git add config/validation.py
git commit -m "config: add wechat config validation"
```

---

## Phase 2: 数据库层

### Task 3: monitor/schema.sql — 新增 wechat_publish_tasks 表

**Files:**
- Modify: `monitor/schema.sql`

- [ ] **Step 3.1: 在 schema.sql 末尾添加表定义**

在文件末尾（最后一个 CREATE TABLE 之后）添加：

```sql
-- ── 微信公众号发布任务表 ───────────────────────────────
CREATE TABLE IF NOT EXISTS wechat_publish_tasks (
    task_id           TEXT PRIMARY KEY,
    article_task_id   TEXT,                          -- 关联的 article_tasks.task_id（可选）
    draft_path       TEXT,                          -- draft.md 文件路径
    title            TEXT,
    author           TEXT,
    theme            TEXT NOT NULL DEFAULT 'default',
    color            TEXT NOT NULL DEFAULT 'blue',
    need_open_comment INTEGER NOT NULL DEFAULT 1,
    only_fans_can_comment INTEGER NOT NULL DEFAULT 0,
    cover_image      TEXT,                          -- 封面图路径
    html_content     TEXT,                          -- 转换后的 HTML 内容（可选，文件路径优先）
    publish_mode     TEXT NOT NULL DEFAULT 'draft',  -- draft=仅保存草稿(默认), publish=立即群发
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending / running / done / error / cancelled
    wx_article_id    TEXT,                          -- 微信返回的 article_id（发布成功后）
    wx_url           TEXT,                          -- 微信图文消息 URL
    error            TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    finished_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_wechat_tasks_created_at ON wechat_publish_tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wechat_tasks_status ON wechat_publish_tasks(status, created_at DESC);
CREATE INDEX IF EXISTS idx_wechat_tasks_article ON wechat_publish_tasks(article_task_id, created_at DESC);
```

- [ ] **Step 3.2: 提交**

```bash
git add monitor/schema.sql
git commit -m "schema: add wechat_publish_tasks table"
```

### Task 4: monitor/db.py — 新增 v18 迁移 + CRUD 函数

**Files:**
- Modify: `monitor/db.py`

- [ ] **Step 4.1: 添加 v18 迁移**

在 `_migrate_monitor_accounts` 函数末尾（v17 迁移之后）添加：

```python
# v18: 微信公众号发布任务表
if "v18_wechat_publish_tasks" not in applied:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wechat_publish_tasks (
            task_id           TEXT PRIMARY KEY,
            article_task_id   TEXT,
            draft_path       TEXT,
            title            TEXT,
            author           TEXT,
            theme            TEXT NOT NULL DEFAULT 'default',
            color            TEXT NOT NULL DEFAULT 'blue',
            need_open_comment INTEGER NOT NULL DEFAULT 1,
            only_fans_can_comment INTEGER NOT NULL DEFAULT 0,
            cover_image      TEXT,
            html_content     TEXT,
            publish_mode     TEXT NOT NULL DEFAULT 'draft',  -- draft=仅草稿, publish=立即群发
            status           TEXT NOT NULL DEFAULT 'pending',
            wx_article_id    TEXT,
            wx_url           TEXT,
            error            TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            finished_at      TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wechat_tasks_created_at ON wechat_publish_tasks(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wechat_tasks_status ON wechat_publish_tasks(status, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wechat_tasks_article ON wechat_publish_tasks(article_task_id, created_at DESC)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        ("v18_wechat_publish_tasks", today),
    )
```

- [ ] **Step 4.2: 添加 CRUD 函数**

在 db.py 末尾（`list_clip_tasks` 之后）添加：

```python
# ── wechat_publish_tasks CRUD ─────────────────────────────────

def create_wechat_publish_task(
    draft_path: str,
    title: str | None,
    *,
    article_task_id: str | None = None,
    author: str | None = None,
    theme: str = "default",
    color: str = "blue",
    need_open_comment: bool = True,
    only_fans_can_comment: bool = False,
    cover_image: str | None = None,
    html_content: str | None = None,
    publish_mode: str = "draft",  # draft=仅草稿(默认), publish=立即群发
) -> str:
    """创建微信公众号发布任务，返回 task_id。"""
    task_id = f"wechat_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_publish_tasks
               (task_id, article_task_id, draft_path, title, author,
                theme, color, need_open_comment, only_fans_can_comment,
                cover_image, html_content, publish_mode, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                task_id, article_task_id, draft_path, title, author,
                theme, color,
                int(need_open_comment), int(only_fans_can_comment),
                cover_image, html_content, publish_mode, now, now,
            ),
        )
    return task_id


def update_wechat_publish_task(
    task_id: str,
    *,
    status=_UNSET,
    wx_article_id=_UNSET,
    wx_url=_UNSET,
    error=_UNSET,
    finished_at=_UNSET,
    html_content=_UNSET,
) -> None:
    """更新微信公众号发布任务。"""
    fields, values = [], []
    mapping = [
        ("status", status),
        ("wx_article_id", wx_article_id),
        ("wx_url", wx_url),
        ("error", error),
        ("finished_at", finished_at),
        ("html_content", html_content),
    ]
    for field, value in mapping:
        if value is not _UNSET:
            fields.append(f"{field}=?")
            values.append(value)
    if not fields:
        return
    fields.append("updated_at=?")
    values.append(now_iso())
    values.append(task_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE wechat_publish_tasks SET {', '.join(fields)} WHERE task_id = ?",
            values,
        )


def get_wechat_publish_task(task_id: str) -> dict | None:
    """获取单个发布任务。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wechat_publish_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    return dict(row) if row else None


def list_wechat_publish_tasks(
    *,
    status: str | None = None,
    article_task_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """分页查询发布任务列表。"""
    where = []
    params = []
    if status:
        where.append("status = ?")
        params.append(status)
    if article_task_id:
        where.append("article_task_id = ?")
        params.append(article_task_id)
    where_sql = " AND ".join(where) if where else "1=1"
    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM wechat_publish_tasks WHERE {where_sql}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT * FROM wechat_publish_tasks
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    return ([dict(row) for row in rows], total)
```

- [ ] **Step 4.3: 提交**

```bash
git add monitor/db.py
git commit -m "db: add wechat_publish_tasks migration and CRUD"
```

---

## Phase 3: 发布器核心模块

### Task 5: monitor/wechat_publisher.py — 微信公众号 API 发布器

**Files:**
- Create: `monitor/wechat_publisher.py`
- Test: `tests/test_wechat_publisher.py`

- [ ] **Step 5.1: 写测试 — 凭证验证失败**

```python
import pytest, tempfile, os, json
from monitor import wechat_publisher as wp

def test_access_token_fails_without_credentials():
    """无凭证时抛出 ValueError。"""
    with pytest.raises(ValueError, match="wechat_app_id.*required"):
        wp.WechatPublisher("", "", "tmp")

def test_access_token_fails_with_empty_secret():
    """AppSecret 为空时抛出 ValueError。"""
    with pytest.raises(ValueError, match="wechat_app_secret.*required"):
        wp.WechatPublisher("wx1234567890123456", "", "tmp")

def test_build_article_content_from_draft_path(tmp_path):
    """draft.md 存在时能解析标题和正文。"""
    draft = tmp_path / "draft.md"
    draft.write_text("---\ntitle: 测试标题\n---\n\n正文内容", encoding="utf-8")
    title, content = wp.build_article_content_from_draft(draft)
    assert title == "测试标题"
    assert "正文内容" in content
```

Run: `python -m pytest tests/test_wechat_publisher.py::test_access_token_fails_without_credentials tests/test_wechat_publisher.py::test_build_article_content_from_draft_path -v`
Expected: FAIL (module not found)

- [ ] **Step 5.2: 实现最小模块**

创建 `monitor/wechat_publisher.py`：

```python
"""
monitor/wechat_publisher.py — 微信公众号 API 发布器

封装微信公众号发布 API：
1. access_token 获取与缓存
2. 草稿新建（新增封面图）
3. 提交发布
4. HTML 内容生成（从 draft.md）
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_log = logging.getLogger("monitor.wechat_publisher")

_ACCESS_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_ACCESS_TOKEN_TTL = 7000  # 官方 7200s，预留 200s buffer


@dataclass
class WechatPublishResult:
    success: bool
    wx_article_id: Optional[str] = None
    wx_url: Optional[str] = None
    error: Optional[str] = None


class WechatPublisher:
    """
    微信公众号发布器（API 模式）。
    凭证来源优先级：构造参数 > config/default。
    """

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        data_dir: str | None = None,
    ):
        from config.settings import load_config
        cfg = load_config()
        self.app_id = (app_id or cfg.get("wechat_app_id") or "").strip()
        self.app_secret = (app_secret or cfg.get("wechat_app_secret") or "").strip()
        self.data_dir = data_dir or cfg.get("article_output_dir", "output/articles")
        self.default_author = cfg.get("wechat_default_author", "")
        self.default_theme = cfg.get("wechat_default_theme", "default")
        self.default_color = cfg.get("wechat_default_color", "blue")
        self._validate_credentials()

    def _validate_credentials(self):
        if not self.app_id:
            raise ValueError("wechat_app_id is required")
        if not self.app_secret:
            raise ValueError("wechat_app_secret is required")
        if not re.match(r"^wx[a-zA-Z0-9]{16}$", self.app_id):
            raise ValueError(f"wechat_app_id 格式不正确: {self.app_id}")

    def _get_access_token(self) -> str:
        """获取 access_token，带内存缓存。"""
        cache_key = f"{self.app_id}"
        if cache_key in _ACCESS_TOKEN_CACHE:
            token, expire_at = _ACCESS_TOKEN_CACHE[cache_key]
            if time.time() < expire_at - 60:
                return token

        url = (
            "https://api.weixin.qq.com/cgi-bin/token"
            f"?grant_type=client_credential&appid={self.app_id}&secret={self.app_secret}"
        )
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
        except urllib.error.URLError as e:
            raise RuntimeError(f"获取 access_token 失败: {e}")

        if "access_token" not in data:
            err_msg = data.get("errmsg", str(data))
            raise RuntimeError(f"获取 access_token 失败: {err_msg}")

        token = data["access_token"]
        expires_in = int(data.get("expires_in", 7200))
        _ACCESS_TOKEN_CACHE[cache_key] = (token, time.time() + expires_in)
        return token

    def _api_post(self, path: str, payload: dict) -> dict:
        """发送微信 API 请求，自动补充 access_token。"""
        token = self._get_access_token()
        url = f"https://api.weixin.qq.com{path}?access_token={token}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read())
                return {"errcode": e.code, "errmsg": err_body.get("errmsg", str(err_body))}
            except Exception:
                return {"errcode": e.code, "errmsg": str(e)}
        except urllib.error.URLError as e:
            raise RuntimeError(f"API 请求失败: {e}")

    def _upload_image(self, image_path: str | None) -> str | None:
        """上传图片到微信临时素材，返回 media_id。"""
        if not image_path or not os.path.exists(image_path):
            return None
        token = self._get_access_token()
        boundary = "----WechatBoundary"
        filename = os.path.basename(image_path)
        with open(image_path, "rb") as f:
            img_data = f.read()
        mime = "image/png" if filename.lower().endswith(".png") else "image/jpeg"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + img_data + f"\r\n--{boundary}--\r\n".encode("utf-8")
        url = f"https://api.weixin.qq.com/cgi-bin/media/upload?access_token={token}&type=image"
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
        except urllib.error.URLError as e:
            _log.warning("图片上传失败，跳过封面: %s", e)
            return None
        if result.get("errcode", 0) != 0:
            _log.warning("图片上传失败: %s", result.get("errmsg"))
            return None
        return result.get("media_id")

    def _create_draft(
        self,
        title: str,
        author: str,
        digest: str,
        content: str,
        cover_media_id: str | None,
        need_open_comment: bool = True,
        only_fans_can_comment: bool = False,
    ) -> str:
        """创建草稿，返回 media_id（article_id）。"""
        payload = {
            "articles": [
                {
                    "title": title,
                    "author": author,
                    "digest": digest[:120],
                    "content": content,
                    "content_source_url": "",
                    "thumb_media_id": cover_media_id or "",
                    "need_open_comment": 1 if need_open_comment else 0,
                    "only_fans_can_comment": 1 if only_fans_can_comment else 0,
                }
            ]
        }
        result = self._api_post("/cgi-bin/draft/add", payload)
        if result.get("errcode", 0) != 0:
            raise RuntimeError(
                f"创建草稿失败: errcode={result['errcode']}, errmsg={result.get('errmsg')}"
            )
        media_id = result.get("media_id")
        if not media_id:
            raise RuntimeError(f"创建草稿成功但未返回 media_id: {result}")
        return media_id

    def _submit_publish(self, media_id: str) -> dict:
        """提交发布，返回发布任务 ID。"""
        payload = {"media_id": media_id}
        result = self._api_post("/cgi-bin/freepublish/submit", payload)
        if result.get("errcode", 0) != 0:
            raise RuntimeError(
                f"提交发布失败: errcode={result['errcode']}, errmsg={result.get('errmsg')}"
            )
        return result

    def save_to_draft(
        self,
        title: str,
        content: str,
        *,
        author: str | None = None,
        cover_image: str | None = None,
        digest: str | None = None,
        need_open_comment: bool = True,
        only_fans_can_comment: bool = False,
    ) -> WechatPublishResult:
        """仅保存到草稿箱，不触发群发（订阅号默认推荐）。"""
        try:
            author = author or self.default_author
            digest = digest or title[:80]
            cover_media_id = self._upload_image(cover_image)
            media_id = self._create_draft(
                title=title,
                author=author,
                digest=digest,
                content=content,
                cover_media_id=cover_media_id,
                need_open_comment=need_open_comment,
                only_fans_can_comment=only_fans_can_comment,
            )
            return WechatPublishResult(
                success=True,
                wx_article_id=media_id,
                wx_url=None,
            )
        except Exception as e:
            _log.error("保存到草稿失败: %s", e)
            return WechatPublishResult(success=False, error=str(e))

    def publish_now(
        self,
        title: str,
        content: str,
        *,
        author: str | None = None,
        cover_image: str | None = None,
        digest: str | None = None,
        need_open_comment: bool = True,
        only_fans_can_comment: bool = False,
    ) -> WechatPublishResult:
        """创建草稿并立即群发（会占用每月群发配额，订阅号每月限4次）。"""
        try:
            author = author or self.default_author
            digest = digest or title[:80]
            cover_media_id = self._upload_image(cover_image)
            media_id = self._create_draft(
                title=title,
                author=author,
                digest=digest,
                content=content,
                cover_media_id=cover_media_id,
                need_open_comment=need_open_comment,
                only_fans_can_comment=only_fans_can_comment,
            )
            self._submit_publish(media_id)
            return WechatPublishResult(
                success=True,
                wx_article_id=media_id,
                wx_url=None,
            )
        except Exception as e:
            _log.error("立即发布失败: %s", e)
            return WechatPublishResult(success=False, error=str(e))


# ── 工具函数 ─────────────────────────────────────────────────

def build_article_content_from_draft(draft_path: str | Path) -> tuple[str, str]:
    """
    从 draft.md 解析标题和正文 HTML。
    frontmatter 支持 title 字段，正文输出简化 HTML（p/blockquote/img/h2-h6）。
    返回 (title, html_content)。
    """
    draft_path = Path(draft_path)
    raw = draft_path.read_text(encoding="utf-8")
    title = ""
    body = raw

    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            fm = parts[1]
            body = parts[2].strip()
            for line in fm.splitlines():
                if line.strip().startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip('"\'')
                    break

    if not title:
        h1 = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = h1.group(1).strip() if h1 else draft_path.stem

    # 简单 Markdown → HTML 转换（支持 img/link/bold/italic/blockquote/code）
    html_parts = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # img
        img_match = re.match(r"!\[(.*?)\]\((.+?)\)", line)
        if img_match:
            alt, src = img_match.groups()
            html_parts.append(f'<p><img src="{src}" alt="{alt}" style="max-width:100%;"/></p>')
            continue
        # link
        line = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', line)
        # bold italic
        line = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"\*(.+?)\*", r"<em>\1</em>", line)
        # inline code
        line = re.sub(r"`(.+?)`", r"<code>\1</code>", line)
        # blockquote
        if line.startswith(">"):
            content = line.lstrip("> ").strip()
            html_parts.append(f"<blockquote>{content}</blockquote>")
            continue
        # h2-h6
        h_match = re.match(r"^(#{2,6})\s+(.+)$", line)
        if h_match:
            level = len(h_match.group(1))
            text = h_match.group(2).strip()
            html_parts.append(f"<h{level}>{text}</h{level}>")
            continue
        if line:
            html_parts.append(f"<p>{line}</p>")

    return title, "\n".join(html_parts)


def convert_md_to_html_for_wechat(input_path: str | Path) -> tuple[str, str]:
    """
    兼容性别名：将 .md 文件转换为微信友好的 HTML。
    返回 (title, html_content)。
    """
    return build_article_content_from_draft(input_path)
```

- [ ] **Step 5.3: 运行测试验证**

Run: `python -m pytest tests/test_wechat_publisher.py -v`
Expected: PASS（无凭证测试应通过，build_article_content 测试应通过）

- [ ] **Step 5.4: 提交**

```bash
git add monitor/wechat_publisher.py tests/test_wechat_publisher.py
git commit -m "feat: add WechatPublisher for WeChat Official Account publishing"
```

---

## Phase 4: API 层

### Task 6: server/__main__.py — 新增 wechat publish API

**Files:**
- Modify: `server/__main__.py`

- [ ] **Step 6.1: 添加 do_GET 分支**

在 `do_GET` 的 `elif` 链中（`/api/proxy/config` 分支之后）添加：

```python
elif path == "/api/wechat/config":
    self._api_wechat_config()
```

在 `elif path == "/api/proxy/config":` 下方添加：

```python
def _api_wechat_config(self):
    """GET /api/wechat/config — 返回 wechat 配置（隐藏 app_secret）。"""
    cfg = _db.load_config()
    safe = {
        "wechat_app_id": cfg.get("wechat_app_id") or "",
        "wechat_default_author": cfg.get("wechat_default_author") or "",
        "wechat_default_theme": cfg.get("wechat_default_theme", "default"),
        "wechat_default_color": cfg.get("wechat_default_color", "blue"),
        "wechat_need_open_comment": cfg.get("wechat_need_open_comment", True),
        "wechat_only_fans_can_comment": cfg.get("wechat_only_fans_can_comment", False),
        "configured": bool(cfg.get("wechat_app_id") and cfg.get("wechat_app_secret")),
    }
    self._send_json(safe)
```

- [ ] **Step 6.2: 添加 do_POST 分支**

在 `do_POST` 的 `elif` 链中（`/api/res/open-folder` 之后，`else: self._send_json` 之前）添加：

```python
elif path == "/api/wechat/draft":
    self._api_wechat_draft(body)
elif path == "/api/wechat/publish":
    self._api_wechat_publish(body)
elif path.startswith("/api/wechat/tasks/"):
    task_id = path.split("/")[-1]
    self._api_wechat_task_status(task_id)
```

在 `_api_res_open_folder` 方法定义之后添加两个方法：

```python
def _api_wechat_draft(self, body: dict):
    """
    POST /api/wechat/draft
    将文章保存到公众号草稿箱（不触发群发，不占配额）。
    Body: { draft_path?, article_task_id?, title?, content?, author?, theme?, color?,
            cover_image?, need_open_comment?, only_fans_can_comment? }
    """
    self._handle_wechat_publish(body, publish_mode="draft")


def _api_wechat_publish(self, body: dict):
    """
    POST /api/wechat/publish
    创建草稿并立即群发（占用每月群发配额，订阅号每月限4次）。
    Body: 同 /api/wechat/draft
    """
    self._handle_wechat_publish(body, publish_mode="publish")


def _handle_wechat_publish(self, body: dict, publish_mode: str):
    """共用处理逻辑，publish_mode=draft 仅存草稿，publish_mode=publish 立即群发。"""
    from monitor import wechat_publisher as wp
    from config.validation import validate_wechat_config
    from config.settings import load_config

    cfg = load_config()
    validation_errors = validate_wechat_config(cfg)
    if validation_errors:
        self._send_json({"error": validation_errors[0], "details": validation_errors}, 400)
        return

    draft_path = body.get("draft_path") or ""
    article_task_id = body.get("article_task_id") or None
    title = body.get("title") or ""
    content = body.get("content") or ""
    author = body.get("author") or cfg.get("wechat_default_author") or ""
    theme = body.get("theme") or cfg.get("wechat_default_theme", "default")
    color = body.get("color") or cfg.get("wechat_default_color", "blue")
    need_open_comment = body.get("need_open_comment", cfg.get("wechat_need_open_comment", True))
    only_fans_can_comment = body.get("only_fans_can_comment", cfg.get("wechat_only_fans_can_comment", False))
    cover_image = body.get("cover_image") or None

    # 如果没有直接传 content，尝试从 draft_path 读取
    if not content and draft_path:
        if not os.path.isfile(draft_path):
            self._send_json({"error": f"draft 文件不存在: {draft_path}"}, 400)
            return
        title, content = wp.convert_md_to_html_for_wechat(draft_path)
    elif not content:
        self._send_json({"error": "content 或 draft_path 至少需要一个"}, 400)
        return

    if not title:
        self._send_json({"error": "title 不能为空"}, 400)
        return

    # 创建发布任务记录
    task_id = _db.create_wechat_publish_task(
        draft_path=draft_path,
        title=title,
        article_task_id=article_task_id,
        author=author,
        theme=theme,
        color=color,
        need_open_comment=need_open_comment,
        only_fans_can_comment=only_fans_can_comment,
        cover_image=cover_image,
        html_content=content,
        publish_mode=publish_mode,
    )

    # 异步执行（后台线程）
    def _publish_task():
        _db.update_wechat_publish_task(task_id, status="running")
        publisher = wp.WechatPublisher()
        if publish_mode == "draft":
            result = publisher.save_to_draft(
                title=title, content=content, author=author,
                cover_image=cover_image, need_open_comment=need_open_comment,
                only_fans_can_comment=only_fans_can_comment,
            )
        else:
            result = publisher.publish_now(
                title=title, content=content, author=author,
                cover_image=cover_image, need_open_comment=need_open_comment,
                only_fans_can_comment=only_fans_can_comment,
            )
        if result.success:
            _db.update_wechat_publish_task(
                task_id, status="done",
                wx_article_id=result.wx_article_id,
                wx_url=result.wx_url,
                finished_at=_db.now_iso(),
            )
        else:
            _db.update_wechat_publish_task(
                task_id, status="error", error=result.error,
                finished_at=_db.now_iso(),
            )

    import threading
    t = threading.Thread(target=_publish_task, daemon=True)
    t.start()

    self._send_json({"task_id": task_id, "status": "pending"})


def _api_wechat_task_status(self, task_id: str):
    """GET /api/wechat/tasks/{task_id}"""
    task = _db.get_wechat_publish_task(task_id)
    if not task:
        self._send_json({"error": "任务不存在"}, 404)
        return
    safe = {
        "task_id": task.get("task_id"),
        "article_task_id": task.get("article_task_id"),
        "title": task.get("title"),
        "author": task.get("author"),
        "publish_mode": task.get("publish_mode"),
        "status": task.get("status"),
        "wx_article_id": task.get("wx_article_id"),
        "wx_url": task.get("wx_url"),
        "error": task.get("error"),
        "created_at": task.get("created_at"),
        "finished_at": task.get("finished_at"),
    }
    self._send_json(safe)
```

- [ ] **Step 6.3: 写测试**

创建 `tests/test_wechat_publish_api.py`：

```python
import pytest, json, os, tempfile
from unittest.mock import patch, MagicMock

@pytest.fixture
def app_client():
    """创建测试用 app client（复用的 test_conftest.py 模式）。"""
    # 参考现有 test_* 文件的 fixture 模式
    pass

def test_draft_requires_config(test_client, tmp_path):
    """未配置 wechat 凭证时返回 400。"""
    with patch("server.__main__._db.load_config", return_value={}):
        resp = test_client.post(
            "/api/wechat/draft",
            json={"title": "测试", "content": "<p>内容</p>"},
        )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data

def test_draft_requires_content_or_draft_path(test_client):
    """无 content 也无 draft_path 时返回 400。"""
    with patch("server.__main__._db.load_config") as mock_cfg:
        mock_cfg.return_value = {"wechat_app_id": "wx1234567890123456",
                                  "wechat_app_secret": "test_secret_123456"}
        resp = test_client.post(
            "/api/wechat/draft",
            json={"title": "测试"},
        )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "content 或 draft_path" in data["error"]

def test_draft_and_publish_both_exist(test_client):
    """draft 和 publish 两个端点都存在。"""
    with patch("server.__main__._db.load_config", return_value={}):
        # draft 端点
        resp1 = test_client.post("/api/wechat/draft", json={})
        # publish 端点（立即群发）
        resp2 = test_client.post("/api/wechat/publish", json={})
    # 两个都应返回 400（缺少凭证），而不是 404
    assert resp1.status_code == 400
    assert resp2.status_code == 400

def test_publish_task_status_not_found(test_client):
    """不存在的 task_id 返回 404。"""
    with patch("server.__main__._db.get_wechat_publish_task", return_value=None):
        resp = test_client.get("/api/wechat/tasks/nonexistent")
    assert resp.status_code == 404
```

Run: `python -m pytest tests/test_wechat_publish_api.py -v`
Expected: FAIL (功能未实现)

- [ ] **Step 6.4: 提交**

```bash
git add server/__main__.py tests/test_wechat_publish_api.py
git commit -m "feat: add WeChat draft + publish API endpoints"
```

---

## Phase 5: 前端 — 配置页

### Task 7: 微信公众号配置页

**Files:**
- Create: `frontend-vue/src/views/settings/WechatPublishSettings.vue`
- Modify: `frontend-vue/src/router/index.ts`
- Modify: `frontend-vue/src/components/layout/AppSider.vue`
- Modify: `frontend-vue/src/api/config.ts`
- Modify: `frontend-vue/src/locales/zh.json`
- Modify: `frontend-vue/src/locales/en.json`
- Create: `frontend-vue/src/api/wechatPublish.ts`

- [ ] **Step 7.1: 创建 wechatPublish API 模块**

创建 `frontend-vue/src/api/wechatPublish.ts`：

```typescript
import request from '@/api/request'

export default {
  getConfig() {
    return request<{
      wechat_app_id: string
      wechat_default_author: string
      wechat_default_theme: string
      wechat_default_color: string
      wechat_need_open_comment: boolean
      wechat_only_fans_can_comment: boolean
      configured: boolean
    }>({
      url: '/api/wechat/config',
      method: 'get',
    })
  },

  saveToDraft(data: {
    draft_path?: string
    article_task_id?: string
    title?: string
    content?: string
    author?: string
    theme?: string
    color?: string
    cover_image?: string
    need_open_comment?: boolean
    only_fans_can_comment?: boolean
  }) {
    return request<{ task_id: string; status: string }>({
      url: '/api/wechat/draft',
      method: 'post',
      data,
    })
  },

  publishNow(data: {
    draft_path?: string
    article_task_id?: string
    title?: string
    content?: string
    author?: string
    theme?: string
    color?: string
    cover_image?: string
    need_open_comment?: boolean
    only_fans_can_comment?: boolean
  }) {
    return request<{ task_id: string; status: string }>({
      url: '/api/wechat/publish',
      method: 'post',
      data,
    })
  },

  getTaskStatus(taskId: string) {
    return request<{
      task_id: string
      article_task_id?: string
      title: string
      author: string
      publish_mode: string
      status: string
      wx_article_id?: string
      wx_url?: string
      error?: string
      created_at: string
      finished_at?: string
    }>({
      url: `/api/wechat/tasks/${taskId}`,
      method: 'get',
    })
  },
}
```

- [ ] **Step 7.2: 更新 config.ts**

在 `AppConfig` 接口中添加：

```typescript
// WeChat Official Account
wechat_app_id?: string
wechat_app_secret?: string
wechat_default_author?: string
wechat_default_theme?: string
wechat_default_color?: string
wechat_need_open_comment?: boolean
wechat_only_fans_can_comment?: boolean
```

- [ ] **Step 7.3: 创建 WechatPublishSettings.vue**

```vue
<template>
  <div>
    <RouterLink to="/settings-hub" class="back-link">
      {{ t('settings.backToSettings') }}
    </RouterLink>

    <div class="page-header">
      <div class="page-title">{{ t('wechatPublish.title') }}</div>
      <div class="page-desc">{{ t('wechatPublish.desc') }}</div>
    </div>

    <NCard :title="t('wechatPublish.credentials')">
      <NForm ref="formRef" :model="form" label-placement="left" label-width="180">
        <NFormItem :label="t('wechatPublish.appId')" path="wechat_app_id">
          <NInput v-model:value="form.wechat_app_id" :placeholder="t('wechatPublish.appIdHint')" />
        </NFormItem>
        <NFormItem :label="t('wechatPublish.appSecret')" path="wechat_app_secret">
          <NInput
            v-model:value="form.wechat_app_secret"
            type="password"
            show-password-on="click"
            :placeholder="t('wechatPublish.appSecretHint')"
          />
        </NFormItem>
        <NFormItem :label="t('wechatPublish.defaultAuthor')" path="wechat_default_author">
          <NInput v-model:value="form.wechat_default_author" />
        </NFormItem>
      </NForm>
      <div class="save-btn-row">
        <NButton type="primary" :loading="saving" @click="save">
          {{ t('common.save') }}
        </NButton>
      </div>
    </NCard>

    <NCard :title="t('wechatPublish.publishDefaults')" class="mt-4">
      <NForm ref="formRef2" :model="form" label-placement="left" label-width="180">
        <NFormItem :label="t('wechatPublish.theme')" path="wechat_default_theme">
          <NSelect
            v-model:value="form.wechat_default_theme"
            :options="themeOptions"
            style="width: 200px"
          />
        </NFormItem>
        <NFormItem :label="t('wechatPublish.color')" path="wechat_default_color">
          <NSelect
            v-model:value="form.wechat_default_color"
            :options="colorOptions"
            style="width: 200px"
          />
        </NFormItem>
        <NFormItem :label="t('wechatPublish.needOpenComment')" path="wechat_need_open_comment">
          <NSwitch v-model:value="form.wechat_need_open_comment" />
        </NFormItem>
        <NFormItem :label="t('wechatPublish.onlyFansCanComment')" path="wechat_only_fans_can_comment">
          <NSwitch v-model:value="form.wechat_only_fans_can_comment" />
        </NFormItem>
      </NForm>
      <div class="save-btn-row">
        <NButton type="primary" :loading="saving" @click="save">
          {{ t('common.save') }}
        </NButton>
      </div>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18 } from 'vue-i18n'
import apiConfig from '@/api/config'
import apiWechat from '@/api/wechatPublish'

const { t } = useI18()
const form = ref({
  wechat_app_id: '',
  wechat_app_secret: '',
  wechat_default_author: '',
  wechat_default_theme: 'default',
  wechat_default_color: 'blue',
  wechat_need_open_comment: true,
  wechat_only_fans_can_comment: false,
})
const saving = ref(false)

const themeOptions = [
  { label: 'default', value: 'default' },
  { label: 'grace', value: 'grace' },
  { label: 'simple', value: 'simple' },
  { label: 'modern', value: 'modern' },
]

const colorOptions = [
  { label: 'blue', value: 'blue' },
  { label: 'green', value: 'green' },
  { label: 'vermilion', value: 'vermilion' },
  { label: 'yellow', value: 'yellow' },
  { label: 'purple', value: 'purple' },
  { label: 'sky', value: 'sky' },
  { label: 'rose', value: 'rose' },
  { label: 'olive', value: 'olive' },
  { label: 'black', value: 'black' },
  { label: 'gray', value: 'gray' },
  { label: 'pink', value: 'pink' },
  { label: 'red', value: 'red' },
  { label: 'orange', value: 'orange' },
]

onMounted(async () => {
  try {
    const cfg = await apiWechat.getConfig()
    form.value.wechat_app_id = cfg.wechat_app_id || ''
    form.value.wechat_default_author = cfg.wechat_default_author || ''
    form.value.wechat_default_theme = cfg.wechat_default_theme || 'default'
    form.value.wechat_default_color = cfg.wechat_default_color || 'blue'
    form.value.wechat_need_open_comment = cfg.wechat_need_open_comment ?? true
    form.value.wechat_only_fans_can_comment = cfg.wechat_only_fans_can_comment ?? false
  } catch (e) {
    // ignore
  }
})

async function save() {
  saving.value = true
  try {
    const fullConfig = await apiConfig.get()
    await apiConfig.save({
      ...fullConfig,
      ...form.value,
    })
  } finally {
    saving.value = false
  }
}
</script>
```

- [ ] **Step 7.4: 更新 router — 添加 /settings-hub/wechat 路由**

在 settings 路由 children 中添加：

```typescript
{
  path: '/settings-hub/wechat',
  name: 'settingsWechat',
  meta: { keepAlive: false },
  component: () => import('@/views/settings/WechatPublishSettings.vue'),
},
```

- [ ] **Step 7.5: 更新 AppSider.vue — 添加公众号入口**

在设置分栏的路由列表中，找到 `/settings-hub/ai` 条目，在其后添加：

```vue
<RouterLink to="/settings-hub/wechat" class="nav-item">
  {{ t('nav.settingsWechat') }}
</RouterLink>
```

- [ ] **Step 7.6: 更新 i18n zh.json**

在 `locales/zh.json` 中追加：

```json
"wechatPublish": {
  "title": "微信公众号发布",
  "desc": "配置微信公众号凭证，实现文章一键发布到公众号。",
  "credentials": "公众号凭证",
  "appId": "AppID",
  "appIdHint": "请输入微信公众号 AppID",
  "appSecret": "AppSecret",
  "appSecretHint": "请输入微信公众号 AppSecret",
  "defaultAuthor": "默认作者",
  "publishDefaults": "发布默认设置",
  "theme": "主题",
  "color": "配色",
  "needOpenComment": "开启评论",
  "onlyFansCanComment": "仅粉丝可评论"
},
"nav": {
  "settingsWechat": "公众号发布"
}
```

- [ ] **Step 7.7: 更新 i18n en.json**

同上，添加英文 key。

- [ ] **Step 7.8: 编译前端验证**

Run: `cd frontend-vue && npm run build`
Expected: 无编译错误

- [ ] **Step 7.9: 提交**

```bash
git add frontend-vue/src/views/settings/WechatPublishSettings.vue \
        frontend-vue/src/api/wechatPublish.ts \
        frontend-vue/src/api/config.ts \
        frontend-vue/src/router/index.ts \
        frontend-vue/src/components/layout/AppSider.vue \
        frontend-vue/src/locales/zh.json \
        frontend-vue/src/locales/en.json
git commit -m "feat(frontend): add WeChat Official Account publish settings page"
```

---

## Phase 6: 端到端集成

### Task 8: AiCreation.vue — 文章发布按钮（草稿 + 群发）

**Files:**
- Modify: `frontend-vue/src/views/AiCreation.vue`

- [ ] **Step 8.1: 在 AiCreation.vue 文章 Tab 添加两个发布按钮**

在 `submitArticleTask` 按钮下方添加：

```vue
<!-- 已完成且有 draft_path 时显示发布按钮 -->
<div v-if="latestArticleTask && latestArticleTask.status === 'done' && latestArticleTask.draft_path" class="wechat-publish-row">
  <NButton
    :loading="publishingWechat"
    :disabled="publishingWechat"
    @click="saveToWechatDraft(latestArticleTask)"
  >
    {{ t('aiCreation.saveToWechatDraft') }}
  </NButton>
  <NButton
    type="warning"
    :loading="publishingWechat"
    :disabled="publishingWechat"
    @click="confirmPublishNow(latestArticleTask)"
  >
    {{ t('aiCreation.publishNow') }}
  </NButton>
  <span v-if="wechatPublishTaskId" class="publish-status">
    {{ wechatPublishStatusLabel }}: {{ wechatPublishStatus }}
  </span>
</div>
```

- [ ] **Step 8.2: 添加发布逻辑**

在 `<script setup>` 中添加：

```typescript
const publishingWechat = ref(false)
const wechatPublishTaskId = ref<string | null>(null)
const wechatPublishStatus = ref('')
const wechatPublishMode = ref('') // 'draft' | 'publish'

function getWechatPublishStatusLabel(mode: string) {
  return mode === 'publish'
    ? t('aiCreation.wechatPublishLabelPublish')
    : t('aiCreation.wechatPublishLabelDraft')
}

async function saveToWechatDraft(task: any) {
  publishingWechat.value = true
  wechatPublishMode.value = 'draft'
  try {
    const result = await apiWechat.saveToDraft({
      article_task_id: task.task_id,
      draft_path: task.draft_path,
    })
    wechatPublishTaskId.value = result.task_id
    pollWechatStatus(result.task_id)
  } catch (e: any) {
    window.$message.error(e.message || t('aiCreation.wechatPublishFailed'))
  } finally {
    publishingWechat.value = false
  }
}

async function confirmPublishNow(task: any) {
  // 订阅号群发每月限额4次，显示确认对话框
  const confirmed = await new Promise<boolean>((resolve) => {
    window.$dialog.warning({
      title: t('aiCreation.publishNowConfirmTitle'),
      content: t('aiCreation.publishNowConfirmContent'),
      positiveText: t('aiCreation.publishNowConfirmOk'),
      negativeText: t('aiCreation.publishNowConfirmCancel'),
      onPositiveClick: () => resolve(true),
      onNegativeClick: () => resolve(false),
    })
  })
  if (!confirmed) return

  publishingWechat.value = true
  wechatPublishMode.value = 'publish'
  try {
    const result = await apiWechat.publishNow({
      article_task_id: task.task_id,
      draft_path: task.draft_path,
    })
    wechatPublishTaskId.value = result.task_id
    pollWechatStatus(result.task_id)
  } catch (e: any) {
    window.$message.error(e.message || t('aiCreation.wechatPublishFailed'))
  } finally {
    publishingWechat.value = false
  }
}

async function pollWechatStatus(taskId: string) {
  const poll = async () => {
    const task = await apiWechat.getTaskStatus(taskId)
    wechatPublishStatus.value = task.status
    if (['done', 'error', 'cancelled'].includes(task.status)) {
      if (task.status === 'done') {
        window.$message.success(t('aiCreation.wechatPublishSuccess'))
      } else if (task.status === 'error') {
        window.$message.error(`${t('aiCreation.wechatPublishFailed')}: ${task.error}`)
      }
      return
    }
    setTimeout(poll, 3000)
  }
  poll()
}
```

- [ ] **Step 8.3: 添加 i18n key**

在 zh.json 中追加：

```json
"aiCreation": {
  "saveToWechatDraft": "保存到草稿箱",
  "publishNow": "立即群发",
  "wechatPublishLabelDraft": "草稿箱状态",
  "wechatPublishLabelPublish": "群发状态",
  "publishNowConfirmTitle": "确认立即群发",
  "publishNowConfirmContent": "群发将占用本月群发配额（订阅号每月仅4次）。确认发布？",
  "publishNowConfirmOk": "确认发布",
  "publishNowConfirmCancel": "取消",
  "wechatPublishSuccess": "操作成功",
  "wechatPublishFailed": "操作失败",
  "wechatPublishStatus": "状态"
}
```

- [ ] **Step 8.4: 提交**

```bash
git add frontend-vue/src/views/AiCreation.vue frontend-vue/src/locales/zh.json frontend-vue/src/locales/en.json
git commit -m "feat(frontend): add save-to-draft and publish-now WeChat buttons"
```

---

## Phase 7: 集成验证

### Task 9: 端到端测试

- [ ] **Step 9.1: 运行完整测试套件**

Run: `python -m pytest tests/test_wechat_publisher.py tests/test_wechat_publish_api.py -v`

- [ ] **Step 9.2: 前端编译检查**

Run: `cd frontend-vue && npm run build && npm run type-check`（如果项目配置了 type-check）

- [ ] **Step 9.3: 手动验证流程（两种模式都测）**

1. 启动 monitor_server: `python -m server`
2. 访问 Web UI → 设置中心 → 公众号发布 → 填写 AppID/AppSecret → 保存
3. AI Creation → 提交一篇文章生成任务 → 等待完成
4. **模式 A**：点击"保存到草稿箱" → 等待状态变为 done → 确认微信公众号后台草稿箱出现对应文章
5. **模式 B**：点击"立即群发" → 确认弹窗提示配额限制 → 确认发布 → 等待状态变为 done → 确认公众号出现对应文章
6. 两种模式的 task 在 wechat_publish_tasks 表中 `publish_mode` 字段分别为 `draft` 和 `publish`

---

## Self-Review Checklist

1. **Spec coverage**: 扫描 docs/ai-article-pixelle-video-integration-plan.md 中 wechat 相关需求，每个都能在任务中找到对应实现？
2. **Placeholder scan**: 搜索 plan 文件，确认没有 "TBD"、"TODO"、"实现后期" 等占位符。
3. **Type consistency**: 检查所有函数签名和字段名在任务间的一致性（如 task_id vs taskId、draft_path vs draftPath）。
4. **Integration points**: server/__main__.py 中新增的路由是否在正确的 do_GET/do_POST 分支中？字段名是否与前端 API 调用匹配？
5. **baoyu-wechat-api.ts 对齐**: baoyu 的 API 调用（access_token、草稿、封面图、提交发布）是否在 wechat_publisher.py 中完整覆盖？
6. **双模式设计**: `save_to_draft()` 和 `publish_now()` 是否真正独立（不互相调用）？前端两个按钮是否都有确认流程（群发有配额警告）？
7. **订阅号限额**: 群发按钮是否显示明确的配额提示对话框？
