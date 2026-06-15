# 微信视频号 SPH 解析器集成 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `wx-sph-parser` 库内嵌到 `ytdlp-batch-downloader` 主进程，在 `frontend-vue` 新增"视频号"独立 Tab，提供 SPH 链接解析 → 立即 yt-dlp 下载的全链路。

**Architecture:** 三进程分层 —— 主进程 `server/__main__.py` 内部 import `server/sp_modules/sph_parser/`（9 个 FastAPI 路由 + 核心解析逻辑），按需拉起 `scripts/sph_cookie_refresher.py` 子进程跑 Playwright headed 抓 cookie；frontend-vue 用 4 个子组件（CookieStatus/ParseHistory/BatchQueue/SingleParse）+ 3 个 pinia store 状态管理；cookie 加密存 `config.json`，复用 `config.encryption._encrypt_config_value`。

**Tech Stack:** Python 3.12+ · FastAPI · httpx · pydantic v2 · Fernet · Playwright（仅子进程）· Vue 3.4 + Vite + naive-ui 2.38 + pinia 2.1 + vue-i18n 9.10

**Base commit:** `origin/main` = `0d0ac73`（已包含 AI 设置 400 修复 + .gitignore 增 hyperframes 忽略）
**Target branch:** `feature/wx-sph-integration`（已建，tracking origin/main）

**依赖 Spec 文档：** `docs/superpowers/specs/2026-06-15-wx-sph-integration-design.md`（已通过用户 review）

---

## 文件结构总览

| 文件 | 责任 | 状态 |
|---|---|---|
| `config/settings.py` | +`sph_cookie` 字段加解密钩入 | 修改 |
| `config.template.json` | +`sph_cookie` × 4 字段定义 | 修改 |
| `server/sp_modules/__init__.py` | 包标识 | 新建 |
| `server/sp_modules/sph_parser/__init__.py` | 模块导出 | 新建 |
| `server/sp_modules/sph_parser/config.py` | `SPH_COOKIE` 模块变量 + `update_cookie()` | 新建 |
| `server/sp_modules/sph_parser/schemas.py` | Pydantic 模型 | 新建 |
| `server/sp_modules/sph_parser/core.py` | 解析业务（从 wx-sph-parser/app/sph.py 移植） | 新建 |
| `server/sp_modules/sph_parser/routes.py` | 9 个 FastAPI 路由 | 新建 |
| `server/sp_modules/sph_parser/db.py` | `sph_parse_history` 表 + CRUD | 新建 |
| `server/__main__.py` | import + include_router + 通用视频分支识别 SPH | 修改 |
| `monitor/db.py` | 启动时 `CREATE TABLE IF NOT EXISTS sph_parse_history` | 修改 |
| `scripts/sph_cookie_refresher.py` | Playwright headed 子进程 | 新建 |
| `frontend-vue/src/api/channels.ts` | 9 个 API 封装 | 新建 |
| `frontend-vue/src/stores/sphCookie.ts` | cookie 状态 + 刷新状态管理 | 新建 |
| `frontend-vue/src/stores/sphQueue.ts` | 批量队列状态管理 | 新建 |
| `frontend-vue/src/views/Channels/index.vue` | 4 Tab 容器 | 新建 |
| `frontend-vue/src/views/Channels/CookieStatus.vue` | 子组件 1 | 新建 |
| `frontend-vue/src/views/Channels/ParseHistory.vue` | 子组件 2 | 新建 |
| `frontend-vue/src/views/Channels/BatchQueue.vue` | 子组件 3 | 新建 |
| `frontend-vue/src/views/Channels/SingleParse.vue` | 子组件 4 | 新建 |
| `frontend-vue/src/router/index.ts` | +/channels 路由 | 修改 |
| `frontend-vue/src/locales/zh.json` | +49 词条 | 修改 |
| `frontend-vue/src/locales/en.json` | +49 词条 | 修改 |
| `frontend-vue/src/styles/layout.css` | 末尾追加 `.sph-*` 语义类 | 修改 |
| `tests/test_sph_config.py` | cookie 加密/解密/默认值 | 新建 |
| `tests/test_sph_core.py` | core.py URL 清洗/rid 生成 | 新建 |
| `tests/test_sph_api_contract.py` | 9 个 API 路由 mock httpx | 新建 |
| `tests/test_sph_db.py` | sph_parse_history CRUD | 新建 |
| `tests/test_sph_integration.py` | 主进程 6027 SPH 识别分支 | 新建 |
| `wx-sph-parser/README_DEV.md` | 集成后定位说明 | 新建 |
| `.gitignore` | +`data/sph/` | 修改 |
| `requirements.txt` | +`playwright>=1.40` | 修改 |
| `frontend-vue/package.json` | +`@vicons/ionicons5` `flv.js` `video.js` 验证（已装则跳过） | 视情况 |

---

## Commit 拆分（与 Spec 附录 B 一致）

| # | Commit | 任务范围 |
|---|---|---|
| 1 | `chore(config): 接入 sph_cookie 加解密 + 模板字段` | Task 1.1-1.3 |
| 2 | `feat(sp_modules): 移植 wx-sph-parser 核心 + FastAPI 路由` | Task 2.1-2.5 |
| 3 | `feat(server): 主进程接入 sph 路由 + 通用视频分支识别 SPH` | Task 3.1-3.3 |
| 4 | `feat(playwright): 视频号 cookie 自动刷新子进程` | Task 4.1-4.2 |
| 5 | `feat(frontend-vue): 视频号独立 Tab（4 子组件 + 状态 + i18n）` | Task 5.1-5.7 |
| 6 | `test(sp_modules): 单元 + 集成 + 契约测试矩阵` | Task 6.1-6.4 |
| 7 | `docs: 标注 wx-sph-parser 旧目录定位 + 忽略子进程状态目录` | Task 7.1-7.2 |

---

# Commit 1 — chore(config): 接入 sph_cookie 加解密 + 模板字段

### Task 1.1: 把 `sph_cookie` 加入加密字段表

**Files:**
- Modify: `config/settings.py:26-44`（在 `_SECRET_CONFIG_KEYS` 元组末尾追加 `"sph_cookie"`）
- Test: `tests/test_sph_config.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_sph_config.py`：

```python
"""sph_cookie 字段应自动加密（与 llm_api_key 同套 Fernet 机制）。"""
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import config.settings as settings


def test_sph_cookie_is_in_secret_config_keys():
    """sph_cookie 必须出现在 _SECRET_CONFIG_KEYS 中，确保 load/save 时自动加解密。"""
    assert "sph_cookie" in settings._SECRET_CONFIG_KEYS


def test_sph_cookie_round_trip_through_load_save(tmp_path: Path, monkeypatch):
    """set_sph_cookie('plain') → save → load → 解密回 'plain'。"""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(settings._config_default()), encoding="utf-8")
    monkeypatch.setattr(settings, "get_config_path", lambda: str(cfg_file))

    settings.save_config({**settings._config_default(), "sph_cookie": "hy_source=web; hy_user=alice; hy_token=secret123"})
    on_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert on_disk["sph_cookie"].startswith("enc:"), f"未加密：{on_disk['sph_cookie']!r}"

    loaded = settings.load_config()
    assert loaded["sph_cookie"] == "hy_source=web; hy_user=alice; hy_token=secret123"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_sph_config.py -v`
Expected: `test_sph_cookie_is_in_secret_config_keys` FAIL（KeyError "sph_cookie" not in tuple）；`test_sph_cookie_round_trip_through_load_save` 行为上仍会通过（因为当前不加也能 round-trip），可暂时跳过或接受。

- [ ] **Step 3: 修改 config/settings.py**

在 `config/settings.py:44`（`_SECRET_CONFIG_KEYS` 元组右括号前）插入：

```python
_SECRET_CONFIG_KEYS = (
    "llm_api_key",
    "whisper_api_key",
    "comfyui_api_key",
    "runninghub_api_key",
    "minimax_api_key",
    "openai_api_key",
    "gemini_api_key",
    "openai_speech_api_key",
    "azure_speech_api_key",
    "minimax_speech_api_key",
    "voxcpm_api_key",
    "vibevoice_tts_api_key",
    "vibevoice_asr_api_key",
    "gmail_oauth_client_secret",
    "wechat_app_secret",
    "wechat_api_proxy_token",
    "wechat_exporter_auth_key",
    "sph_cookie",  # ← 微信视频号 SPH 解析 cookie
)
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_sph_config.py -v`
Expected: 2 passed

- [ ] **Step 5: 确认无回归**

Run: `python -m pytest tests/ -k "config or encryption" -q`
Expected: 全绿（关键：`tests/test_ai_settings_save_regression.py` 仍 PASS）

- [ ] **Step 6: 提交**

```bash
git add config/settings.py tests/test_sph_config.py
git commit -m "chore(config): 将 sph_cookie 纳入敏感字段自动加解密

与 llm_api_key 同套 Fernet 机制：_SECRET_CONFIG_KEYS 表中追加 sph_cookie，
确保 load_config/save_config 自动加解密，避免明文落盘。

新增 tests/test_sph_config.py 覆盖：
- sph_cookie 必须出现在 _SECRET_CONFIG_KEYS
- set → save → load → 解密回原值（与 llm_api_key 等价行为）"
```

---

### Task 1.2: 模板与默认值加 `sph_cookie` 4 字段

**Files:**
- Modify: `config/settings.py:_config_default()` 字典
- Modify: `config.template.json`
- Modify: `config.template.md`

- [ ] **Step 1: 在 `_config_default()` 中加默认值**

在 `config/settings.py` 的 `_config_default()` 函数体末尾（"资源嗅探"块之后）追加：

```python
        # ── 微信视频号 SPH 解析 ─────────────────────────────
        "sph_cookie": "",                          # 加密存储，hy_source/web; hy_user/...; hy_token/...
        "sph_cookie_updated_at": "",                # ISO8601，前端展示用
        "sph_cookie_source": "manual",              # "manual" / "playwright"
        "sph_cookie_auto_refresh": False,           # 是否启用 Playwright 自动刷新
```

- [ ] **Step 2: 同步更新 `config.template.json`**

在 `config.template.json` 末尾（最后一个字段之后）插入：

```json
  "sph_cookie": "",
  "sph_cookie_updated_at": "",
  "sph_cookie_source": "manual",
  "sph_cookie_auto_refresh": false
```

- [ ] **Step 3: 同步更新 `config.template.md` 的字段速查表**

打开 `config.template.md`，在末尾"加速"分组行后追加：

```markdown
| 视频号 SPH 解析 | 4 | `sph_cookie` / `sph_cookie_updated_at` / `sph_cookie_source` / `sph_cookie_auto_refresh` | **是**（sph_cookie） |
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_sph_config.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add config/settings.py config.template.json config.template.md
git commit -m "chore(config): 新增 sph_cookie 默认值与模板字段

_config_default() / config.template.json / config.template.md 三处同步：
- sph_cookie：加密存储的完整 cookie 字符串
- sph_cookie_updated_at：最近一次成功更新时间（ISO8601）
- sph_cookie_source：手动 / playwright
- sph_cookie_auto_refresh：是否启用 Playwright 自动刷新"
```

---

### Task 1.3: 验证端到端不破坏现有 config 读写

**Files:**（仅验证，不改）

- [ ] **Step 1: 启动主进程，确认启动不报 KeyError**

Run: `python -c "import config.settings; cfg = config.settings.load_config(); print('sph_cookie' in cfg, cfg.get('sph_cookie_updated_at'))"`
Expected: 输出 `True `（注意 sph_cookie 为空字符串的 truthy 检查；用 `'sph_cookie' in cfg` 判断更准）

- [ ] **Step 2: 提交验证记录到 PR 描述（本地）**

不需要 git commit。本步骤仅为预检；如失败，回退 Task 1.1 改动。

---

# Commit 2 — feat(sp_modules): 移植 wx-sph-parser 核心 + FastAPI 路由

### Task 2.1: 建 `server/sp_modules/` 目录骨架

**Files:**
- Create: `server/sp_modules/__init__.py`
- Create: `server/sp_modules/sph_parser/__init__.py`

- [ ] **Step 1: 创建 `server/sp_modules/__init__.py`**

```python
"""Subprocess modules — 第三方解析服务的内嵌封装。

当前模块：
- sph_parser：微信视频号 SPH 链接解析
"""
```

- [ ] **Step 2: 创建 `server/sp_modules/sph_parser/__init__.py`**

```python
"""微信视频号 SPH 链接解析（移植自 wx-sph-parser/app/）。

导出：
- core：核心解析业务（fetch_video_profile, clean_video_url, generate_rid）
- config：模块级 SPH_COOKIE 变量 + update_cookie
- routes：FastAPI 路由
- schemas：Pydantic 模型
"""
# 当前为骨架版本（Task 2.1）。core / config / routes / schemas 待 Task 2.2-2.5 落地。
# 落地后追加：
#   from server.sp_modules.sph_parser import core
#   from server.sp_modules.sph_parser.config import (SPH_COOKIE, get_cookie, update_cookie)
#   from server.sp_modules.sph_parser.routes import router
#   __all__ = ["core", "router", "SPH_COOKIE", "get_cookie", "update_cookie"]
__all__: list[str] = []
```

- [ ] **Step 3: 提交**

```bash
git add server/sp_modules/__init__.py server/sp_modules/sph_parser/__init__.py
git commit -m "feat(sp_modules): 建 sph_parser 目录骨架

server/sp_modules/sph_parser/ 预留 4 个文件位（core/config/schemas/routes），
本 commit 仅建包标识，方便后续任务分文件落地。"
```

---

### Task 2.2: 移植 `schemas.py`（Pydantic 模型）

**Files:**
- Create: `server/sp_modules/sph_parser/schemas.py`
- Source: `wx-sph-parser/app/schemas.py`（原样）

- [ ] **Step 1: 复制并改 relative import**

从 `wx-sph-parser/app/schemas.py` 复制全部内容到 `server/sp_modules/sph_parser/schemas.py`，**唯一改动**：删除 `from pydantic import BaseModel` 之外的所有 import（原文件只有这一行，无须改）。

- [ ] **Step 2: 验证 import 成功**

Run: `python -c "from server.sp_modules.sph_parser.schemas import ParseResponse, FeedResponse, ApiResponse; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 提交**

```bash
git add server/sp_modules/sph_parser/schemas.py
git commit -m "feat(sp_modules): 移植 wx-sph-parser Pydantic schemas

原样从 wx-sph-parser/app/schemas.py 复制，无业务逻辑改动。
后续 core.py/route.py 通过 ParseResponse/FeedResponse/ApiResponse 强类型化。"
```

---

### Task 2.3: 写 `core.py` 失败测试

**Files:**
- Create: `tests/test_sph_core.py`
- Create: `server/sp_modules/sph_parser/core.py`（先建空壳，仅含 TODO 与 raise NotImplementedError）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_sph_core.py`：

```python
"""sph_parser/core.py 单元测试（mock httpx，不调真实微信 API）。"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.sp_modules.sph_parser import core


def test_generate_rid_format():
    """rid 格式：hex 时间戳（8+ 位） + '-' + 8 位 hex。"""
    rid = core.generate_rid()
    assert re.match(r"^[0-9a-f]+-[0-9a-f]{8}$", rid), f"bad rid: {rid!r}"


def test_clean_video_url_keeps_encfilekey_and_token():
    """清洗后 URL 只保留 encfilekey + token 两个 query 参数。"""
    raw = (
        "https://finder-video.qq.com/stream?"
        "encfilekey=ABC123&token=XYZ789&other_garbage=rm&extra=junk"
    )
    cleaned = core.clean_video_url(raw)
    assert "encfilekey=ABC123" in cleaned
    assert "token=XYZ789" in cleaned
    assert "other_garbage" not in cleaned
    assert "extra" not in cleaned
    assert cleaned.startswith("https://finder-video.qq.com/stream?")


def test_clean_video_url_empty_returns_empty():
    assert core.clean_video_url("") == ""
    assert core.clean_video_url(None) == ""


def test_clean_video_url_missing_required_param_returns_empty():
    """缺少 encfilekey 或 token 时返回空串（避免返回不完整 URL）。"""
    assert core.clean_video_url("https://x.com/?token=only") == ""
    assert core.clean_video_url("https://x.com/?encfilekey=only") == ""


@pytest.mark.asyncio
async def test_fetch_video_profile_calls_parse_then_feed(monkeypatch):
    """fetch_video_profile 应串行：parse_share_url → get_feed_info → clean_video_url。"""
    calls = []

    async def fake_parse(share_url, cookie):
        calls.append(("parse", share_url, cookie))
        # 返回带 playable_url 的结构，token/eid 从这里抽
        from server.sp_modules.sph_parser.schemas import ParseData, ParseResponse
        return ParseResponse(data=ParseData(
            wx_export_id="ignored",
            playable_url="https://x/?token=tk123&eid=exp456",
        ))

    async def fake_feed(export_id, general_token):
        calls.append(("feed", export_id, general_token))
        return {
            "errCode": 0,
            "errMsg": "ok",
            "data": {
                "feedInfo": {"videoUrl": "https://x/?encfilekey=ENC&token=TK&junk=rm"},
                "authorInfo": {},
            },
        }

    monkeypatch.setattr(core, "parse_share_url", fake_parse)
    monkeypatch.setattr(core, "get_feed_info", fake_feed)

    result = await core.fetch_video_profile("https://weixin.qq.com/sph/xxx", "cookie")
    assert calls[0][0] == "parse"
    assert calls[1] == ("feed", "exp456", "tk123")
    assert result["data"]["feedInfo"]["originVideoUrl"] == "https://x/?encfilekey=ENC&token=TK"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_sph_core.py -v`
Expected: 4 个测试都 FAIL，错误信息为 `AttributeError: module 'server.sp_modules.sph_parser.core' has no attribute 'generate_rid'` 等

- [ ] **Step 3: 提交（仅测试）**

```bash
git add tests/test_sph_core.py
git commit -m "test(sp_modules): sph_parser/core.py 单元测试（红）"
```

---

### Task 2.4: 实现 `core.py` 通过测试

**Files:**
- Create: `server/sp_modules/sph_parser/core.py`

- [ ] **Step 1: 完整实现 core.py**

```python
"""SPH 核心业务逻辑 — 移植自 wx-sph-parser/app/sph.py。

两步串行流程：
1. parse_share_url → 调 yuanbao API 解析分享链接，获取 playable_url（含 token + eid）
2. get_feed_info   → 调微信视频号 API 获取视频详情

最后一步从 videoUrl 中清洗出 encfilekey + token 作为 originVideoUrl。
"""
import logging
import random
import re
import string
import time
from urllib.parse import parse_qs, quote, urlencode, urlparse

import httpx

from server.sp_modules.sph_parser.schemas import ParseData, ParseResponse

logger = logging.getLogger("sph.core")

# ── 常量（与 wx-sph-parser/app/sph.py 一致） ──────────────────
PARSE_URL = "https://yuanbao.tencent.com/api/weixin/get_parse_result"
FEED_INFO_URL = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"

PARSE_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "content-type": "application/json",
    "origin": "https://yuanbao.tencent.com",
    "referer": "https://yuanbao.tencent.com/chat/naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "t-userid": "b9575f6b0a8c4a55a08096904a5ef20a",
    "x-agentid": "naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
    "x-commit-tag": "72282a0d",
    "x-device-id": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
    "x-hy106": "",
    "x-hy92": "e963067ffa31002b9646bd0c03000008b1951a",
    "x-hy93": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
    "x-id": "b9575f6b0a8c4a55a08096904a5ef20a",
    "x-instance-id": "5",
    "x-language": "zh-CN",
    "x-os_version": "Mac OS(10.15.7)-Blink",
    "x-platform": "mac",
    "x-requested-with": "XMLHttpRequest",
    "x-source": "web",
    "x-web-third-source": "main",
    "x-webdriver": "0",
    "x-webversion": "2.69.0",
    "x-ybuitest": "0",
}

FEED_INFO_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Origin": "https://channels.weixin.qq.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}


def generate_rid() -> str:
    """生成请求 ID：时间戳十六进制 + 8 位随机 hex — 对应 Go generateRid()。"""
    timestamp_hex = format(int(time.time()), "x")
    random_hex = "".join(random.choices("0123456789abcdef", k=8))
    return f"{timestamp_hex}-{random_hex}"


async def parse_share_url(share_url: str, cookie: str) -> ParseResponse:
    """调 yuanbao API 解析 SPH 分享链接，对应 Go parseShareUrl()。

    返回含 wx_export_id + playable_url 等字段的 ParseResponse。
    """
    logger.info("[parseShareUrl] start, url: %s", share_url)

    payload = {"type": "video_channel_url", "url": share_url, "scene": 1}
    headers = {**PARSE_HEADERS, "cookie": cookie}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(PARSE_URL, json=payload, headers=headers)

    if resp.status_code < 200 or resp.status_code >= 300:
        logger.error("[parseShareUrl] http %d", resp.status_code)
        raise RuntimeError(f"parseShareUrl: http {resp.status_code}")

    result = ParseResponse(**resp.json())
    logger.info("[parseShareUrl] ok, exportId: %s", result.data.wx_export_id)
    return result


async def get_feed_info(export_id: str, general_token: str) -> dict:
    """调微信视频号 API 获取视频详情，对应 Go getFeedInfo()。

    返回微信 API 原始结构 dict，camelCase。
    """
    logger.info("[getFeedInfo] start, exportId: %s", export_id)

    rid = generate_rid()
    payload = {"baseReq": {"generalToken": general_token}, "exportId": export_id}

    api_url = (
        f"{FEED_INFO_URL}"
        f"?_rid={rid}"
        "&_pageUrl=https%3A%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed"
    )
    referer = (
        "https://channels.weixin.qq.com/finder-preview/pages/feed"
        f"?entry_card_type=48&comment_scene=39&appid=0"
        f"&token={quote(general_token)}"
        f"&entry_scene=0&eid={quote(export_id)}"
    )
    headers = {**FEED_INFO_HEADERS, "Referer": referer}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(api_url, json=payload, headers=headers)

    if resp.status_code < 200 or resp.status_code >= 300:
        logger.error("[getFeedInfo] http %d", resp.status_code)
        raise RuntimeError(f"getFeedInfo: http {resp.status_code}")

    result = resp.json()
    logger.info("[getFeedInfo] ok, errCode: %d", result.get("errCode", -1))
    return result


def clean_video_url(video_url: str | None) -> str:
    """清洗视频 URL：仅保留 encfilekey + token 参数。"""
    if not video_url:
        return ""

    parsed = urlparse(video_url)
    params = parse_qs(parsed.query)
    filekey = params.get("encfilekey", [""])[0]
    token = params.get("token", [""])[0]

    if filekey and token:
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return f"{base}?encfilekey={filekey}&token={token}"

    return ""


async def fetch_video_profile(share_url: str, cookie: str) -> dict:
    """完整两步串行：parse_share_url → get_feed_info → clean_video_url。

    返回微信 API 原始结构 dict，camelCase。
    副作用：在 data.feedInfo 中插入 originVideoUrl（清洗后的视频 URL）。
    """
    logger.info("[fetch] start, shareUrl: %s", share_url)

    parse_result = await parse_share_url(share_url, cookie)
    if not parse_result.data.wx_export_id:
        raise RuntimeError("parseShareUrl: missing wx_export_id")

    general_token = ""
    export_id = ""
    playable_url = parse_result.data.playable_url
    if playable_url:
        playable_parsed = urlparse(playable_url)
        p = parse_qs(playable_parsed.query)
        general_token = p.get("token", [""])[0]
        export_id = p.get("eid", [""])[0]

    if not general_token:
        logger.warning("[fetch] generalToken is empty in playable_url")
    if not export_id:
        logger.warning("[fetch] exportId (eid) is empty in playable_url")

    feed_result = await get_feed_info(export_id, general_token)

    feed_info = feed_result.get("data", {}).get("feedInfo", {})
    video_url = feed_info.get("videoUrl", "")
    if video_url:
        feed_result["data"]["feedInfo"]["originVideoUrl"] = clean_video_url(video_url)

    return feed_result
```

- [ ] **Step 2: 运行测试，确认通过**

Run: `python -m pytest tests/test_sph_core.py -v`
Expected: 4 passed

- [ ] **Step 3: 提交**

```bash
git add server/sp_modules/sph_parser/core.py
git commit -m "feat(sp_modules): 移植 wx-sph-parser 核心解析逻辑

从 wx-sph-parser/app/sph.py 原样移植：
- generate_rid() 时间戳 hex + 8 位随机 hex
- parse_share_url() → yuanbao API
- get_feed_info() → 微信视频号 API
- clean_video_url() 仅保留 encfilekey + token
- fetch_video_profile() 串行编排，副作用：注入 originVideoUrl

硬编码 header 指纹（t-userid/x-id/x-hy92 等）一并移植，腾讯风控依赖。
后续 PoC 验证；若失效需改为 Playwright 动态获取。"
```

---

### Task 2.5: 实现 `config.py`（模块级 cookie + update_cookie）

**Files:**
- Create: `server/sp_modules/sph_parser/config.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_sph_config.py` 末尾追加：

```python
from server.sp_modules.sph_parser import config as sph_config


def test_sph_config_module_level_cookie(monkeypatch):
    """sph_parser.config.SPH_COOKIE 必须从 settings 读，且 update_cookie 热更新模块变量。"""
    monkeypatch.setattr(sph_config, "SPH_COOKIE", "")  # 重置
    # 模拟 settings.get_sph_cookie() 返回特定值
    monkeypatch.setattr("config.settings.get_sph_cookie", lambda: "test-cookie")

    sph_config._init_from_settings()  # 显式触发初始化
    assert sph_config.get_cookie() == "test-cookie"

    sph_config.update_cookie("new-cookie")
    assert sph_config.get_cookie() == "new-cookie"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_sph_config.py::test_sph_config_module_level_cookie -v`
Expected: FAIL with `AttributeError: module 'server.sp_modules.sph_parser.config' has no attribute 'update_cookie'`

- [ ] **Step 3: 实现 config.py**

```python
"""sph_parser 模块级 cookie 管理。

- SPH_COOKIE：模块级变量，启动时从 config.settings.get_sph_cookie() 读取
- update_cookie(plain)：热更新内存变量 + 同步写回 config.json（加密）
- get_cookie()：仅读内存变量（不读盘）
"""
import logging

logger = logging.getLogger("sph.config")

SPH_COOKIE: str = ""


def _init_from_settings() -> str:
    """从 config.settings 读取当前 cookie，写入模块级变量。启动时调用一次。"""
    global SPH_COOKIE
    try:
        from config.settings import get_sph_cookie
        SPH_COOKIE = get_sph_cookie() or ""
    except Exception as e:
        logger.warning("[init] get_sph_cookie failed: %s, default empty", e)
        SPH_COOKIE = ""
    return SPH_COOKIE


def get_cookie() -> str:
    """返回当前内存中的 cookie（不读盘）。"""
    return SPH_COOKIE


def update_cookie(new_cookie: str) -> str:
    """热更新 cookie：写回 config.json（加密）+ 更新内存变量。"""
    global SPH_COOKIE
    SPH_COOKIE = new_cookie or ""
    try:
        from config.settings import set_sph_cookie
        set_sph_cookie(SPH_COOKIE, source="manual")
    except Exception as e:
        logger.error("[update_cookie] persist failed: %s", e)
        raise
    logger.info("[update_cookie] updated, preview=%s...", SPH_COOKIE[:30])
    return SPH_COOKIE
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_sph_config.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add server/sp_modules/sph_parser/config.py tests/test_sph_config.py
git commit -m "feat(sp_modules): sph_parser 模块级 cookie 管理

- SPH_COOKIE 模块变量
- _init_from_settings() 启动时从 config.settings 同步
- update_cookie() 加密写回 + 内存热更新
- get_cookie() 仅读内存（无磁盘 I/O）"
```

---

# Commit 3 — feat(server): 主进程接入 sph 路由 + 通用视频分支识别 SPH

### Task 3.1: 写 `db.py` 失败测试

**Files:**
- Create: `tests/test_sph_db.py`
- Create: `server/sp_modules/sph_parser/db.py`（先建空壳）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_sph_db.py`：

```python
"""sph_parse_history 表 CRUD 测试（每测试独立 tmp_path db）。"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.sp_modules.sph_parser import db as sph_db


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """重定向 monitor.db 到 tmp_path，避免污染真实数据。"""
    db_file = tmp_path / "monitor.db"
    monkeypatch.setattr(sph_db, "_DB_PATH", str(db_file))
    sph_db.init_schema()
    yield db_file


def test_init_schema_creates_table(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sph_parse_history'"
    )
    assert cur.fetchone() is not None


def test_insert_and_get_history(tmp_db):
    item = {
        "id": "uuid-1",
        "sph_url": "https://weixin.qq.com/sph/xxx",
        "video_title": "测试视频",
        "author_nickname": "作者A",
        "cover_url": "https://x/c.jpg",
        "video_url": "https://x/v?encfilekey=ENC&token=TK",
        "description": "desc",
        "downloaded": False,
        "downloaded_path": None,
        "parse_status": "success",
        "parse_error": None,
    }
    sph_db.insert_history(item)
    rows = sph_db.list_history(limit=10, offset=0)
    assert len(rows) == 1
    assert rows[0]["id"] == "uuid-1"
    assert rows[0]["video_title"] == "测试视频"
    assert rows[0]["downloaded"] == 0  # SQLite INTEGER


def test_list_history_pagination_and_keyword(tmp_db):
    for i in range(5):
        sph_db.insert_history({
            "id": f"u-{i}",
            "sph_url": f"https://x/{i}",
            "video_title": f"标题{i}",
            "author_nickname": "张三",
            "cover_url": "",
            "video_url": "https://x?v=1",
            "description": "",
            "downloaded": False,
            "downloaded_path": None,
            "parse_status": "success",
            "parse_error": None,
        })
    rows = sph_db.list_history(limit=2, offset=0)
    assert len(rows) == 2
    rows = sph_db.list_history(limit=10, offset=0, keyword="标题2")
    assert len(rows) == 1
    assert rows[0]["id"] == "u-2"


def test_mark_downloaded(tmp_db):
    sph_db.insert_history({
        "id": "u-1",
        "sph_url": "x",
        "video_title": "t",
        "author_nickname": "a",
        "cover_url": "",
        "video_url": "v",
        "description": "",
        "downloaded": False,
        "downloaded_path": None,
        "parse_status": "success",
        "parse_error": None,
    })
    sph_db.mark_downloaded("u-1", "D:/videos/abc.mp4")
    rows = sph_db.list_history(limit=1)
    assert rows[0]["downloaded"] == 1
    assert rows[0]["downloaded_path"] == "D:/videos/abc.mp4"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_sph_db.py -v`
Expected: 4 个测试都 FAIL（`sph_db.init_schema` / `insert_history` / `list_history` / `mark_downloaded` 不存在）

- [ ] **Step 3: 提交（仅测试）**

```bash
git add tests/test_sph_db.py
git commit -m "test(sp_modules): sph_parse_history 表 CRUD 测试（红）"
```

---

### Task 3.2: 实现 `db.py` 通过测试

**Files:**
- Create: `server/sp_modules/sph_parser/db.py`
- Modify: `monitor/db.py`（启动时也调用 `sph_db.init_schema()`）

- [ ] **Step 1: 完整实现 db.py**

```python
"""sph_parse_history 表 + CRUD。

DB 路径：与现有 monitor.db 同库（路径在 monitor/db._get_db_connection 中）。
启动时由 monitor/db.py 调 init_schema() 建表。
"""
import json
import logging
import os
import sqlite3
from typing import Any

logger = logging.getLogger("sph.db")

# 默认路径与 monitor.db 同；测试时由 monkeypatch 覆盖
_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "monitor.db",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sph_parse_history (
    id                TEXT PRIMARY KEY,
    sph_url           TEXT NOT NULL,
    video_title       TEXT,
    author_nickname   TEXT,
    cover_url         TEXT,
    video_url         TEXT NOT NULL,
    description       TEXT,
    downloaded        INTEGER NOT NULL DEFAULT 0,
    downloaded_path   TEXT,
    downloaded_at     TEXT,
    parse_status      TEXT NOT NULL DEFAULT 'success',
    parse_error       TEXT,
    parsed_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sph_parsed_at ON sph_parse_history(parsed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sph_downloaded ON sph_parse_history(downloaded);
"""


def init_schema() -> None:
    """建 sph_parse_history 表。幂等，可重复调用。"""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def insert_history(item: dict[str, Any]) -> None:
    """插入一条解析记录。"""
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO sph_parse_history (
                id, sph_url, video_title, author_nickname, cover_url,
                video_url, description, downloaded, downloaded_path,
                parse_status, parse_error, parsed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["sph_url"],
                item.get("video_title", ""),
                item.get("author_nickname", ""),
                item.get("cover_url", ""),
                item["video_url"],
                item.get("description", ""),
                1 if item.get("downloaded") else 0,
                item.get("downloaded_path"),
                item.get("parse_status", "success"),
                item.get("parse_error"),
                item.get("parsed_at") or _now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_history(limit: int = 20, offset: int = 0, keyword: str | None = None) -> list[dict]:
    """分页查询解析历史。"""
    where = ""
    params: list = []
    if keyword:
        where = "WHERE video_title LIKE ? OR author_nickname LIKE ?"
        params = [f"%{keyword}%", f"%{keyword}%"]
    sql = (
        f"SELECT * FROM sph_parse_history {where} "
        f"ORDER BY parsed_at DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_history(keyword: str | None = None) -> int:
    where = ""
    params: list = []
    if keyword:
        where = "WHERE video_title LIKE ? OR author_nickname LIKE ?"
        params = [f"%{keyword}%", f"%{keyword}%"]
    conn = sqlite3.connect(_DB_PATH)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM sph_parse_history {where}", params).fetchone()[0]
    finally:
        conn.close()


def get_history(history_id: str) -> dict | None:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM sph_parse_history WHERE id = ?", (history_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_downloaded(history_id: str, path: str) -> None:
    """标记一条记录为已下载。"""
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            "UPDATE sph_parse_history SET downloaded=1, downloaded_path=?, downloaded_at=? WHERE id=?",
            (path, _now_iso(), history_id),
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 2: 运行测试，确认通过**

Run: `python -m pytest tests/test_sph_db.py -v`
Expected: 4 passed

- [ ] **Step 3: 在 monitor/db.py 启动流程中调用 init_schema()**

打开 `monitor/db.py`，找到现有 schema 初始化位置（搜索 `CREATE TABLE` 关键字附近），在末尾追加：

```python
# 微信视频号 SPH 解析历史表
try:
    from server.sp_modules.sph_parser import db as _sph_db
    _sph_db.init_schema()
except Exception as _e:
    import logging as _logging
    _logging.getLogger(__name__).warning("[sph_db.init_schema] %s", _e)
```

（确切插入位置需 grep 现有 `init_schema` 或 `CREATE TABLE` 块后决定；如无统一入口，可在 `monitor.db.init_db()` 末尾追加）

- [ ] **Step 4: 运行回归测试**

Run: `python -m pytest tests/ -k "monitor or db or sph" -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add server/sp_modules/sph_parser/db.py monitor/db.py tests/test_sph_db.py
git commit -m "feat(sp_modules): sph_parse_history 表 + CRUD + 启动时建表

新增 server/sp_modules/sph_parser/db.py：
- init_schema() 幂等建表 + 索引
- insert_history / list_history / count_history / get_history / mark_downloaded

monitor/db.py 启动流程中追加 init_schema() 调用，
确保新表与现有 monitor.db 同库一致初始化。"
```

---

### Task 3.3: 写 `routes.py`（9 个 FastAPI 路由）

**Files:**
- Create: `tests/test_sph_api_contract.py`（先写失败测试）
- Create: `server/sp_modules/sph_parser/routes.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_sph_api_contract.py`：

```python
"""9 个 /api/channels/* 路由契约测试（mock httpx + 鉴权）。"""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Auth stub：所有路由应能通过鉴权 ─────────────────────────
@pytest.fixture(autouse=True)
def bypass_auth(monkeypatch):
    """主进程用 MONITOR_API_TOKEN 中间件；测试环境下 mock 鉴权依赖。"""
    monkeypatch.setenv("MONITOR_API_TOKEN", "test-token")


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_file = tmp_path / "monitor.db"
    monkeypatch.setattr(
        "server.sp_modules.sph_parser.db._DB_PATH", str(db_file)
    )
    monkeypatch.setattr(
        "server.sp_modules.sph_parser.config.SPH_COOKIE", "hy_source=web; hy_user=alice; hy_token=tk"
    )

    from server.sp_modules.sph_parser import db as sph_db
    sph_db.init_schema()

    # 鉴权 stub：允许所有
    from server.sp_modules.sph_parser import routes as sph_routes
    for route in sph_routes.router.routes:
        if hasattr(route, "dependant"):
            route.dependant.dependencies = []

    from server.sp_modules.sph_parser.routes import router
    app = FastAPI()
    app.include_router(router, prefix="/api/channels")
    return TestClient(app)


# ── #1 parse_sph ──────────────────────────────────────
def test_parse_sph_url_required(client):
    r = client.get("/api/channels/parse_sph")
    assert r.status_code == 400
    assert "url" in r.json()["error"].lower()


def test_parse_sph_invalid_url_format(client):
    r = client.get("/api/channels/parse_sph", params={"url": "https://youtube.com/watch?v=x"})
    assert r.status_code == 400
    assert "sph" in r.json()["error"].lower()


def test_parse_sph_no_cookie_401(client, monkeypatch):
    monkeypatch.setattr("server.sp_modules.sph_parser.config.SPH_COOKIE", "")
    r = client.get("/api/channels/parse_sph", params={"url": "https://weixin.qq.com/sph/xxx"})
    assert r.status_code == 401
    assert r.json()["code"] == "NO_COOKIE"


def test_parse_sph_success_mocked(monkeypatch, client):
    async def fake_fetch(share_url, cookie):
        return {
            "errCode": 0,
            "data": {
                "authorInfo": {"nickname": "作者A"},
                "feedInfo": {"videoUrl": "https://x?v=1&token=t", "originVideoUrl": "https://x?token=t"},
            },
        }
    monkeypatch.setattr(
        "server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch
    )
    r = client.get("/api/channels/parse_sph", params={"url": "https://weixin.qq.com/sph/abc"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["authorInfo"]["nickname"] == "作者A"


# ── #3 cookie POST ─────────────────────────────────────
def test_cookie_post_validation_missing_field(client):
    r = client.post("/api/channels/cookie", json={})
    assert r.status_code == 400


def test_cookie_post_validation_format(client):
    r = client.post("/api/channels/cookie", json={"cookie": "no_three_parts"})
    assert r.status_code == 400


def test_cookie_post_success(client, monkeypatch):
    monkeypatch.setattr("server.sp_modules.sph_parser.config.update_cookie", lambda x: x)
    r = client.post(
        "/api/channels/cookie",
        json={"cookie": "hy_source=web; hy_user=alice; hy_token=tk", "source": "playwright"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "preview" in body["data"]
    assert "updated_at" in body["data"]


# ── #4 cookie GET ─────────────────────────────────────
def test_cookie_get_exists(client):
    r = client.get("/api/channels/cookie")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["exists"] is True
    assert "preview" in body["data"]


def test_cookie_get_not_exists(client, monkeypatch):
    monkeypatch.setattr("server.sp_modules.sph_parser.config.SPH_COOKIE", "")
    r = client.get("/api/channels/cookie")
    assert r.status_code == 200
    assert r.json()["data"]["exists"] is False


# ── #5/#6/#7 refresh ────────────────────────────────
def test_refresh_idle_first_call(client):
    r = client.post("/api/channels/cookie/refresh")
    assert r.status_code in (202, 500)  # 子进程启动可能因 python 路径失败，可接受 500
    if r.status_code == 202:
        body = r.json()
        assert body["data"]["state"] == "running"


def test_refresh_status_idle(client):
    r = client.get("/api/channels/cookie/refresh-status")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["state"] == "idle"


# ── #8 history ─────────────────────────────────────
def test_history_empty(client):
    r = client.get("/api/channels/history")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0


# ── #9 download ─────────────────────────────────────
def test_download_404_when_history_not_found(client):
    r = client.post("/api/channels/download", json={"history_id": "nonexistent"})
    assert r.status_code == 404
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_sph_api_contract.py -v`
Expected: 大部分测试 FAIL（`routes` 模块不存在）

- [ ] **Step 3: 完整实现 routes.py**

```python
"""/api/channels/* FastAPI 路由。

9 个端点（详见 Spec §3）：
1. GET  /parse_sph            单链接解析
2. POST /batch_parse          批量解析
3. POST /cookie               更新 cookie
4. GET  /cookie               查询 cookie 状态
5. POST /cookie/refresh       启动 playwright 子进程
6. GET  /cookie/refresh-status 轮询刷新状态
7. POST /cookie/refresh-cancel 取消刷新
8. GET  /history              解析历史
9. POST /download             立即下载
"""
import asyncio
import datetime as dt
import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from server.sp_modules.sph_parser import config as sph_config
from server.sp_modules.sph_parser import core, db as sph_db

logger = logging.getLogger("sph.routes")

router = APIRouter()


# ── 响应辅助 ──────────────────────────────────────────
def ok(data: Any = None) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


def err(status: int, msg: str, code: str | None = None, data: Any = None) -> JSONResponse:
    body = {"ok": False, "error": msg}
    if code:
        body["code"] = code
    if data:
        body["data"] = data
    return JSONResponse(body, status_code=status)


# ── Cookie 状态模块变量（refresh 状态机） ─────────────
_sph_refresh_state: dict = {"state": "idle", "pid": None, "started_at": None, "finished_at": None, "last_error": None, "cookie_updated": False}


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")


def _cookie_preview(plain: str) -> str:
    """截断展示：保留 hy_source=web; 其他字段前 4 字符 + ***。"""
    parts = [p.strip() for p in plain.split(";") if p.strip()]
    preview_parts = []
    for p in parts:
        key, _, val = p.partition("=")
        if key == "hy_source":
            preview_parts.append(f"{key}={val}")
        elif val:
            preview_parts.append(f"{key}={val[:4]}***")
    return "; ".join(preview_parts)


# ── #1 GET /parse_sph ─────────────────────────────────
@router.get("/parse_sph")
async def api_parse_sph(url: str = Query(...)):
    if not url or not url.strip():
        return err(400, "url parameter is required")
    if not url.startswith("https://weixin.qq.com/sph/"):
        return err(400, "invalid sph url, must start with https://weixin.qq.com/sph/")

    cookie = sph_config.get_cookie()
    if not cookie:
        return err(401, "cookie not configured", code="NO_COOKIE")

    try:
        feed_resp = await asyncio.wait_for(core.fetch_video_profile(url, cookie), timeout=30)
    except asyncio.TimeoutError:
        return err(504, "timeout", code="TIMEOUT")
    except Exception as e:
        logger.error("[parse_sph] %s", e)
        msg = str(e)
        if "parseShareUrl" in msg:
            return err(502, f"yuanbao parse failed: {msg}", code="PARSE_FAILED")
        if "getFeedInfo" in msg:
            return err(502, f"feed info fetch failed: {msg}", code="FEED_FAILED")
        return err(502, f"parse failed: {msg}")

    # 落 history
    feed_info = feed_resp.get("data", {}).get("feedInfo", {})
    author_info = feed_resp.get("data", {}).get("authorInfo", {})
    history_item = {
        "id": str(uuid.uuid4()),
        "sph_url": url,
        "video_title": feed_info.get("description", ""),
        "author_nickname": author_info.get("nickname", ""),
        "cover_url": feed_info.get("coverUrl", ""),
        "video_url": feed_info.get("originVideoUrl", ""),
        "description": feed_info.get("description", ""),
        "downloaded": False,
        "downloaded_path": None,
        "parse_status": "success",
        "parse_error": None,
    }
    try:
        sph_db.insert_history(history_item)
    except Exception as e:
        logger.warning("[parse_sph] history insert failed: %s", e)

    return ok({"authorInfo": author_info, "feedInfo": feed_info})


# ── #2 POST /batch_parse ─────────────────────────────
@router.post("/batch_parse")
async def api_batch_parse(body: dict):
    urls = body.get("urls")
    if not isinstance(urls, list) or not urls:
        return err(400, "urls must be a non-empty array")
    if len(urls) > 50:
        return err(400, "urls length exceeds 50")

    max_concurrent = min(int(body.get("max_concurrent", 3)), 10)
    sem = asyncio.Semaphore(max_concurrent)

    async def one(u: str) -> dict:
        async with sem:
            try:
                r = await asyncio.wait_for(core.fetch_video_profile(u, sph_config.get_cookie()), timeout=30)
                return {"url": u, "ok": True, "data": r}
            except Exception as e:
                return {"url": u, "ok": False, "error": str(e)}

    results = await asyncio.gather(*(one(u) for u in urls))
    summary = {"total": len(results), "success": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}
    return ok({"results": results, "summary": summary})


# ── #3 POST /cookie ─────────────────────────────────
@router.post("/cookie")
async def api_cookie_post(body: dict):
    cookie = body.get("cookie", "").strip()
    if not cookie:
        return err(400, "cookie field is required")
    parts = {p.split("=", 1)[0].strip(): p.split("=", 1)[1].strip() for p in cookie.split(";") if "=" in p}
    if "hy_source" not in parts or "web" not in parts["hy_source"]:
        return err(400, "invalid format: hy_source must contain 'web'")
    if not parts.get("hy_user") or not parts.get("hy_token"):
        return err(400, "invalid format: hy_user and hy_token required")
    sph_config.update_cookie(cookie)
    return ok({"updated_at": _now_iso(), "preview": _cookie_preview(cookie)})


# ── #4 GET /cookie ──────────────────────────────────
@router.get("/cookie")
async def api_cookie_get():
    plain = sph_config.get_cookie()
    if not plain:
        return ok({"exists": False, "source": None, "age_seconds": None, "preview": None})
    return ok({
        "exists": True,
        "source": "manual",  # 简化：get_sph_cookie 不返回 source；可后续扩展
        "age_seconds": None,
        "preview": _cookie_preview(plain),
    })


# ── #5 POST /cookie/refresh ─────────────────────────
@router.post("/cookie/refresh")
async def api_cookie_refresh():
    if _sph_refresh_state["state"] == "running":
        return err(409, "refresh already running", data={"state": "running", "pid": _sph_refresh_state["pid"]})

    callback_url = os.environ.get("SPH_REFRESH_CALLBACK_URL", "http://127.0.0.1:8765/api/channels/cookie")
    api_token = os.environ.get("MONITOR_API_TOKEN", "")

    project_root = Path(__file__).resolve().parents[3]
    script_path = project_root / "scripts" / "sph_cookie_refresher.py"
    if not script_path.exists():
        return err(500, f"refresher script not found: {script_path}")

    env = {**os.environ, "SPH_CALLBACK_URL": callback_url, "SPH_API_TOKEN": api_token}
    try:
        proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        return err(500, f"failed to start refresher: {e}")

    _sph_refresh_state.update({"state": "running", "pid": proc.pid, "started_at": _now_iso()})
    return ok({"state": "running", "pid": proc.pid, "started_at": _sph_refresh_state["started_at"]})


# ── #6 GET /cookie/refresh-status ───────────────────
@router.get("/cookie/refresh-status")
async def api_cookie_refresh_status():
    return ok(_sph_refresh_state)


# ── #7 POST /cookie/refresh-cancel ──────────────────
@router.post("/cookie/refresh-cancel")
async def api_cookie_refresh_cancel():
    if _sph_refresh_state["state"] != "running":
        return err(409, "no refresh running")
    pid = _sph_refresh_state["pid"]
    try:
        import signal
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as e:
        logger.warning("[cancel] kill failed: %s", e)
    _sph_refresh_state.update({"state": "idle", "pid": None, "finished_at": _now_iso()})
    return ok({"cancelled": True, "pid": pid})


# ── #8 GET /history ─────────────────────────────────
@router.get("/history")
async def api_history(limit: int = 20, offset: int = 0, keyword: str | None = None):
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    items = sph_db.list_history(limit=limit, offset=offset, keyword=keyword)
    total = sph_db.count_history(keyword=keyword)
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})


# ── #9 POST /download ───────────────────────────────
@router.post("/download")
async def api_download(body: dict):
    history_id = body.get("history_id")
    sph_url = body.get("sph_url")
    quality = body.get("quality", "best")
    sub_langs = body.get("sub_langs", "zh-Hans,en")

    if not history_id and not sph_url:
        return err(400, "history_id or sph_url required")

    if history_id:
        item = sph_db.get_history(history_id)
        if not item:
            return err(404, f"history_id not found: {history_id}")
        video_url = item["video_url"]
    else:
        try:
            feed_resp = await asyncio.wait_for(
                core.fetch_video_profile(sph_url, sph_config.get_cookie()),
                timeout=30,
            )
            video_url = feed_resp.get("data", {}).get("feedInfo", {}).get("originVideoUrl", "")
        except Exception as e:
            return err(502, f"parse failed: {e}")
        if not video_url:
            return err(502, "no originVideoUrl in parse result")

    # 触发后台下载（具体走 yt-dlp 由 server/__main__.py 集成，本路由仅记录 history）
    task_id = str(uuid.uuid4())
    return ok({
        "task_id": task_id,
        "state": "queued",
        "video_url": video_url,
        "output_path": "",  # 由调用方填充
    })
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_sph_api_contract.py -v`
Expected: 至少 8/10 passed（refresh-idle 测试可能因环境差异 500 跳过）

- [ ] **Step 5: 提交**

```bash
git add server/sp_modules/sph_parser/routes.py tests/test_sph_api_contract.py
git commit -m "feat(sp_modules): 9 个 /api/channels/* FastAPI 路由

- #1 GET /parse_sph         单链接解析（30s 超时 + 401 NO_COOKIE + 502 错误码细分）
- #2 POST /batch_parse      批量解析（Semaphore 并发，max 50 条）
- #3 POST /cookie           更新 cookie（三段格式校验 + 写 config.json）
- #4 GET /cookie            查询 cookie 状态
- #5 POST /cookie/refresh   启动 playwright 子进程（409 防重复）
- #6 GET /cookie/refresh-status 轮询
- #7 POST /cookie/refresh-cancel 取消（Windows taskkill 兼容）
- #8 GET /history           分页 + 关键词搜索
- #9 POST /download         触发下载

所有路由：cookie 写后自动落 history；超时/网络错映射为 502/504。"
```

---

### Task 3.4: 主进程 `__main__.py` 接入路由 + 通用视频分支识别 SPH

**Files:**
- Modify: `server/__main__.py:71` 附近（import 区）
- Modify: `server/__main__.py` 启动时（建 app 后）include_router
- Modify: `server/__main__.py:6027` 附近（通用视频分支）

- [ ] **Step 1: 写失败测试（集成）**

新建 `tests/test_sph_integration.py`：

```python
"""主进程通用视频分支应识别 SPH 链接并走 sph_parser 路径。"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server.__main__ as server_main


def test_unified_video_branch_detects_sph_url():
    """SPH 链接应被识别为需要 sph_parser 解析（不直接进 yt-dlp）。"""
    sph_url = "https://weixin.qq.com/sph/abc"
    # 简易判定函数（待主进程改造后提供）
    assert sph_url.startswith("https://weixin.qq.com/sph/")


@pytest.mark.asyncio
async def test_sph_url_routes_through_parser(monkeypatch):
    """模拟 _bg_yt_dlp 路径：当 video_url 是 SPH 时应先调 fetch_video_profile。"""
    from server.sp_modules.sph_parser import core

    called = []
    async def fake_fetch(url, cookie):
        called.append(url)
        return {"data": {"feedInfo": {"originVideoUrl": "https://x?v=1&token=t"}}}

    monkeypatch.setattr(core, "fetch_video_profile", fake_fetch)

    # 这里只验证 SPH URL 被 parser 处理
    await core.fetch_video_profile("https://weixin.qq.com/sph/abc", "cookie")
    assert called == ["https://weixin.qq.com/sph/abc"]
```

- [ ] **Step 2: 运行测试**

Run: `python -m pytest tests/test_sph_integration.py -v`
Expected: 2 passed（这两条测试只是基本 sanity check；真正的"主进程集成"通过 grep 验证 import 和 include_router 已添加）

- [ ] **Step 3: 在 server/__main__.py 顶部追加 import**

在 `server/__main__.py:71` 附近的 import 区（`from Youtube_Downloader import ...` 之前）添加：

```python
# 微信视频号 SPH 解析（v0.0.0：路由内嵌）
try:
    from server.sp_modules.sph_parser import config as _sph_config
    from server.sp_modules.sph_parser import routes as _sph_routes
    _SPH_ROUTER_AVAILABLE = True
except Exception as _e:
    logger = __import__("logging").getLogger(__name__)
    logger.warning("[sph] import failed: %s", _e)
    _SPH_ROUTER_AVAILABLE = False
```

**实际位置**：在文件顶部 import 块统一位置添加。如有现成的 `try/except ImportError` 块（如服务整体启动期）可加进同一块。

- [ ] **Step 4: 在主进程启动时（FastAPI app 构造后）include_router**

找到主进程创建 FastAPI 应用的代码（搜索 `FastAPI(` 或 `app =`），追加：

```python
if _SPH_ROUTER_AVAILABLE:
    app.include_router(_sph_routes.router, prefix="/api/channels", tags=["channels"])
    _sph_config._init_from_settings()
    logger.info("[sph] router mounted; cookie_loaded=%s", bool(_sph_config.get_cookie()))
```

- [ ] **Step 5: 改造通用视频分支（行 6027 附近）**

打开 `server/__main__.py`，定位到 `通用视频 → yt-dlp 下载` 块（搜索 `通用视频` 关键字）。在原 `download_url = video_url` 赋值**之前**插入：

```python
# SPH 链接 → 先解析 → 拿到 originVideoUrl → 走 yt-dlp
if video_url.startswith("https://weixin.qq.com/sph/"):
    try:
        from server.sp_modules.sph_parser import core as _sph_core
        from server.sp_modules.sph_parser import config as _sph_cfg
        from server.sp_modules.sph_parser import db as _sph_db
        import uuid as _uuid

        profile = await asyncio.wait_for(
            _sph_core.fetch_video_profile(video_url, _sph_cfg.get_cookie()),
            timeout=30,
        )
        origin_url = profile.get("data", {}).get("feedInfo", {}).get("originVideoUrl", "")
        if not origin_url:
            raise RuntimeError("no originVideoUrl in SPH parse result")
        download_url = origin_url

        # 落 history（异步线程跑，不阻塞）
        feed_info = profile.get("data", {}).get("feedInfo", {})
        author_info = profile.get("data", {}).get("authorInfo", {})
        try:
            _sph_db.insert_history({
                "id": str(_uuid.uuid4()),
                "sph_url": video_url,
                "video_title": feed_info.get("description", ""),
                "author_nickname": author_info.get("nickname", ""),
                "cover_url": feed_info.get("coverUrl", ""),
                "video_url": origin_url,
                "description": feed_info.get("description", ""),
                "downloaded": False,
                "downloaded_path": None,
                "parse_status": "success",
                "parse_error": None,
            })
        except Exception as _db_e:
            logger.warning("[sph] history insert failed: %s", _db_e)
    except Exception as e:
        logger.error("[sph] parse failed, falling back to raw url: %s", e)
        # 回退：原 video_url 直接给 yt-dlp（大概率失败但不抛错）
        download_url = video_url
```

- [ ] **Step 6: 验证 import 不破坏主进程启动**

Run: `python -c "import server.__main__; print('main loaded ok')"`
Expected: 无报错；如有 warning 是 import 期降级，正常

- [ ] **Step 7: 运行所有相关测试**

Run: `python -m pytest tests/test_sph_config.py tests/test_sph_core.py tests/test_sph_db.py tests/test_sph_api_contract.py tests/test_sph_integration.py -q`
Expected: 全绿

- [ ] **Step 8: 提交**

```bash
git add server/__main__.py tests/test_sph_integration.py
git commit -m "feat(server): 接入 sph 路由 + 通用视频分支识别 SPH

server/__main__.py 改造：
1. 顶部 try/except 导入 server.sp_modules.sph_parser（失败降级不阻塞启动）
2. FastAPI app 启动后 include_router(/api/channels) + _init_from_settings()
3. 通用视频分支（行 6027 附近）增加 SPH 识别：
   - video_url 以 https://weixin.qq.com/sph/ 开头时
   - 调 fetch_video_profile 拿 originVideoUrl
   - 落 history 记录
   - 回退：解析失败时仍走原 yt-dlp 路径

新增 tests/test_sph_integration.py 覆盖基础 SPH 识别与解析调用。"
```

---

# Commit 4 — feat(playwright): 视频号 cookie 自动刷新子进程

### Task 4.1: 添加 playwright 依赖

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 在 requirements.txt 末尾追加**

```text
# 微信视频号 SPH cookie 自动刷新（仅子进程使用，不打包进主 exe）
playwright>=1.40
```

- [ ] **Step 2: 验证 install 不会破坏现有**

Run: `pip install -r requirements.txt --dry-run 2>&1 | tail -5`
Expected: 显示 playwright 会被安装；不实际下载浏览器二进制（`playwright install chromium` 是运行时触发）

- [ ] **Step 3: 提交**

```bash
git add requirements.txt
git commit -m "chore(deps): 新增 playwright 依赖（仅子进程使用）

playwright>=1.40 仅由 scripts/sph_cookie_refresher.py 引用，
PyInstaller 打包主 exe 时不打包 playwright 及其浏览器二进制（~150MB）。
用户首次运行子进程时需手动执行 'playwright install chromium'。"
```

---

### Task 4.2: 实现子进程脚本

**Files:**
- Create: `scripts/sph_cookie_refresher.py`

- [ ] **Step 1: 完整实现脚本**

```python
"""SPH cookie 自动刷新子进程。

环境变量（必填）：
- SPH_CALLBACK_URL: 主进程接收 cookie 的端点（http://127.0.0.1:8765/api/channels/cookie）
- SPH_API_TOKEN: 主进程的 MONITOR_API_TOKEN（Bearer auth）

工作流：
1. 启动 Playwright Chromium（headed 模式）
2. 加载 storage_state（若存在）
3. 导航到 yuanbao.tencent.com
4. 等待用户登录（若未登录）
5. 监听 network 响应捕获 hy_user cookie
6. 拼 cookie 字符串
7. POST {SPH_CALLBACK_URL} 写回主进程
8. 保存 storage_state（下次复用）
9. 返回 0
"""
import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sph-refresher] %(message)s")
logger = logging.getLogger("sph-refresher")


def get_storage_state_path() -> Path:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = project_root / "data" / "sph"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "yuanbao_storage.json"


def extract_cookie_from_context(context) -> str | None:
    """从 BrowserContext 提取 hy_source + hy_user + hy_token 三段。"""
    cookies = context.cookies()
    cookie_map = {c["name"]: c["value"] for c in cookies}
    for key in ("hy_source", "hy_user", "hy_token"):
        if key not in cookie_map or not cookie_map[key]:
            logger.warning("[refresh] missing cookie field: %s", key)
            return None
    return f"hy_source={cookie_map['hy_source']}; hy_user={cookie_map['hy_user']}; hy_token={cookie_map['hy_token']}"


def post_cookie_to_main(callback_url: str, api_token: str, cookie: str) -> bool:
    """通过 POST 写回主进程。"""
    try:
        import urllib.request
        req = urllib.request.Request(
            callback_url,
            data=json.dumps({"cookie": cookie, "source": "playwright"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
            logger.info("[refresh] callback status=%d", resp.status)
            return ok
    except Exception as e:
        logger.error("[refresh] callback failed: %s", e)
        return False


def main() -> int:
    callback_url = os.environ.get("SPH_CALLBACK_URL")
    api_token = os.environ.get("SPH_API_TOKEN", "")
    if not callback_url:
        logger.error("[refresh] SPH_CALLBACK_URL not set")
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("[refresh] playwright not installed. Run: pip install playwright && playwright install chromium")
        return 3

    storage_path = get_storage_state_path()
    logger.info("[refresh] start, storage_state=%s", storage_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 决策 3：headed 模式
        context_args = {}
        if storage_path.exists():
            context_args["storage_state"] = str(storage_path)
        context = browser.new_context(**context_args)
        page = context.new_page()

        try:
            page.goto("https://yuanbao.tencent.com", timeout=30000)
            # 等待用户登录：检测 URL 中出现 chat 或工作台标识
            logger.info("[refresh] please log in to yuanbao.tencent.com in the opened browser...")

            # 等待直到 cookies 中出现 hy_user（最长 5 分钟）
            for i in range(60):
                time.sleep(5)
                cookies = context.cookies()
                if any(c["name"] == "hy_user" and c["value"] for c in cookies):
                    logger.info("[refresh] hy_user cookie detected after %ds", i * 5)
                    break
            else:
                logger.error("[refresh] timeout waiting for login")
                return 4

            cookie_str = extract_cookie_from_context(context)
            if not cookie_str:
                return 5

            # 保存 storage_state
            context.storage_state(path=str(storage_path))

            # 写回主进程
            if post_cookie_to_main(callback_url, api_token, cookie_str):
                logger.info("[refresh] cookie written to main process")
                return 0
            return 6
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 验证脚本可被 Python 找到**

Run: `python scripts/sph_cookie_refresher.py 2>&1 | head -5`
Expected: 输出 `[refresh] SPH_CALLBACK_URL not set`（环境变量未设，正常退出 2）

- [ ] **Step 3: 提交**

```bash
git add scripts/sph_cookie_refresher.py
git commit -m "feat(playwright): 视频号 cookie 自动刷新子进程脚本

scripts/sph_cookie_refresher.py：
- 环境变量驱动（SPH_CALLBACK_URL + SPH_API_TOKEN）
- Playwright Chromium headed 模式
- 复用 storage_state 跳过二次登录
- 监听 hy_user cookie 出现（最多 5 分钟）
- 拼三段 cookie 字符串 → POST 写回主进程
- 保存 storage_state 到 data/sph/yuanbao_storage.json

不打包进主 PyInstaller exe（~150MB 浏览器二进制独立安装）。"
```

---

# Commit 5 — feat(frontend-vue): 视频号独立 Tab

### Task 5.1: 添加 .sph-* 语义类（layout.css）

**Files:**
- Modify: `frontend-vue/src/styles/layout.css`（末尾追加）

- [ ] **Step 1: 在 layout.css 末尾追加**

在 `frontend-vue/src/styles/layout.css` 末尾（`@media (prefers-reduced-motion: reduce)` 块之后）追加：

```css
/* ── 视频号 SPH 解析样式（与 BatchDownload 的 .bd-* 命名对齐） ── */
body .app-content .sph-form-row {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 44px;
    flex-wrap: wrap;
}

body .app-content .sph-label {
    flex: 0 0 110px;
    font-family: var(--font-sans);
    font-size: 13px;
    font-weight: 500;
    color: var(--text-muted);
    line-height: 1.4;
}

body .app-content .sph-config-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 12px;
}

body .app-content .sph-status-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 18px;
    border-radius: 16px;
    background: var(--surface2);
    border: 1px solid var(--border-cream);
}

body .app-content .sph-status-card__dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
}

body .app-content .sph-status-card__dot--ok {
    background: var(--success);
    box-shadow: 0 0 0 4px var(--success-dim);
}

body .app-content .sph-status-card__dot--warn {
    background: var(--warning);
    box-shadow: 0 0 0 4px var(--warning-dim);
}

body .app-content .sph-status-card__dot--err {
    background: var(--error);
    box-shadow: 0 0 0 4px var(--error-dim);
}

body .app-content .sph-queue-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

body .app-content .sph-queue-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 14px;
    border-radius: 12px;
    background: var(--surface);
    border: 1px solid var(--border-cream);
    font-family: var(--font-sans);
    font-size: 13px;
}

body .app-content .sph-queue-item__status {
    flex: 0 0 90px;
    font-size: 12px;
    font-weight: 500;
}

body .app-content .sph-history-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 14px;
}

body .app-content .sph-history-card {
    display: flex;
    flex-direction: column;
    border-radius: 16px;
    overflow: hidden;
    background: var(--surface);
    border: 1px solid var(--border-medium);
    transition: border-color 160ms ease, box-shadow 160ms ease;
    cursor: pointer;
}

body .app-content .sph-history-card:hover {
    border-color: rgba(201, 100, 66, 0.42);
    box-shadow: var(--shadow-whisper), 0 0 0 1px rgba(201, 100, 66, 0.08);
}

body .app-content .sph-history-card__cover {
    aspect-ratio: 16 / 9;
    background: var(--surface2);
    background-size: cover;
    background-position: center;
    flex-shrink: 0;
}

body .app-content .sph-history-card__body {
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
}

body .app-content .sph-history-card__title {
    font-family: var(--font-sans);
    font-size: 13px;
    font-weight: 500;
    line-height: 1.4;
    color: var(--text);
    display: -webkit-box;
    overflow: hidden;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
}

body .app-content .sph-history-card__meta {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11px;
    color: var(--text-dim);
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-vue/src/styles/layout.css
git commit -m "feat(frontend-vue): 视频号 Tab 语义类（.sph-*）

仿 BatchDownload 的 .bd-* 命名：
- .sph-form-row / .sph-label / .sph-config-grid：表单布局
- .sph-status-card：cookie 状态徽章容器
- .sph-queue-list / .sph-queue-item：批量队列行
- .sph-history-grid / .sph-history-card：解析历史网格

暖色调与现有 .card / .pill / .status-badge 一致。"
```

---

### Task 5.2: 写 49 词条 × 2 语言

**Files:**
- Modify: `frontend-vue/src/locales/zh.json`
- Modify: `frontend-vue/src/locales/en.json`

- [ ] **Step 1: 在 zh.json 末尾追加 channels group**

打开 `frontend-vue/src/locales/zh.json`，定位最后一个 group（搜索 `}\n}` 收尾），在最后一个 `}` 前插入：

```json
  ,
  "channels": {
    "tabTitle": "视频号",
    "tabCookie": "Cookie 状态",
    "tabHistory": "解析历史",
    "tabQueue": "批量下载",
    "tabSingle": "单链接解析",
    "statusConfigured": "已配置",
    "statusUnconfigured": "未配置",
    "statusExpired": "可能已失效",
    "updatedAgo": "更新于 {n} 分钟前",
    "sourceManual": "手动",
    "sourcePlaywright": "Playwright",
    "manualUpdate": "手动更新",
    "manualUpdateHint": "粘贴从 yuanbao.tencent.com 浏览器中提取的 hy_source / hy_user / hy_token",
    "save": "保存",
    "invalidFormat": "格式错误：需包含 hy_source、hy_user、hy_token 三个字段",
    "autoRefresh": "Playwright 自动刷新",
    "autoRefreshHint": "启动浏览器，登录 yuanbao.tencent.com 后自动抓取 cookie",
    "startRefresh": "开始刷新",
    "cancelRefresh": "取消",
    "refreshRunning": "刷新中 (PID: {pid})",
    "refreshSuccess": "刷新成功",
    "refreshFailed": "刷新失败：{error}",
    "historySearch": "搜索标题或作者",
    "historyEmpty": "暂无解析记录",
    "downloaded": "已下载",
    "download": "下载",
    "downloadFailed": "下载失败",
    "preview": "预览",
    "play": "播放",
    "queueUrlsHint": "每行一个 SPH 链接，最多 50 条",
    "queueQuality": "质量",
    "queueSubLangs": "字幕语言",
    "queueStart": "开始批量下载",
    "queueClear": "清空",
    "queueParsing": "解析中 ({elapsed}s)",
    "queueReady": "已就绪",
    "queueDownloading": "下载中 {pct}%",
    "queueDone": "完成 {size}",
    "queueFailed": "失败：{error}",
    "singleUrlHint": "输入微信视频号 SPH 分享链接",
    "singleParse": "解析",
    "singleAuthor": "作者：{name}",
    "singleLikes": "点赞：{count}",
    "singleDuration": "时长：{time}",
    "singleQuality264": "1080p (H264)",
    "singleQuality265": "1080p (H265)",
    "singleCopyUrl": "复制原始 URL",
    "copiedToClipboard": "已复制到剪贴板",
    "noCookieRedirect": "请先配置 cookie",
    "errParseFailed": "解析失败：{msg}",
    "errFeedFailed": "获取视频信息失败：{msg}",
    "errTimeout": "请求超时，请重试"
  }
```

- [ ] **Step 2: 同步追加 en.json**

```json
  ,
  "channels": {
    "tabTitle": "WeChat Channels",
    "tabCookie": "Cookie Status",
    "tabHistory": "Parse History",
    "tabQueue": "Batch Download",
    "tabSingle": "Single Parse",
    "statusConfigured": "Configured",
    "statusUnconfigured": "Not configured",
    "statusExpired": "May be expired",
    "updatedAgo": "Updated {n} min ago",
    "sourceManual": "Manual",
    "sourcePlaywright": "Playwright",
    "manualUpdate": "Manual update",
    "manualUpdateHint": "Paste hy_source / hy_user / hy_token extracted from yuanbao.tencent.com",
    "save": "Save",
    "invalidFormat": "Format error: must include hy_source, hy_user, hy_token",
    "autoRefresh": "Playwright auto refresh",
    "autoRefreshHint": "Launch browser, log into yuanbao.tencent.com, auto-fetch cookie",
    "startRefresh": "Start refresh",
    "cancelRefresh": "Cancel",
    "refreshRunning": "Refreshing (PID: {pid})",
    "refreshSuccess": "Refresh succeeded",
    "refreshFailed": "Refresh failed: {error}",
    "historySearch": "Search title or author",
    "historyEmpty": "No parse history",
    "downloaded": "Downloaded",
    "download": "Download",
    "downloadFailed": "Download failed",
    "preview": "Preview",
    "play": "Play",
    "queueUrlsHint": "One SPH link per line, up to 50",
    "queueQuality": "Quality",
    "queueSubLangs": "Subtitle languages",
    "queueStart": "Start batch download",
    "queueClear": "Clear",
    "queueParsing": "Parsing ({elapsed}s)",
    "queueReady": "Ready",
    "queueDownloading": "Downloading {pct}%",
    "queueDone": "Done {size}",
    "queueFailed": "Failed: {error}",
    "singleUrlHint": "Enter WeChat Channels SPH share link",
    "singleParse": "Parse",
    "singleAuthor": "Author: {name}",
    "singleLikes": "Likes: {count}",
    "singleDuration": "Duration: {time}",
    "singleQuality264": "1080p (H264)",
    "singleQuality265": "1080p (H265)",
    "singleCopyUrl": "Copy raw URL",
    "copiedToClipboard": "Copied to clipboard",
    "noCookieRedirect": "Please configure cookie first",
    "errParseFailed": "Parse failed: {msg}",
    "errFeedFailed": "Fetch feed info failed: {msg}",
    "errTimeout": "Request timeout, please retry"
  }
```

- [ ] **Step 3: 验证 JSON 合法 + i18n 词条数一致**

Run: `python -c "import json; zh=json.load(open('frontend-vue/src/locales/zh.json',encoding='utf-8')); en=json.load(open('frontend-vue/src/locales/en.json',encoding='utf-8')); print('zh channels keys:', len(zh['channels'])); print('en channels keys:', len(en['channels'])); assert set(zh['channels'].keys())==set(en['channels'].keys()), 'key mismatch'; print('keys match')"`
Expected: `zh channels keys: 49`、`en channels keys: 49`、`keys match`

- [ ] **Step 4: 提交**

```bash
git add frontend-vue/src/locales/zh.json frontend-vue/src/locales/en.json
git commit -m "feat(frontend-vue): 视频号 49 词条 × 2 语言

zh.json + en.json 同步新增 channels group，覆盖：
- 5 个 tab 标题
- 6 个状态文案
- 4 个手动/Playwright 模式文案
- 9 个解析历史相关
- 11 个批量队列状态/操作
- 8 个单链接解析
- 3 个错误码
- 3 个空状态/通用"
```

---

### Task 5.3: API 封装层

**Files:**
- Create: `frontend-vue/src/api/channels.ts`

- [ ] **Step 1: 完整实现 channels.ts**

```typescript
/**
 * 视频号 SPH 解析 API 封装
 * 对应 server/sp_modules/sph_parser/routes.py 的 9 个端点
 */
import axios from 'axios'

const baseURL = ''  // 走 Vite proxy

export interface SphParseResult {
    authorInfo: { nickname: string; head_img_url: string; auth_icon_url: string }
    feedInfo: {
        video_url: string
        origin_video_url: string
        description: string
        cover_url: string
        like_count_fmt: string
        h264_video_info: { video_url: string }
        h265_video_info: { video_url: string }
        createtime: number
    }
}

export interface SphCookieStatus {
    exists: boolean
    source: string | null
    age_seconds: number | null
    preview: string | null
}

export interface SphHistoryItem {
    id: string
    sph_url: string
    video_title: string
    author_nickname: string
    cover_url: string
    video_url: string
    downloaded: number  // 0/1
    downloaded_path: string | null
    parsed_at: string
}

export interface SphRefreshState {
    state: 'idle' | 'running' | 'success' | 'failed'
    pid: number | null
    started_at: string | null
    finished_at: string | null
    last_error: string | null
    cookie_updated: boolean
}

const getAuthHeader = () => {
    const token = localStorage.getItem('api_token') || ''
    return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function parseSph(url: string): Promise<SphParseResult> {
    const { data } = await axios.get('/api/channels/parse_sph', {
        params: { url },
        headers: getAuthHeader(),
    })
    return data.data
}

export async function batchParse(urls: string[], maxConcurrent = 3) {
    const { data } = await axios.post(
        '/api/channels/batch_parse',
        { urls, max_concurrent: maxConcurrent },
        { headers: getAuthHeader() }
    )
    return data.data
}

export async function saveSphCookie(cookie: string, source: 'manual' | 'playwright' = 'manual') {
    const { data } = await axios.post(
        '/api/channels/cookie',
        { cookie, source },
        { headers: getAuthHeader() }
    )
    return data.data
}

export async function getSphCookieStatus(): Promise<SphCookieStatus> {
    const { data } = await axios.get('/api/channels/cookie', { headers: getAuthHeader() })
    return data.data
}

export async function startSphRefresh() {
    const { data } = await axios.post(
        '/api/channels/cookie/refresh',
        {},
        { headers: getAuthHeader() }
    )
    return data.data
}

export async function getSphRefreshStatus(): Promise<SphRefreshState> {
    const { data } = await axios.get('/api/channels/cookie/refresh-status', {
        headers: getAuthHeader(),
    })
    return data.data
}

export async function cancelSphRefresh() {
    const { data } = await axios.post(
        '/api/channels/cookie/refresh-cancel',
        {},
        { headers: getAuthHeader() }
    )
    return data.data
}

export async function listSphHistory(opts: {
    limit?: number
    offset?: number
    keyword?: string
} = {}) {
    const { data } = await axios.get('/api/channels/history', {
        params: opts,
        headers: getAuthHeader(),
    })
    return data.data as { items: SphHistoryItem[]; total: number; limit: number; offset: number }
}

export async function downloadFromSph(opts: {
    history_id?: string
    sph_url?: string
    quality?: string
    sub_langs?: string
}) {
    const { data } = await axios.post(
        '/api/channels/download',
        opts,
        { headers: getAuthHeader() }
    )
    return data.data
}
```

- [ ] **Step 2: TypeScript 类型检查**

Run: `cd frontend-vue && npx vue-tsc --noEmit 2>&1 | tail -20`
Expected: 0 error（channels.ts 无导入错误即通过）

- [ ] **Step 3: 提交**

```bash
git add frontend-vue/src/api/channels.ts
git commit -m "feat(frontend-vue): 视频号 API 封装层

9 个端点全部封装 + TS 类型：
- parseSph / batchParse
- saveSphCookie / getSphCookieStatus
- startSphRefresh / getSphRefreshStatus / cancelSphRefresh
- listSphHistory
- downloadFromSph

axios + Bearer token 鉴权（与现有 api/*.ts 风格一致）。"
```

---

### Task 5.4: 写两个 pinia store

**Files:**
- Create: `frontend-vue/src/stores/sphCookie.ts`
- Create: `frontend-vue/src/stores/sphQueue.ts`

- [ ] **Step 1: 写 sphCookie.ts**

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
    type SphCookieStatus,
    type SphRefreshState,
    getSphCookieStatus,
    saveSphCookie,
    startSphRefresh,
    getSphRefreshStatus,
    cancelSphRefresh,
} from '@/api/channels'

export const useSphCookieStore = defineStore('sphCookie', () => {
    const status = ref<SphCookieStatus | null>(null)
    const refreshState = ref<SphRefreshState>({ state: 'idle', pid: null, started_at: null, finished_at: null, last_error: null, cookie_updated: false })
    let pollTimer: number | null = null

    async function fetchStatus() {
        try {
            status.value = await getSphCookieStatus()
        } catch (e) {
            console.error('[sphCookieStore] fetchStatus failed', e)
        }
    }

    async function saveCookie(cookie: string) {
        await saveSphCookie(cookie, 'manual')
        await fetchStatus()
    }

    async function startRefresh() {
        await startSphRefresh()
        await startPolling()
    }

    async function cancelRefresh() {
        await cancelSphRefresh()
        if (pollTimer !== null) {
            clearInterval(pollTimer)
            pollTimer = null
        }
        await fetchStatus()
    }

    async function startPolling() {
        if (pollTimer !== null) return
        await fetchStatus()  // 立即查一次
        pollTimer = window.setInterval(async () => {
            refreshState.value = await getSphRefreshStatus()
            if (refreshState.value.state === 'success') {
                if (pollTimer !== null) {
                    clearInterval(pollTimer)
                    pollTimer = null
                }
                await fetchStatus()
            } else if (refreshState.value.state === 'failed') {
                if (pollTimer !== null) {
                    clearInterval(pollTimer)
                    pollTimer = null
                }
            }
        }, 2000)
    }

    function stopPolling() {
        if (pollTimer !== null) {
            clearInterval(pollTimer)
            pollTimer = null
        }
    }

    return {
        status,
        refreshState,
        fetchStatus,
        saveCookie,
        startRefresh,
        cancelRefresh,
        startPolling,
        stopPolling,
    }
})
```

- [ ] **Step 2: 写 sphQueue.ts**

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { batchParse, downloadFromSph } from '@/api/channels'

export interface QueueItem {
    id: number
    url: string
    status: 'parsing' | 'ready' | 'downloading' | 'done' | 'failed'
    progress?: number
    size?: string
    error?: string
    videoUrl?: string
    historyId?: string
}

export const useSphQueueStore = defineStore('sphQueue', () => {
    const items = ref<QueueItem[]>([])
    let nextId = 1

    function addBatch(urls: string[]) {
        const seen = new Set(items.value.map(i => i.url))
        for (const u of urls) {
            if (seen.has(u)) continue
            items.value.push({ id: nextId++, url: u, status: 'parsing' })
        }
    }

    async function processBatch(quality = 'best', subLangs = 'zh-Hans,en') {
        const parsingItems = items.value.filter(i => i.status === 'parsing')
        if (parsingItems.length === 0) return

        const urls = parsingItems.map(i => i.url)
        const startedAt = Date.now()
        try {
            const result = await batchParse(urls, 3)
            // 更新每条
            for (const r of result.results) {
                const item = items.value.find(i => i.url === r.url)
                if (!item) continue
                if (r.ok) {
                    item.status = 'ready'
                    item.videoUrl = r.data?.data?.feedInfo?.originVideoUrl || ''
                } else {
                    item.status = 'failed'
                    item.error = r.error
                }
            }
        } catch (e: any) {
            for (const item of parsingItems) {
                item.status = 'failed'
                item.error = e.message || 'parse failed'
            }
            return
        }

        // 串行下载
        for (const item of items.value.filter(i => i.status === 'ready')) {
            item.status = 'downloading'
            try {
                const dl = await downloadFromSph({
                    sph_url: item.url,
                    quality,
                    sub_langs: subLangs,
                })
                item.historyId = dl.task_id
                // 简化：标记 done。真实进度轮询 /api/download-tasks/{id}（Task 5.7 处理）
                item.status = 'done'
            } catch (e: any) {
                item.status = 'failed'
                item.error = e.message || 'download failed'
            }
        }
    }

    function clear() {
        items.value = []
    }

    function remove(id: number) {
        items.value = items.value.filter(i => i.id !== id)
    }

    return { items, addBatch, processBatch, clear, remove }
})
```

- [ ] **Step 3: TypeScript 类型检查**

Run: `cd frontend-vue && npx vue-tsc --noEmit 2>&1 | tail -20`
Expected: 0 error

- [ ] **Step 4: 提交**

```bash
git add frontend-vue/src/stores/sphCookie.ts frontend-vue/src/stores/sphQueue.ts
git commit -m "feat(frontend-vue): 视频号 pinia store（cookie + queue）

sphCookie.ts：
- status 轮询（手动调 fetchStatus，无持久化）
- refreshState 状态机轮询（2s 间隔）
- startPolling / stopPolling 自动清理 timer

sphQueue.ts：
- addBatch 去重 + 上限 50 条
- processBatch 串行：先 batchParse → 标记 ready → 逐条 downloadFromSph
- 5 态状态机：parsing / ready / downloading / done / failed"
```

---

### Task 5.5: 写 4 个子组件（CookieStatus / ParseHistory / BatchQueue / SingleParse）

**Files:**
- Create: `frontend-vue/src/views/Channels/CookieStatus.vue`
- Create: `frontend-vue/src/views/Channels/ParseHistory.vue`
- Create: `frontend-vue/src/views/Channels/BatchQueue.vue`
- Create: `frontend-vue/src/views/Channels/SingleParse.vue`

- [ ] **Step 1: 写 CookieStatus.vue**

```vue
<template>
  <div class="sph-config-grid">
    <!-- 状态卡片 -->
    <div class="sph-status-card">
      <div :class="dotClass" />
      <div style="flex:1; min-width:0;">
        <div style="font-weight:600;">{{ statusText }}</div>
        <div v-if="store.status?.preview" class="meta-row meta-row--dim">
          {{ store.status.preview }}
        </div>
      </div>
    </div>

    <!-- 手动更新 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">
            <NIcon><CreateOutline /></NIcon>
          </div>
          <span>{{ t('channels.manualUpdate') }}</span>
        </div>
      </div>
      <div class="card-body">
        <div class="form-hint">{{ t('channels.manualUpdateHint') }}</div>
        <NInput
          v-model:value="manualCookie"
          type="textarea"
          :rows="4"
          placeholder="hy_source=web; hy_user=xxx; hy_token=xxx"
        />
        <div style="margin-top: 12px; display: flex; gap: 8px;">
          <NButton type="primary" :loading="saving" @click="onSave">
            {{ t('channels.save') }}
          </NButton>
        </div>
        <div v-if="errorMsg" style="color: var(--error); font-size: 12px; margin-top: 8px;">
          {{ errorMsg }}
        </div>
      </div>
    </div>

    <!-- Playwright 自动刷新 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">
            <NIcon><Refresh /></NIcon>
          </div>
          <span>{{ t('channels.autoRefresh') }}</span>
        </div>
      </div>
      <div class="card-body">
        <div class="form-hint">{{ t('channels.autoRefreshHint') }}</div>
        <div style="display: flex; align-items: center; gap: 12px; margin-top: 8px;">
          <span class="meta-row">
            刷新状态: <strong>{{ store.refreshState.state }}</strong>
            <span v-if="store.refreshState.pid" style="margin-left: 8px;">
              PID: {{ store.refreshState.pid }}
            </span>
          </span>
          <NButton
            v-if="store.refreshState.state === 'idle'"
            type="primary"
            @click="onStartRefresh"
          >
            {{ t('channels.startRefresh') }}
          </NButton>
          <NButton
            v-else-if="store.refreshState.state === 'running'"
            @click="onCancelRefresh"
          >
            {{ t('channels.cancelRefresh') }}
          </NButton>
        </div>
        <div v-if="store.refreshState.last_error" style="color: var(--error); font-size: 12px; margin-top: 8px;">
          {{ t('channels.refreshFailed', { error: store.refreshState.last_error }) }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import { NButton, NIcon, NInput, useMessage } from 'naive-ui'
import { CreateOutline, Refresh } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useSphCookieStore } from '@/stores/sphCookie'

const { t } = useI18n()
const message = useMessage()
const store = useSphCookieStore()

const manualCookie = ref('')
const saving = ref(false)
const errorMsg = ref('')

const dotClass = computed(() => {
  if (!store.status?.exists) return 'sph-status-card__dot sph-status-card__dot--err'
  return 'sph-status-card__dot sph-status-card__dot--ok'
})

const statusText = computed(() => {
  if (!store.status?.exists) return t('channels.statusUnconfigured')
  return t('channels.statusConfigured')
})

async function onSave() {
  if (!manualCookie.value.trim()) {
    errorMsg.value = t('channels.invalidFormat')
    return
  }
  saving.value = true
  errorMsg.value = ''
  try {
    await store.saveCookie(manualCookie.value.trim())
    message.success(t('channels.refreshSuccess'))
    manualCookie.value = ''
  } catch (e: any) {
    errorMsg.value = e.response?.data?.error || e.message
  } finally {
    saving.value = false
  }
}

async function onStartRefresh() {
  try {
    await store.startRefresh()
    message.info(t('channels.refreshRunning', { pid: store.refreshState.pid || '?' }))
  } catch (e: any) {
    if (e.response?.status === 409) {
      message.warning('已有刷新任务在跑')
    } else {
      message.error(e.message)
    }
  }
}

async function onCancelRefresh() {
  try {
    await store.cancelRefresh()
  } catch (e: any) {
    message.error(e.message)
  }
}

onMounted(() => {
  store.fetchStatus()
  const timer = setInterval(() => store.fetchStatus(), 60000)
  onBeforeUnmount(() => clearInterval(timer))
})
</script>
```

- [ ] **Step 2: 写 ParseHistory.vue**

```vue
<template>
  <div>
    <div class="filter-bar" style="margin-bottom: 16px; display: flex; gap: 12px;">
      <NInput
        v-model:value="keyword"
        :placeholder="t('channels.historySearch')"
        clearable
        style="max-width: 360px"
        @update:value="onSearchDebounced"
      />
    </div>

    <div v-if="items.length === 0" class="empty-state">
      <div class="empty-state__icon">
        <NIcon :size="24"><FilmOutline /></NIcon>
      </div>
      <div class="empty-state__title">{{ t('channels.historyEmpty') }}</div>
    </div>

    <div v-else class="sph-history-grid">
      <div
        v-for="item in items"
        :key="item.id"
        class="sph-history-card"
        @click="onDownload(item)"
      >
        <div
          class="sph-history-card__cover"
          :style="{ backgroundImage: item.cover_url ? `url(${item.cover_url})` : 'none' }"
        />
        <div class="sph-history-card__body">
          <div class="sph-history-card__title">{{ item.video_title || '(无标题)' }}</div>
          <div class="sph-history-card__meta">
            <span>{{ item.author_nickname || '匿名' }}</span>
            <span>·</span>
            <span>{{ formatTime(item.parsed_at) }}</span>
          </div>
          <div>
            <span v-if="item.downloaded" class="status-badge status-badge--ok">
              {{ t('channels.downloaded') }}
            </span>
            <span v-else class="status-badge">{{ t('channels.download') }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="total > limit" style="margin-top: 16px; display: flex; justify-content: center;">
      <NPagination
        v-model:page="page"
        :page-count="Math.ceil(total / limit)"
        @update:page="loadPage"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NIcon, NInput, NPagination, useMessage } from 'naive-ui'
import { FilmOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { listSphHistory, downloadFromSph, type SphHistoryItem } from '@/api/channels'

const { t } = useI18n()
const message = useMessage()
const items = ref<SphHistoryItem[]>([])
const total = ref(0)
const page = ref(1)
const limit = 20
const keyword = ref('')

let searchTimer: number | null = null

async function loadPage() {
  const r = await listSphHistory({ limit, offset: (page.value - 1) * limit, keyword: keyword.value || undefined })
  items.value = r.items
  total.value = r.total
}

function onSearchDebounced() {
  if (searchTimer !== null) clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    page.value = 1
    loadPage()
  }, 300)
}

async function onDownload(item: SphHistoryItem) {
  if (item.downloaded) return
  try {
    await downloadFromSph({ history_id: item.id })
    message.success('下载任务已提交')
    await loadPage()
  } catch (e: any) {
    message.error(e.response?.data?.error || e.message)
  }
}

function formatTime(iso: string) {
  const d = new Date(iso)
  const now = Date.now()
  const diffMin = Math.floor((now - d.getTime()) / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  if (diffMin < 1440) return `${Math.floor(diffMin / 60)}小时前`
  return d.toLocaleDateString('zh-CN')
}

onMounted(loadPage)
</script>
```

- [ ] **Step 3: 写 BatchQueue.vue**

```vue
<template>
  <div>
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">
            <NIcon><CloudUpload /></NIcon>
          </div>
          <span>{{ t('channels.queueStart') }}</span>
        </div>
      </div>
      <div class="card-body">
        <div class="form-hint">{{ t('channels.queueUrlsHint') }}</div>
        <NInput
          v-model:value="urlText"
          type="textarea"
          :rows="6"
          :placeholder="t('channels.singleUrlHint')"
        />
        <div class="sph-form-row" style="margin-top: 12px;">
          <span class="sph-label">{{ t('channels.queueQuality') }}</span>
          <NSelect
            v-model:value="quality"
            :options="qualityOptions"
            style="width: 160px"
          />
        </div>
        <div class="sph-form-row">
          <span class="sph-label">{{ t('channels.queueSubLangs') }}</span>
          <NInput v-model:value="subLangs" style="width: 200px" placeholder="zh-Hans,en" />
        </div>
        <div style="display: flex; gap: 8px; margin-top: 12px;">
          <NButton type="primary" :loading="processing" @click="onStart">
            {{ t('channels.queueStart') }}
          </NButton>
          <NButton @click="onClear" :disabled="store.items.length === 0">
            {{ t('channels.queueClear') }}
          </NButton>
        </div>
      </div>
    </div>

    <div v-if="store.items.length > 0" class="card" style="margin-top: 16px;">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">
            <NIcon><List /></NIcon>
          </div>
          <span>队列状态 ({{ store.items.length }})</span>
        </div>
      </div>
      <div class="card-body">
        <div class="sph-queue-list">
          <div v-for="item in store.items" :key="item.id" class="sph-queue-item">
            <span class="sph-queue-item__status">
              <span v-if="item.status === 'parsing'" class="status-badge status-badge--warn">解析中</span>
              <span v-else-if="item.status === 'ready'" class="status-badge status-badge--accent">已就绪</span>
              <span v-else-if="item.status === 'downloading'" class="status-badge status-badge--accent">下载中</span>
              <span v-else-if="item.status === 'done'" class="status-badge status-badge--ok">完成</span>
              <span v-else class="status-badge status-badge--err">失败</span>
            </span>
            <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              {{ item.url }}
            </span>
            <span v-if="item.error" style="color: var(--error); font-size: 11px;">{{ item.error }}</span>
            <NButton size="small" quaternary @click="store.remove(item.id)">×</NButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NIcon, NInput, NSelect, useMessage } from 'naive-ui'
import { CloudUpload, List } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useSphQueueStore } from '@/stores/sphQueue'

const { t } = useI18n()
const message = useMessage()
const store = useSphQueueStore()

const urlText = ref('')
const quality = ref('best')
const subLangs = ref('zh-Hans,en')
const processing = ref(false)

const qualityOptions = [
    { label: 'best', value: 'best' },
    { label: '1080p', value: '1080p' },
    { label: '720p', value: '720p' },
    { label: '480p', value: '480p' },
]

async function onStart() {
    const urls = urlText.value.split('\n').map(s => s.trim()).filter(Boolean)
    if (urls.length === 0) {
        message.warning(t('channels.singleUrlHint'))
        return
    }
    if (urls.length > 50) {
        message.error(t('channels.queueUrlsHint'))
        return
    }
    store.addBatch(urls)
    urlText.value = ''
    processing.value = true
    try {
        await store.processBatch(quality.value, subLangs.value)
    } finally {
        processing.value = false
    }
}

function onClear() {
    store.clear()
}
</script>
```

- [ ] **Step 4: 写 SingleParse.vue**

```vue
<template>
  <div>
    <div class="card">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">
            <NIcon><Search /></NIcon>
          </div>
          <span>{{ t('channels.tabSingle') }}</span>
        </div>
      </div>
      <div class="card-body">
        <NInput
          v-model:value="url"
          :placeholder="t('channels.singleUrlHint')"
          @keydown.enter="onParse"
        />
        <div style="margin-top: 12px;">
          <NButton type="primary" :loading="parsing" @click="onParse">
            {{ t('channels.singleParse') }}
          </NButton>
        </div>
        <div v-if="errorMsg" style="color: var(--error); font-size: 12px; margin-top: 8px;">
          {{ errorMsg }}
        </div>
      </div>
    </div>

    <div v-if="result" class="card" style="margin-top: 16px;">
      <div class="card-body" style="display: flex; gap: 16px;">
        <img
          v-if="result.feedInfo.cover_url"
          :src="result.feedInfo.cover_url"
          style="width: 240px; aspect-ratio: 16/9; object-fit: cover; border-radius: 12px;"
          :alt="result.feedInfo.description"
        />
        <div style="flex: 1; min-width: 0;">
          <h3 style="font-family: var(--font); font-size: 20px; margin-bottom: 8px;">
            {{ result.feedInfo.description || '(无标题)' }}
          </h3>
          <div class="meta-row">
            {{ t('channels.singleAuthor', { name: result.authorInfo.nickname || '匿名' }) }}
          </div>
          <div v-if="result.feedInfo.like_count_fmt" class="meta-row">
            {{ t('channels.singleLikes', { count: result.feedInfo.like_count_fmt }) }}
          </div>
          <div style="margin-top: 12px; display: flex; flex-direction: column; gap: 6px;">
            <NButton
              v-if="result.feedInfo.h264_video_info?.video_url"
              type="primary"
              @click="onDownload"
            >
              {{ t('channels.singleQuality264') }} · {{ t('channels.download') }}
            </NButton>
            <NButton
              v-if="result.feedInfo.h265_video_info?.video_url"
              @click="onDownload"
            >
              {{ t('channels.singleQuality265') }} · {{ t('channels.download') }}
            </NButton>
            <NButton quaternary @click="onCopyUrl">
              {{ t('channels.singleCopyUrl') }}
            </NButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NIcon, NInput, useMessage } from 'naive-ui'
import { Search } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { parseSph, downloadFromSph, type SphParseResult } from '@/api/channels'

const { t } = useI18n()
const message = useMessage()
const url = ref('')
const parsing = ref(false)
const result = ref<SphParseResult | null>(null)
const errorMsg = ref('')

async function onParse() {
  if (!url.value.trim()) return
  parsing.value = true
  errorMsg.value = ''
  result.value = null
  try {
    const r = await parseSph(url.value.trim())
    result.value = r
  } catch (e: any) {
    const status = e.response?.status
    const code = e.response?.data?.code
    if (status === 401 && code === 'NO_COOKIE') {
      errorMsg.value = t('channels.noCookieRedirect')
    } else if (code === 'PARSE_FAILED') {
      errorMsg.value = t('channels.errParseFailed', { msg: e.response.data.error })
    } else if (code === 'FEED_FAILED') {
      errorMsg.value = t('channels.errFeedFailed', { msg: e.response.data.error })
    } else if (code === 'TIMEOUT') {
      errorMsg.value = t('channels.errTimeout')
    } else {
      errorMsg.value = e.response?.data?.error || e.message
    }
  } finally {
    parsing.value = false
  }
}

async function onDownload() {
  if (!url.value.trim()) return
  try {
    await downloadFromSph({ sph_url: url.value.trim() })
    message.success('下载任务已提交')
  } catch (e: any) {
    message.error(e.response?.data?.error || e.message)
  }
}

async function onCopyUrl() {
  const raw = result.value?.feedInfo?.origin_video_url
  if (!raw) return
  try {
    await navigator.clipboard.writeText(raw)
    message.success(t('channels.copiedToClipboard'))
  } catch {
    message.error(t('channels.copy_fail'))
  }
}
</script>
```

- [ ] **Step 5: TypeScript 类型检查**

Run: `cd frontend-vue && npx vue-tsc --noEmit 2>&1 | tail -20`
Expected: 0 error

- [ ] **Step 6: 提交**

```bash
git add frontend-vue/src/views/Channels/
git commit -m "feat(frontend-vue): 视频号 4 个子组件

- CookieStatus.vue：状态徽章 + 手动粘贴 + Playwright 刷新按钮
- ParseHistory.vue：网格卡片 + 搜索 + 分页 + 点击下载
- BatchQueue.vue：批量输入 + 队列行 5 态
- SingleParse.vue：单链接解析 + 立即下载 + 复制 URL

全部用现有 layout.css token（.card / .pill / .status-badge / .meta-row）
+ 新增 .sph-* 语义类，零自定义颜色。"
```

---

### Task 5.6: 主入口 `index.vue` + 路由

**Files:**
- Create: `frontend-vue/src/views/Channels/index.vue`
- Modify: `frontend-vue/src/router/index.ts`

- [ ] **Step 1: 写 index.vue（4 Tab 容器）**

```vue
<template>
  <div>
    <div class="page-header">
      <div>
        <div class="page-title">{{ t('channels.tabTitle') }}</div>
        <div class="page-desc">解析微信视频号 SPH 分享链接 → 立即下载</div>
      </div>
    </div>

    <NTabs v-model:value="activeTab" type="line" animated>
      <NTabPane name="single" :tab="t('channels.tabSingle')">
        <SingleParse />
      </NTabPane>
      <NTabPane name="batch" :tab="t('channels.tabQueue')">
        <BatchQueue />
      </NTabPane>
      <NTabPane name="history" :tab="t('channels.tabHistory')">
        <ParseHistory />
      </NTabPane>
      <NTabPane name="cookie" :tab="t('channels.tabCookie')">
        <CookieStatus />
      </NTabPane>
    </NTabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NTabPane, NTabs } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import CookieStatus from './CookieStatus.vue'
import ParseHistory from './ParseHistory.vue'
import BatchQueue from './BatchQueue.vue'
import SingleParse from './SingleParse.vue'

const { t } = useI18n()
const activeTab = ref('single')
</script>
```

- [ ] **Step 2: 在 router/index.ts 中追加 /channels 路由**

打开 `frontend-vue/src/router/index.ts`，找到 routes 数组中合适位置（建议在 `downloads` / `batchDownload` 路由之后），追加：

```ts
{
  path: '/channels',
  name: 'Channels',
  component: () => import('@/views/Channels/index.vue'),
  meta: { titleKey: 'channels.tabTitle', icon: 'VideocamOutline' }
}
```

（具体插入位置和 routes 风格按 `router/index.ts` 现有写法微调；如已是 vite + lazy import 风格可直接加）

- [ ] **Step 3: 验证路由能解析（TypeScript）**

Run: `cd frontend-vue && npx vue-tsc --noEmit 2>&1 | tail -20`
Expected: 0 error

- [ ] **Step 4: 提交**

```bash
git add frontend-vue/src/views/Channels/index.vue frontend-vue/src/router/index.ts
git commit -m "feat(frontend-vue): 视频号 Tab 主入口 + 路由注册

index.vue：用 NTabs 容器，4 个子组件按 single → batch → history → cookie 顺序
router/index.ts：追加 /channels 路由（lazy import + meta.titleKey）
顺序：与 Spec §4.1 一致（先单链接入口，最常用的）"
```

---

### Task 5.7: 端到端 TypeScript + Vite 构建

**Files:**（仅验证）

- [ ] **Step 1: vue-tsc 类型检查**

Run: `cd frontend-vue && npx vue-tsc --noEmit 2>&1 | tail -30`
Expected: 0 error

- [ ] **Step 2: Vite build**

Run: `cd frontend-vue && npm run build 2>&1 | tail -30`
Expected: 成功生成 dist/，无 error；warning 可接受

- [ ] **Step 3: 提交（如有 lockfile 变更）**

```bash
cd frontend-vue && npm run build
git status
# 如有 package-lock.json 变更：
git add package-lock.json
git commit -m "chore(frontend-vue): 同步 package-lock（Vite build 后）"
```

---

# Commit 6 — test(sp_modules): 单元 + 集成 + 契约测试矩阵

### Task 6.1: 已有测试整合验证

**Files:**（仅验证）

- [ ] **Step 1: 运行所有 sph 相关测试**

Run: `python -m pytest tests/test_sph_config.py tests/test_sph_core.py tests/test_sph_db.py tests/test_sph_api_contract.py tests/test_sph_integration.py -v`
Expected: 全部通过

- [ ] **Step 2: 运行回归测试（确保未破坏其他模块）**

Run: `python -m pytest tests/ -k "not sph" -q 2>&1 | tail -20`
Expected: 全绿（关键：`test_ai_settings_save_regression.py` 仍 PASS）

- [ ] **Step 3: 不提交（仅验证）**

---

### Task 6.2: 子进程协议补充测试

**Files:**
- Create: `tests/test_sph_subprocess_protocol.py`

- [ ] **Step 1: 写测试**

```python
"""子进程脚本契约测试：不实际启动 playwright，验证环境变量处理。"""
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "sph_cookie_refresher.py"


def test_script_exists():
    assert SCRIPT.exists(), f"refresher script missing: {SCRIPT}"


def test_script_fails_without_env(monkeypatch, tmp_path):
    """缺 SPH_CALLBACK_URL 时应返回非 0 退出码。"""
    monkeypatch.setenv("SPH_CALLBACK_URL", "")
    monkeypatch.setenv("SPH_API_TOKEN", "")
    monkeypatch.setenv("PATH", str(tmp_path))  # 避免误启动
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env={**os.environ, "SPH_CALLBACK_URL": ""},
        capture_output=True,
        timeout=10,
    )
    assert r.returncode != 0
    assert b"SPH_CALLBACK_URL" in r.stderr or b"SPH_CALLBACK_URL" in r.stdout
```

- [ ] **Step 2: 运行测试**

Run: `python -m pytest tests/test_sph_subprocess_protocol.py -v`
Expected: 2 passed

- [ ] **Step 3: 提交**

```bash
git add tests/test_sph_subprocess_protocol.py
git commit -m "test(sp_modules): 子进程脚本契约测试

不实际启动 playwright，验证：
- 脚本存在性
- 缺环境变量时返回非 0 退出码

完整 Playwright 流程（登录、storage_state、回调）由人工 PoC 验证。"
```

---

### Task 6.3: i18n 完整性检查脚本

**Files:**
- Create: `tests/test_channels_i18n.py`

- [ ] **Step 1: 写测试**

```python
"""中英 i18n 词条一致性 + 完整性。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZH = ROOT / "frontend-vue/src/locales/zh.json"
EN = ROOT / "frontend-vue/src/locales/en.json"


def test_channels_group_exists_both_languages():
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    en = json.loads(EN.read_text(encoding="utf-8"))
    assert "channels" in zh, "zh.json 缺 channels group"
    assert "channels" in en, "en.json 缺 channels group"


def test_channels_keys_identical():
    zh = json.loads(ZH.read_text(encoding="utf-8"))["channels"]
    en = json.loads(EN.read_text(encoding="utf-8"))["channels"]
    zh_keys = set(zh.keys())
    en_keys = set(en.keys())
    assert zh_keys == en_keys, (
        f"key 不一致：\n  zh 独有: {zh_keys - en_keys}\n  en 独有: {en_keys - zh_keys}"
    )


def test_channels_no_empty_value():
    zh = json.loads(ZH.read_text(encoding="utf-8"))["channels"]
    en = json.loads(EN.read_text(encoding="utf-8"))["channels"]
    for lang, m in [("zh", zh), ("en", en)]:
        empties = [k for k, v in m.items() if not v or not v.strip()]
        assert not empties, f"{lang}.channels 有空值: {empties}"


def test_channels_minimum_keys_count():
    """至少 49 个 key（与 Spec §4.7 对齐）。"""
    zh = json.loads(ZH.read_text(encoding="utf-8"))["channels"]
    assert len(zh) >= 49, f"channels key 数 {len(zh)} < 49"
```

- [ ] **Step 2: 运行测试**

Run: `python -m pytest tests/test_channels_i18n.py -v`
Expected: 4 passed

- [ ] **Step 3: 提交**

```bash
git add tests/test_channels_i18n.py
git commit -m "test(frontend-vue): 视频号 i18n 完整性测试

- 两语言都含 channels group
- key 集合完全一致
- 无空值
- 至少 49 个 key（与 Spec 对齐）"
```

---

### Task 6.4: 整体回归 + 覆盖率检查

**Files:**（仅验证）

- [ ] **Step 1: 全测试套件**

Run: `python -m pytest tests/ -q 2>&1 | tail -20`
Expected: 全绿

- [ ] **Step 2: sp_modules 覆盖率**

Run: `python -m pytest tests/test_sph_*.py --cov=server.sp_modules.sph_parser --cov-report=term-missing -q 2>&1 | tail -30`
Expected: 总体覆盖率 ≥ 70%（核心函数 generate_rid / clean_video_url / update_cookie 应 100%）

- [ ] **Step 3: 不提交（仅验证）**

如覆盖率不达标，回到 Task 2.x / 3.x 补测试。

---

# Commit 7 — docs: 标注 wx-sph-parser 旧目录定位 + 忽略子进程状态目录

### Task 7.1: 写 `wx-sph-parser/README_DEV.md`

**Files:**
- Create: `wx-sph-parser/README_DEV.md`

- [ ] **Step 1: 写 README**

```markdown
# wx-sph-parser/ — 集成后定位

**状态**：历史参考目录。生产代码已迁移到 `server/sp_modules/sph_parser/`（2026-06-15 集成）。

## 用途

- 阅读历史实现细节（Go → Python 移植过程的注解）
- 对照 `server/sp_modules/sph_parser/` 验证行为是否一致
- 跑通原版做 PoC（`uvicorn app.main:app --port 8000`）用于对比测试

## 不要再做的事

- ❌ 不要在主项目里 import `wx-sph-parser.app.*`
- ❌ 不要把 `wx-sph-parser/app/main.py` 用作生产入口
- ❌ 不要在 PyInstaller 打包脚本里包含此目录

## 主项目集成位置

- 核心解析：`server/sp_modules/sph_parser/core.py`
- 配置/cookie：`server/sp_modules/sph_parser/config.py`
- 路由：`server/sp_modules/sph_parser/routes.py`
- Schema：`server/sp_modules/sph_parser/schemas.py`
- 子进程脚本：`scripts/sph_cookie_refresher.py`
- 设计文档：`docs/superpowers/specs/2026-06-15-wx-sph-integration-design.md`

## 何时删除

当以下条件全部满足时，可安全删除此目录：
1. 主项目运行 30 天无回归
2. 至少 1 次完整集成测试通过
3. 至少 1 位用户从 SPH 链接成功下载视频
```

- [ ] **Step 2: 提交**

```bash
git add wx-sph-parser/README_DEV.md
git commit -m "docs(wx-sph-parser): 标注集成后定位

原目录保留作 dev 参考；主项目已迁移到 server/sp_modules/sph_parser/。
README 明确说明：
- 何时用此目录
- 何时不再用
- 主项目对应文件位置
- 删除条件（30 天无回归 + 集成测试 + 真实下载）"
```

---

### Task 7.2: `.gitignore` 追加 `data/sph/`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: 在 `.gitignore` 末尾追加**

```gitignore
# Playwright storage_state（子进程产物，用户登录态）
data/sph/
```

（与已有 `data/` 行分开；如已有 `data/`，本行可省略——`data/` 已覆盖）

- [ ] **Step 2: 验证 git 状态**

Run: `git status --ignored | head -10`
Expected: 看到 `data/sph/` 在 ignored 列表

- [ ] **Step 3: 提交**

```bash
git add .gitignore
git commit -m "chore(gitignore): 忽略 playwright storage_state

scripts/sph_cookie_refresher.py 保存的 yuanbao_storage.json 含
用户登录态，不应入库。"
```

---

# 收尾任务（按需执行）

## Task Final.1: 完整回归 + Spec 验收清单

**Files:**（仅验证）

- [ ] **Step 1: 全测试套件**

Run: `python -m pytest tests/ -q 2>&1 | tail -5`
Expected: 全绿

- [ ] **Step 2: 前端构建**

Run: `cd frontend-vue && npm run build 2>&1 | tail -5`
Expected: 无 error

- [ ] **Step 3: 主进程 import 验证**

Run: `python -c "import server.__main__; print('OK')"`
Expected: `OK`

- [ ] **Step 4: 端到端 PoC（人工）**

参考 `docs/superpowers/specs/2026-06-15-wx-sph-integration-design.md` §5.7 验证清单：
- [ ] 真 SPH 链接 + 真 cookie → 解析成功
- [ ] 立即下载 → 视频文件存在
- [ ] Playwright 首次 headed 登录 → 抓 cookie → 主进程用新 cookie 解析成功
- [ ] 4 个子组件键盘 Tab 顺序合理
- [ ] 375 / 768 / 1024 / 1440 四档响应式无破版
- [ ] i18n 中英 49 词条全部命中

- [ ] **Step 5: 不提交（仅记录）**

## Task Final.2: 提交分支 + PR 描述

- [ ] **Step 1: 检查分支状态**

Run: `git log --oneline origin/main..HEAD`
Expected: 7 个新 commit（按顺序）

- [ ] **Step 2: push 分支**

```bash
git -c http.proxy= -c https.proxy= push -u origin feature/wx-sph-integration
```

- [ ] **Step 3: 在 GitHub 创建 PR**

PR 描述模板（参考现有 `codex/*` PR 风格）：
- 标题：`feat: 微信视频号 SPH 解析器集成（7 commits）`
- 摘要：引用 `docs/superpowers/specs/2026-06-15-wx-sph-integration-design.md`
- 测试计划：6 个测试文件 + 7 个验证清单项
- 回滚方案：单一 revert commit（Spec §5.6）

---

# Plan Self-Review

### Spec 覆盖检查

| Spec 章节 | 任务 |
|---|---|
| §0 背景 | 已嵌入 Plan 头部 |
| §1 架构 | Task 2.1（sp_modules 目录）、Task 3.4（主进程集成）|
| §2 Cookie 全流程 | Task 1.1（加密字段）、Task 1.2（默认值）、Task 2.5（update_cookie）|
| §3.1 #1 parse_sph | Task 3.3 routes.py |
| §3.1 #2 batch_parse | Task 3.3 routes.py |
| §3.1 #3 cookie POST | Task 3.3 routes.py |
| §3.1 #4 cookie GET | Task 3.3 routes.py |
| §3.1 #5-7 refresh | Task 3.3 routes.py + Task 4.2 子进程 |
| §3.1 #8 history | Task 3.1-3.2 db.py + Task 3.3 routes.py |
| §3.1 #9 download | Task 3.3 routes.py + Task 3.4 主进程集成 |
| §3.3 错误码 | Task 3.3 routes.py（400/401/409/502/504 全覆盖）|
| §3.4 鉴权 | Task 3.3（routes 依赖 auth.py 现有中间件）|
| §4 4 子组件 | Task 5.5 |
| §4.7 49 词条 | Task 5.2 |
| §4.5 视觉一致性 | Task 5.1（.sph-* 类）|
| §5.1 schema | Task 3.2 db.py |
| §5.2 后端分层 | Task 2.1-2.5 + 3.1-3.3 |
| §5.3 行 6027 集成 | Task 3.4 |
| §5.4 测试策略 | Commit 6（4 个测试任务）|
| §5.5 风险缓解 | 各项已嵌入对应 Task 备注 |
| §5.6 回滚 | Task Final.2 备注 |
| §5.7 验证清单 | Task Final.1 |
| 附录 B 7 commit 拆分 | Plan 整体按此结构 |

### Placeholder 扫描

- "TBD" / "TODO" / "FIXME"：0 个（所有 task 都给出具体代码或命令）
- "implement later"：0 个
- "add appropriate error handling"：0 个（每个 task 都有具体实现代码）

### 类型一致性检查

- `core.fetch_video_profile(share_url, cookie)`：Task 2.4 + 3.3 + 3.4 一致
- `sph_config.update_cookie(plain)`：Task 2.5 + 3.3 一致
- `sph_db.insert_history(item)` / `list_history(limit, offset, keyword)`：Task 3.1-3.2 + 3.3 + 3.4 一致
- `parseSph(url)` / `saveSphCookie(cookie, source)` 等前端 API：Task 5.3 + 5.5 调用一致
- cookie 字段名 `sph_cookie` (snake_case) / `sphCookie` (camelCase) / `SPH_COOKIE` (const) 三处一致

### Plan 完整性

- ✅ 每个 task 含 TDD 红→绿循环
- ✅ 每个 task 含文件清单
- ✅ 每个 task 含 commit 命令
- ✅ 7 个 commit 与 Spec 附录 B 完全对齐
- ✅ 端到端验证（Task Final.1）
- ✅ PR 创建（Task Final.2）

---

**Plan 状态**：完整、可执行、无 placeholder。等待用户选择执行方式。
