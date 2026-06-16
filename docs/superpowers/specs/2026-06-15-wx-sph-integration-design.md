# 微信视频号 SPH 解析器集成 — 设计文档

**日期：** 2026-06-15
**作者：** Claude Opus 4.8（与 wuaikaiyuan 协作完成）
**状态：** 已通过所有 Section 评审，待用户 review 后进入 writing-plans 阶段
**目标分支：** `feature/wx-sph-integration`（基于 `origin/main` = `0d0ac73`）

---

## 0. 背景与目标

### 0.1 现状

- 项目 `ytdlp-batch-downloader` 已具备 YouTube 频道监控 + 批量下载能力（`server/__main__.py:6357` 行单文件，`batch_download` 走 `yt-dlp` 路径）
- 仓库同级目录有独立服务 `wx-sph-parser`（Python FastAPI，约 430 行），可解析微信视频号 SPH 分享链接为视频元数据
- 现有 B 站通用视频通过 `yt-dlp` 批量下载（`server/__main__.py:6027`），但**微信视频号链接 yt-dlp 无法直接支持**

### 0.2 目标

将 `wx-sph-parser` 集成到 `ytdlp-batch-downloader` 中，使得：
1. 用户可在 `frontend-vue` 的"视频号"独立 Tab 中粘贴 SPH 链接 → 解析 → 立即下载
2. 复用现有 `yt-dlp` 批量下载管道（与 `BatchDownload.vue` 同构）
3. Cookie 安全存储（与 `llm_api_key` 同套加密）
4. 提供 Playwright 子进程通道用于 cookie 自动续期

### 0.3 反 Scope

- ❌ 不做 SPH 链接的频道监控（与 YouTube 监控语义不同，SPH 是单次分享链接）
- ❌ 不做视频内容处理（剪辑、字幕生成、封面等）
- ❌ 不做多账号体系（SPH 解析是单 cookie）
- ❌ 不打包 Playwright 进 PyInstaller 主 exe（保持主 exe 体积）

---

## Section 1：架构总览 + 模块布局

### 1.1 模块布局

```
ytdlp-batch-downloader/
├── server/
│   ├── __main__.py                  # 6357 → ~6470 行（+113 行：3 个路由 + 集成点）
│   └── sp_modules/                  # 新增
│       ├── __init__.py
│       └── sph_parser/              # 从 wx-sph-parser/app/ 移植
│           ├── __init__.py
│           ├── core.py              # 原 sph.py 重命名（避免与 sp_modules 同名）
│           ├── config.py            # 改用 config.json 读取
│           ├── schemas.py           # 原样
│           └── routes.py            # 新增：FastAPI 路由（被 server/__main__.py mount）
├── config/
│   ├── settings.py                  # +sph_cookie 加解密 + get_sph_cookie()
│   └── schema.json (or template)    # +sph_cookie 字段定义
├── frontend-vue/src/
│   ├── views/Channels/              # 新增
│   ├── api/channels.ts              # 新增
│   ├── stores/sphCookie.ts          # 新增
│   ├── stores/sphQueue.ts           # 新增
│   ├── i18n/locales/{zh-CN,en-US}.json  # 补 ~20 词条
│   └── router/index.ts              # +/channels 路由
├── scripts/
│   └── sph_cookie_refresher.py      # playwright 子进程脚本（不打包进主 exe）
├── tests/
│   ├── test_sph_parser_unit.py
│   ├── test_sph_api_contract.py
│   └── test_sph_cookie_storage.py
├── wx-sph-parser/                   # 保留为 dev 工具
│   ├── README_DEV.md                # 新增：说明"集成后此目录仅作 dev 参考"
│   └── ...原文件不变
└── docs/superpowers/specs/
    └── 2026-06-15-wx-sph-integration-design.md   # 本文档
```

### 1.2 进程拓扑

```
[主进程 server/__main__.py]
   ├─ in-process import: server/sp_modules/sph_parser
   │   └─ 内部调用 fetch_video_profile() 用于批量下载
   └─ FastAPI routes: /api/channels/* (受 auth.py 保护)

[按需子进程 scripts/sph_cookie_refresher.py]
   └─ Playwright headed → yuanbao.tencent.com → 抓 cookie → POST 回主进程
       触发条件：用户在 UI 主动点击 / 解析失败超过阈值
```

### 1.3 关键边界

- 主进程**不直接 import playwright**（避免打包膨胀 + 反爬风险隔离）
- 子进程通过 `httpx` POST 写回主进程 `/api/channels/cookie` 端点
- 主进程与子进程之间**只通过 HTTP + JSON 通信**，无共享内存

---

## Section 2：Cookie 管理全流程

### 2.1 存储与加密

`config.json` 新增字段：

| 字段 | 类型 | 加密 | 默认值 | 说明 |
|---|---|---|---|---|
| `sph_cookie` | string | ✅ Fernet | `""` | 完整 cookie 字符串：`hy_source=web; hy_user=xxx; hy_token=xxx` |
| `sph_cookie_updated_at` | string（ISO8601） | ❌ | `""` | 最近一次成功更新时间（前端展示用） |
| `sph_cookie_source` | string | ❌ | `"manual"` | `"manual"` / `"playwright"`，前端展示 |
| `sph_cookie_auto_refresh` | bool | ❌ | `false` | 是否启用 Playwright 自动刷新 |

**为什么不存 3 个独立字段**：与 `wx-sph-parser` 原生一致；用户复制习惯是整段粘贴；校验逻辑简单。

**加解密挂钩**（`config/settings.py`）：

```python
def get_sph_cookie() -> str:
    cfg = _load_config()
    return _decrypt_config_value(cfg.get("sph_cookie", ""))

def set_sph_cookie(plain: str, source: str = "manual") -> None:
    cfg = _load_config()
    cfg["sph_cookie"] = _encrypt_config_value(plain)
    cfg["sph_cookie_updated_at"] = _now_iso()
    cfg["sph_cookie_source"] = source
    _save_config(cfg)
```

**mask 行为**：加密后 `config.json` 存 `enc:gAAAAA...`，前端 `GET /api/config` 时 `_mask_config_for_response` 自动显示为 `"***"`（与 `llm_api_key` 行为一致，无需额外改造）。

### 2.2 运行时注入

**选 B：内存缓存 + 热更新**（与 wx-sph-parser 原生 `update_cookie` 一致）

- `sph_parser/config.py` 启动时从 `settings.get_sph_cookie()` 读取，存入模块变量 `SPH_COOKIE`
- `update_cookie(new_plain: str)` 同时做两件事：
  1. 写回 `config.json`（加密）
  2. 更新内存变量
- `get_cookie()` 函数读内存变量（不读盘）

### 2.3 热更新流程（手动 + Playwright 共用通道）

```
用户/UI 触发              API 端点                    后端动作
─────────────────────────────────────────────────────────────────
手动粘贴 cookie
  │
  └─► POST /api/channels/cookie  ──►  校验非空
       body: { cookie: "..." }        settings.set_sph_cookie(plain)
                                       sph_parser.update_cookie(plain)
                                       返回 { ok: true, updated_at: ... }
                                       
Playwright 抓取完成
  │
  └─► POST /api/channels/cookie  ──► 同上（同一端点）
       body: {                         额外：sph_cookie_source = "playwright"
         cookie: "...",
         source: "playwright"
       }
```

**为什么共用同一个端点**：鉴权、日志、加密逻辑只写一份；前端"刷新历史"统一记录来源；子进程无需绕过鉴权。

### 2.4 Playwright 子进程协议

#### 进程模型

```
[主进程 server/__main__.py]
   │  按需启动子进程（不打包进主 exe）
   ▼
[scripts/sph_cookie_refresher.py]
   │  Playwright Chromium（headed 模式）
   │  启动浏览器 → yuanbao.tencent.com → 引导登录 → 抓 cookie
   ▼
[POST 回主进程] /api/channels/cookie
   body: { cookie: "...", source: "playwright" }
```

#### 主进程调度端点

| 端点 | 方法 | 功能 |
|---|---|---|
| `/api/channels/cookie/refresh` | POST | 启动刷新子进程（幂等：已有任务在跑则返回 409） |
| `/api/channels/cookie/refresh-status` | GET | 查询刷新状态（`idle` / `running` / `success` / `failed`） |
| `/api/channels/cookie/refresh-cancel` | POST | 取消正在跑的子进程 |

#### 状态机

```
        POST /refresh
[IDLE] ────────────► [RUNNING]
   ▲                    │
   │                    ├─► success ─► [IDLE]  (cookie 已写入)
   │                    ├─► failed  ─► [IDLE]  (last_error 保留)
   │                    └─► timeout ─► [IDLE]  (默认 5 分钟超时)
   │                        cancel
   └─────────── POST /refresh-cancel ──────┘
```

#### 触发条件（决策 3 落地）

**起步只实现手动触发**（UI 按钮 + 解析失败兜底）：

```python
def _api_channels_cookie_refresh(handler, body):
    state = _sph_refresh_state
    if state["state"] == "running":
        return 409
    proc = subprocess.Popen(
        ["python", "scripts/sph_cookie_refresher.py"],
        stdin=subprocess.PIPE,
        env={**os.environ, "CALLBACK_URL": ..., "API_TOKEN": ...}
    )
    state.update(state="running", pid=proc.pid, started_at=now())
    return 202
```

**解析失败兜底**（可选，**建议先不做**）：在 `fetch_video_profile` 捕获到 401/403 时，标记 `sph_cookie_status="expired"`；前端轮询此状态并提示用户点击刷新。

#### 子进程脚本契约

```python
# scripts/sph_cookie_refresher.py
def run(cookie_callback_url: str, api_token: str, storage_state_path: str | None) -> int:
    """
    1. 启动 Playwright Chromium（headed）
    2. 尝试加载 storage_state（决策 3 推荐：复用登录态）
    3. 若已登录 → 跳到步骤 5
    4. 若未登录 → 提示用户在浏览器中扫码/输账号
    5. 等待登录完成（监听 network 响应中 hy_user 出现）
    6. 提取 hy_source / hy_user / hy_token 三个字段
    7. 拼成 cookie 字符串
    8. POST {cookie_callback_url} body={cookie, source:"playwright"} header=Authorization: Bearer {api_token}
    9. 保存 storage_state 到 {storage_state_path}（下次复用）
    10. 返回 0（成功）/ 非 0（失败）
    """
```

**headless 决策**：headed（YuanBao 大概率有反爬）。脚本启动时 `browser.launch(headless=False)`。

### 2.5 失效检测（决策 3-A 的"半自动"体现）

**前端轮询 + UI 提示**：

```
前端每 60 秒 GET /api/channels/cookie/status
   │
   ▼
{ exists: bool, age_seconds: int, source: "manual"|"playwright", last_error: string }
   │
   ▼
UI 显示状态卡片：
   - 未配置：红色"请配置 cookie"+ 粘贴框
   - 已配置：绿色"cookie 有效，更新于 X 分钟前"
   - 解析连续失败：黄色"可能已失效"+ 一键刷新按钮（调 /refresh）
```

`last_error` 来源：子进程失败时写入 `_sph_refresh_state.last_error`；解析失败时由 `fetch_video_profile` 调用方写入。

### 2.6 安全约束

| 风险 | 缓解 |
|---|---|
| Cookie 泄露到日志 | `sph_cookie` 字段不写 INFO/DEBUG 日志，仅 ERROR 时写 `***` 摘要 |
| 子进程被劫持 | `sph_cookie_refresher.py` 只接受 `CALLBACK_URL` 来自环境变量，不接受 body 里的 URL |
| 第三方子进程依赖主进程 token | token 从 stdin 传入（不通过 argv 暴露） |
| Storage state 文件落盘 | 路径 `data/sph/yuanbao_storage.json`，与 `config.json` 同套 gitignore；权限 0600 |

---

## Section 3：API 端点完整契约

所有端点挂在 `/api/channels/*` 下，统一由 `server/middleware/auth.py` 保护（与现有 `/api/config`、`/api/accounts/*` 一致）。

### 3.1 端点总览

| # | 路径 | 方法 | 功能 | 鉴权 | 幂等 |
|---|---|---|---|---|---|
| 1 | `/api/channels/parse_sph` | GET | 单链接解析 | ✅ Bearer | ✅ |
| 2 | `/api/channels/batch_parse` | POST | 批量解析（≤50 条） | ✅ Bearer | ✅ |
| 3 | `/api/channels/cookie` | POST | 更新/写入 cookie | ✅ Bearer | ✅ |
| 4 | `/api/channels/cookie` | GET | 查询 cookie 状态 | ✅ Bearer | ✅ |
| 5 | `/api/channels/cookie/refresh` | POST | 启动 Playwright 刷新 | ✅ Bearer | ❌（已有任务 409） |
| 6 | `/api/channels/cookie/refresh-status` | GET | 轮询刷新状态 | ✅ Bearer | ✅ |
| 7 | `/api/channels/cookie/refresh-cancel` | POST | 取消刷新 | ✅ Bearer | ✅ |
| 8 | `/api/channels/history` | GET | 查询解析历史 | ✅ Bearer | ✅ |
| 9 | `/api/channels/download` | POST | 立即下载已解析视频 | ✅ Bearer | ❌（返回 task_id） |

### 3.2 端点详细契约

#### #1 `GET /api/channels/parse_sph`

**Query**：`url: string`（必填，微信视频号 SPH 分享链接）

**Response 200**：
```json
{
  "ok": true,
  "data": {
    "author_info": {
      "nickname": "...", "head_img_url": "...", "auth_icon_url": "..."
    },
    "feed_info": {
      "video_url": "https://...encfilekey=...&token=...",
      "origin_video_url": "https://...encfilekey=...&token=...",
      "description": "...",
      "cover_url": "...",
      "like_count_fmt": "1.2万",
      "h264_video_info": { "video_url": "..." },
      "h265_video_info": { "video_url": "..." },
      "createtime": 1718000000
    }
  }
}
```

**错误码**：
| Status | Body | 触发条件 |
|---|---|---|
| 400 | `{"error": "url parameter is required"}` | `url` 缺失/空 |
| 400 | `{"error": "invalid sph url, must start with https://weixin.qq.com/sph/"}` | URL 格式校验失败 |
| 401 | `{"error": "cookie not configured", "code": "NO_COOKIE"}` | `sph_cookie` 未设置 |
| 502 | `{"error": "yuanbao parse failed: ...", "code": "PARSE_FAILED"}` | `parse_share_url` 失败 |
| 502 | `{"error": "feed info fetch failed: ...", "code": "FEED_FAILED"}` | `get_feed_info` 失败 |
| 504 | `{"error": "timeout", "code": "TIMEOUT"}` | 30s 超时 |

#### #2 `POST /api/channels/batch_parse`

**Body**：
```json
{ "urls": ["https://weixin.qq.com/sph/xxx1", ...], "max_concurrent": 3 }
```

**Response 200**：
```json
{
  "ok": true,
  "data": {
    "results": [
      { "url": "...", "ok": true,  "data": { ...解析结果... } },
      { "url": "...", "ok": false, "error": "feed info fetch failed: ..." }
    ],
    "summary": { "total": 2, "success": 1, "failed": 1 }
  }
}
```

**错误码**：400（缺失/超 50）、401（鉴权失败）

**并发控制**：`asyncio.Semaphore(max_concurrent)` 包裹 `fetch_video_profile`；任一失败不影响其他。

#### #3 `POST /api/channels/cookie`

**Body**：
```json
{ "cookie": "hy_source=web; hy_user=xxx; hy_token=xxx", "source": "manual" }
```

**校验**：`cookie` 必填非空；解析出三段（`hy_source` 含 `web`、`hy_user`/`hy_token` 非空）任一缺失 → 400

**Response 200**：
```json
{ "ok": true, "data": { "updated_at": "2026-06-15T14:23:11+08:00", "preview": "hy_source=web; hy_user=abc1***; hy_token=xyz***" } }
```

#### #4 `GET /api/channels/cookie`

**Response 200**：
```json
{ "ok": true, "data": { "exists": true, "updated_at": "...", "source": "manual", "age_seconds": 3725, "preview": "hy_source=web; hy_user=abc1***; hy_token=xyz***" } }
```

未配置时：`{ "ok": true, "data": { "exists": false, "source": null, "age_seconds": null, "preview": null } }`

#### #5 `POST /api/channels/cookie/refresh`

**Body**：无

**Response 202**（启动成功）：
```json
{ "ok": true, "data": { "state": "running", "pid": 12345, "started_at": "..." } }
```

**Response 409**（已有任务在跑）：同上 data + `error: "refresh already running"`

#### #6 `GET /api/channels/cookie/refresh-status`

**Response 200**：
```json
{ "ok": true, "data": { "state": "running", "pid": 12345, "started_at": "...", "finished_at": null, "last_error": null, "cookie_updated": false } }
```

**前端轮询节奏**：点击刷新后立即查一次，之后每 2s 轮询一次直到 `state ∈ {success, failed}`。

#### #7 `POST /api/channels/cookie/refresh-cancel`

**Response 200**：`{ "ok": true, "data": { "cancelled": true, "pid": 12345 } }`
**Response 409**：无任务在跑时。

**实现**：`os.kill(pid, SIGTERM)`（Windows 用 `proc.terminate()`）+ 等待 2s 后 `proc.kill()` 兜底。

#### #8 `GET /api/channels/history`

**Query**：`limit: int (默认 20, max 100)`、`offset: int (默认 0)`、`keyword: string (可选)`

**Response 200**：
```json
{ "ok": true, "data": { "items": [{ "id": "uuid", "sph_url": "...", "video_title": "...", "author_nickname": "...", "cover_url": "...", "video_url": "...", "downloaded": false, "downloaded_path": null, "parsed_at": "..." }], "total": 137, "limit": 20, "offset": 0 } }
```

#### #9 `POST /api/channels/download`

**Body**：
```json
{ "history_id": "uuid", "sph_url": "...", "quality": "best", "sub_langs": "zh-Hans,en" }
```

`history_id` 与 `sph_url` 二选一。

**Response 202**：
```json
{ "ok": true, "data": { "task_id": "uuid", "state": "queued", "output_path": "D:/videos/wechat-channels/2026-06-15_xxx.mp4" } }
```

**实现**：
1. 若是 `history_id`：从 SQLite 查 `video_url`
2. 若是 `sph_url`：先调 `fetch_video_profile`，再写 history，再下载
3. 把 `video_url` 交给现有 `batch_download()` 函数（**yt-dlp 路径**，与 Section 5 集成点一致）
4. 异步后台线程跑（不阻塞 HTTP 请求）
5. 下载完成后回写 `downloaded=true, downloaded_path=...`

### 3.3 错误码全局约定

| 类别 | Status 范围 | 含义 |
|---|---|---|
| 客户端错误 | 400 | 入参缺失/格式错 |
| 未授权 | 401 | 鉴权失败或 cookie 未配 |
| 资源冲突 | 409 | 重复操作（刷新已在跑） |
| 上游错误 | 502 | 微信/yuanbao API 失败 |
| 超时 | 504 | 网络超时 |

**响应体统一格式**：
```json
{ "ok": true, "data": { ... } }            // 成功
{ "ok": false, "error": "...", "code": "MACHINE_CODE", "data": { ...可选... } }  // 失败
```

与 `MonitorHandler._send_json` 风格一致。

### 3.4 鉴权复用

所有 9 个端点都套 `auth.py` 的 `MONITOR_API_TOKEN` 校验中间件。前端调用时从 `localStorage` 读 token，Header 加 `Authorization: Bearer <token>`。

---

## Section 4：frontend-vue 集成

### 4.1 路由与菜单

`frontend-vue/src/router/index.ts` 新增：

```ts
{
  path: '/channels',
  name: 'Channels',
  component: () => import('@/views/Channels/index.vue'),
  meta: { titleKey: 'channels.tabTitle', icon: 'videocam', requiresAuth: true }
}
```

侧边栏顺序：监控 / 账户 / 下载队列 / **视频号** / AI 设置 / 代理池 / ...

### 4.2 4 个子组件清单

```
frontend-vue/src/views/Channels/
├── index.vue                  # 主入口（4 个 Tab 容器，naive-ui n-tabs）
├── CookieStatus.vue           # 子模块 1：Cookie 状态
├── ParseHistory.vue           # 子模块 2：解析历史
├── BatchQueue.vue             # 子模块 3：批量下载队列
└── SingleParse.vue            # 子模块 4：单链接解析
```

### 4.3 子组件 1：CookieStatus.vue

#### UI 结构

```
┌─────────────────────────────────────────────────────┐
│  Cookie 状态                                         │
├─────────────────────────────────────────────────────┤
│  [● 绿色徽章]  已配置   更新于 12 分钟前   来源：手动  │
│  Preview: hy_source=web; hy_user=abc1***; hy_token=xyz*** │
│                                                      │
│  ┌─ 手动更新 ─────────────────────────────┐         │
│  │ [textarea: 粘贴新 cookie]              │         │
│  │ [保存]                                  │         │
│  └────────────────────────────────────────┘         │
│                                                      │
│  ┌─ Playwright 自动刷新 ──────────────────┐         │
│  │ [刷新状态: idle]  [开始刷新]            │         │
│  │ 子进程 PID: 12345  (running 时显示)      │         │
│  │ 上次错误: null                          │         │
│  └────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────┘
```

#### 关键交互

| 元素 | 行为 |
|---|---|
| 状态徽章 | 60s 轮询 `GET /api/channels/cookie` |
| Cookie 文本框 | 三段格式校验（前端 + 服务端） |
| 保存按钮 | `POST /api/channels/cookie`，成功后刷新徽章 + toast |
| 刷新按钮 | `POST /api/channels/cookie/refresh`，启动后切到 2s 轮询 `/refresh-status` |
| 取消按钮 | `POST /api/channels/cookie/refresh-cancel`（仅 running 状态显示） |

### 4.4 子组件 2：ParseHistory.vue

```
┌─────────────────────────────────────────────────────┐
│  解析历史                          [搜索框: 关键字]   │
├─────────────────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │ 封面缩略 │ │ 封面缩略 │ │ 封面缩略 │ │ 封面缩略 │   │
│  │ 标题     │ │ 标题     │ │ 标题     │ │ 标题     │   │
│  │ 作者     │ │ 作者     │ │ 作者     │ │ 作者     │   │
│  │ 14:30    │ │ 14:25    │ │ 14:20    │ │ 14:15    │   │
│  │ [下载]   │ │ [已下载] │ │ [下载]   │ │ [失败]   │   │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘   │
│                                                      │
│              [< 上一页]  1/7  [下一页 >]              │
└─────────────────────────────────────────────────────┘
```

- 网格布局（`n-grid` 4 列响应式）
- 卡片：封面图（`feed_info.cover_url` lazy load）+ 标题 + 作者 + 解析时间 + 状态徽章
- 操作：未下载显示"下载"按钮；已下载显示文件名 + 文件大小（hover 提示本地路径）
- 点击卡片中央播放按钮 → 调 `video.js` 弹窗预览（复用 `video.js 8.10.0`）
- 默认 `limit=20, offset=0`，滚动加载（`n-infinite-scroll`）
- 搜索框 debounce 300ms

### 4.5 子组件 3：BatchQueue.vue

```
┌─────────────────────────────────────────────────────┐
│  批量下载队列                                        │
├─────────────────────────────────────────────────────┤
│  [粘贴多个链接，每行一个]                            │
│  ┌──────────────────────────────────────────┐       │
│  │ https://weixin.qq.com/sph/xxx1           │       │
│  │ https://weixin.qq.com/sph/xxx2           │       │
│  │ https://weixin.qq.com/sph/xxx3           │       │
│  └──────────────────────────────────────────┘       │
│  质量: [best ▾]   字幕: [zh-Hans,en]                 │
│  [开始批量下载]  [清空]                              │
│                                                      │
│  队列状态:                                            │
│  ┌────────────────────────────────────────┐         │
│  │ ● 解析中  xxx1  (12s)                 │         │
│  │ ● 已就绪  xxx2  → D:/videos/...        │         │
│  │ ● 下载中  xxx2  45% [===>     ]        │         │
│  │ ● 失败    xxx3  yuanbao parse failed   │         │
│  │ ✓ 完成    xxx4  28MB                   │         │
│  └────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────┘
```

- 链接文本框：粘贴按行拆分；自动去重；最多 50 条
- 开始按钮：`POST /api/channels/batch_parse` 拿 URL → 视频 URL 列表后逐条 `POST /api/channels/download`
- 队列行 5 状态机：解析中 / 已就绪 / 下载中 / 完成 / 失败
- 进度条：轮询 `GET /api/download-tasks/{id}`（复用现有端点）

### 4.6 子组件 4：SingleParse.vue

```
┌─────────────────────────────────────────────────────┐
│  单链接解析                                          │
├─────────────────────────────────────────────────────┤
│  [输入框: https://weixin.qq.com/sph/xxx]            │
│  [解析]                                              │
│                                                      │
│  解析结果:                                            │
│  ┌──────────────────────────────────────┐           │
│  │  [封面]  标题: ...                   │           │
│  │          作者: ...   点赞: 1.2万      │           │
│  │          时长: 00:42   时间: 06-14    │           │
│  │                                       │           │
│  │  视频源:                              │           │
│  │    1080p (H264): [下载]              │           │
│  │    1080p (H265): [下载]              │           │
│  │    原始 URL: [复制]                  │           │
│  └──────────────────────────────────────┘           │
└─────────────────────────────────────────────────────┘
```

- 输入框：URL 格式校验（前端 + 后端）
- 解析按钮：`GET /api/channels/parse_sph?url=...`
- 下载按钮：`POST /api/channels/download` body=`{ sph_url, quality }`；下载后跳转 ParseHistory 卡片
- 复制按钮：`navigator.clipboard.writeText(originVideoUrl)`
- 错误展示：
  - 401/NO_COOKIE → 跳转 `CookieStatus` Tab 并 toast
  - 502/PARSE_FAILED → 行内显示，提示刷新 cookie
  - 504/TIMEOUT → 行内显示，建议重试

### 4.7 i18n 词条（49 词条 × 2 语言）

`frontend-vue/src/i18n/locales/zh-CN.json` 与 `en-US.json` 同步新增。

#### 中文

```json
{
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
}
```

#### 英文（结构对齐）

```json
{
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
}
```

### 4.8 状态管理总图

| Store | 作用域 | 持久化 | 备注 |
|---|---|---|---|
| `channels` | 解析历史列表 | ❌（每次 mount 重新拉） | 轻量，避免 Pinia 持久化插件依赖 |
| `sphCookie` | cookie 状态 + 刷新状态 | `localStorage` 缓存 status | Pinia + pinia-plugin-persistedstate（若项目已装） |
| `sphQueue` | 批量队列 | ❌（刷新页面即清空） | 队列是临时任务，无需持久化 |

**核查点**（实施时）：`pinia-plugin-persistedstate` 是否已在 `package.json`？若未装，cookie 状态只在内存中也行（每次打开 Tab 重新 `GET /api/channels/cookie`）。

### 4.9 复用现有依赖确认

| 需求 | 现有依赖 | 满足 |
|---|---|---|
| HTTP 客户端 | `axios 1.6.0` | ✅ |
| UI 组件 | `naive-ui 2.38.2` | ✅ |
| 图标 | `@vicons/ionicons5 0.13.0` | ✅ |
| 视频预览 | `flv.js 1.6.2` / `video.js 8.10.0` | ✅ |
| 状态管理 | `pinia 2.1.0` | ✅ |
| 国际化 | `vue-i18n 9.10.0` | ✅ |
| 路由 | `vue-router 4.3.0` | ✅ |
| 时间格式化 | ❌ 用 `Intl.RelativeTimeFormat()` 避免引依赖 | ✅ |

**结论**：frontend-vue 不需要新装 npm 包。

### 4.10 与 monitor_web 的边界

| 维度 | frontend-vue（本次） | monitor_web（不动） |
|---|---|---|
| 视频号 UI | 新增 4 个组件 | 不动（避免双前端维护） |
| Cookie 配置 | 走 `/api/channels/cookie` | 暂不集成（待 frontend-vue 稳定后再说） |
| 后端端点 | 服务端共享 | 共享 |

---

## Section 4.5：前端视觉一致性约束

### 4.5.1 结论

视频号 Tab **不重设计**，**仅采用现有 token + 组件类**。项目 frontend-vue 已有完整落地的 Anthropic 风格设计系统（DESIGN.md 的工程化映射）。

### 4.5.2 既有设计基础设施

**`frontend-vue/tailwind.config.js`** 完整覆盖 Tailwind 默认灰阶为 Claude 暖色（`gray.50~950`、`terracotta.DEFAULT/hover/pressed/dim/ring`、`parchment`、`ivory`、`border-cream`、`warm-sand`、`olive-gray`、`charcoal-warm`、`near-black`）。

**`frontend-vue/src/styles/variables.css`** 定义 ~70 个 CSS 变量：表面层级、文字、强调色、焦点蓝、8 档圆角、阴影、字体（Georgia serif 标题、Inter sans 正文、JetBrains Mono 代码）。

**`frontend-vue/src/styles/layout.css`** 完整实施：app 骨架、侧栏、页头、`page-header / page-title / page-desc`、`.card` 容器族、`.status-badge--ok/warn/err/accent`、`.pill`、`.empty-state`、`.text-link`、`.divider`、`.back-link`、Naive UI 暖色重写、3 档响应式（900/760/520px）、`prefers-reduced-motion` 降级。

### 4.5.3 视频号 4 个子组件的对齐规则

| 现有 token / 类 | 视频号 Tab 用在哪 |
|---|---|
| `.page-header` / `.page-title` / `.page-desc` | `index.vue` 顶部 |
| `.card` / `.card-header` / `.card-title` / `.card-title-icon` | 4 个子组件各自的容器 |
| `.status-badge--ok` | Cookie 已配置、下载完成 |
| `.status-badge--warn` | Cookie 可能失效、解析重试中 |
| `.status-badge--err` | Cookie 未配、解析失败 |
| `.status-badge--accent` | 状态徽章强调（cookie 来源：手动/Playwright） |
| `.pill` / `.pill--active` | 质量选择、刷新按钮组 |
| `.empty-state` / `.empty-state__icon` | "暂无解析记录" |
| `.text-link` | "复制 URL"、"跳到 Cookie 配置" |
| `.divider` | 子组件内分组 |
| `NButton type="primary"` | 开始解析、开始批量下载、保存 cookie |
| `NButton`（默认） | 次级操作（取消、清空） |
| `NInput type="textarea"` | cookie 粘贴框 |
| `NInput` | 单链接输入 |
| `NSelect` | 质量、字幕语言下拉 |
| `NIcon` + `@vicons/ionicons5` | 全部图标 |
| `.card` 网格（推荐）/ `n-data-table` | ParseHistory 列表（推荐 card 网格，更杂志感） |
| 语义类前缀 `.sph-*` | 仿 `.bd-*`（如 `.sph-form-row` / `.sph-label`） |
| `t('channels.xxx')` | i18n（见 §4.7） |
| `--font` (Georgia) | 页面/卡片标题 |
| `--font-sans` (Inter) | 正文、按钮、输入 |
| `--accent` (terracotta) | 主 CTA、active 状态 |
| `--text-dim` (Stone Gray) | "更新于 12 分钟前"类辅助文字 |

### 4.5.4 应回避的反模式

| 反模式 | 替代 |
|---|---|
| ❌ 使用 Naive UI 默认蓝紫色 | ✅ 用 layout.css 已重写的暖色版 |
| ❌ 卡片用直角（`border-radius: 0`） | ✅ `border-radius: 20px`（与 `.card` 一致） |
| ❌ 用 emoji 🎬/⚙️ 做图标 | ✅ `<NIcon><Videocam /></NIcon>` |
| ❌ 标题用 sans 字体 | ✅ Georgia serif 32px（DESIGN.md "Anthropic Serif" 替代） |
| ❌ 单独写一套深色/灰色配色 | ✅ 用 `--text-dim / --text-muted / --surface3` 三档灰 |
| ❌ 进度条用蓝色 | ✅ 用 `--accent` terracotta |
| ❌ Hover 时 scale 放大引起布局抖动 | ✅ layout.css 全局 `transition: ... 160ms ease`（无 transform） |
| ❌ Cookie / api key 直接显示在 UI | ✅ 同 `llm_api_key` 模式：mask 后显示 `***`，编辑时清空字段 |
| ❌ 自创 `--my-color-1` 等变量 | ✅ 用现有 `--accent / --surface / --border-medium` 等 |

### 4.5.5 ui-ux-pro-max Pre-Delivery Checklist

| 项 | 状态 | 说明 |
|---|---|---|
| 无 emoji 图标 | 需执行 | 用 `@vicons/ionicons5` |
| 统一 icon 尺寸 | 已有 | layout.css `width:18px; height:18px` |
| Hover 无 layout shift | 已有 | `transition` 全部用 color/background/opacity |
| Cursor pointer | 已有 | `.pill` / `.card-title` 等已加 |
| Focus 状态可见 | 已有 | `:focus-visible { outline: 2px solid var(--focus) }` |
| Light mode 对比度 | 已有 | `--text` on `--surface` = 16.8:1（远超 4.5:1） |
| 悬浮元素 spacing | 已有 | `.sidebar` `top: 22px` |
| 无内容被 nav 遮挡 | 已有 | sticky header 60px 已计入 |
| max-width 一致 | 已有 | `var(--content-max-width, 1180px)` |
| A11y alt 文本 | 需执行 | 封面图加 `alt`、icon-only 按钮加 `aria-label` |
| 颜色非唯一指示 | 需执行 | 状态徽章加文字，不仅靠颜色 |
| Touch target ≥ 44px | 已有 | `.sidebar__item` 44px、按钮 padding ≥ 8px |
| `prefers-reduced-motion` | 已有 | layout.css 末尾已加全局降级 |
| 表单 label | 需执行 | `<label for>` 或 `aria-label` |
| Responsive 375/768/1024/1440 | 已有 | layout.css 三档断点已写 |

**唯一需主动执行的项**：无 emoji、alt/aria、状态文字冗余。其余 13 项已就绪。

### 4.5.6 改造范围

| 类别 | 工作量 |
|---|---|
| 不重设计 | 0（直接用现有 token） |
| 新增语义类（layout.css 末尾追加） | ~30 行（`.sph-form-row` / `.sph-label` / `.sph-config-grid` 仿 `.bd-*`） |
| 新增 i18n 词条 | 已规划（§4.7） |
| a11y 微调 | 跟随实现（alt / aria-label / 状态文字冗余） |
| Playwright 启动指示器 | 1 个（`n-progress` 或自绘 terracotta 进度条） |

**总改造量**：相比"重设计"节省 ~80% 工作量，4 个子组件直接用现有 layout 模式实现。

---

## Section 5：数据库 + 后端分层 + 集成点 + 测试 + 风险

### 5.1 数据库 Schema

新增 SQLite 表 `sph_parse_history`（与现有 `monitor.db` 同库）：

```sql
CREATE TABLE IF NOT EXISTS sph_parse_history (
    id                TEXT PRIMARY KEY,        -- uuid
    sph_url           TEXT NOT NULL,           -- 原始 SPH 链接
    video_title       TEXT,                    -- feed_info.description
    author_nickname   TEXT,                    -- author_info.nickname
    cover_url         TEXT,                    -- feed_info.cover_url
    video_url         TEXT NOT NULL,           -- 完整 origin_video_url（含 encfilekey+token）
    description       TEXT,                    -- 完整 description
    downloaded        INTEGER NOT NULL DEFAULT 0,  -- 0/1
    downloaded_path   TEXT,                    -- 已下载时填
    downloaded_at     TEXT,                    -- ISO8601
    parse_status      TEXT NOT NULL DEFAULT 'success',  -- success / failed
    parse_error       TEXT,                    -- 失败原因
    parsed_at         TEXT NOT NULL            -- ISO8601
);

CREATE INDEX IF NOT EXISTS idx_sph_parsed_at ON sph_parse_history(parsed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sph_downloaded ON sph_parse_history(downloaded);
CREATE INDEX IF NOT EXISTS idx_sph_title_keyword ON sph_parse_history(video_title);
```

**接入点**：`monitor/db.py` 启动时执行 `CREATE TABLE IF NOT EXISTS`。

**为什么不存 cookie**：cookie 已在 `config.json` 加密，分开存表只会增加泄露面。

### 5.2 后端实现分层

新增 3 个 Python 文件，统一在 `server/sp_modules/sph_parser/` 下：

```
server/sp_modules/sph_parser/
├── __init__.py
├── core.py              # 核心业务（从 wx-sph-parser/app/sph.py 移植，函数签名不变）
├── config.py            # SPH_COOKIE 模块变量 + update_cookie() 热更新
├── schemas.py           # Pydantic 模型（与 wx-sph-parser 保持一致）
└── routes.py            # 9 个 FastAPI 路由（被 server/__main__.py 启动时 mount）
```

**集成模式**：`server/__main__.py` 启动时 import：
```python
from server.sp_modules.sph_parser import routes as sph_routes
app.include_router(sph_routes.router, prefix="/api/channels", tags=["channels"])
```

### 5.3 集成到现有 `batch_download` 的统一视频分支（行 6027）

**现状**（行 5998-6067）：
```python
# ── 通用视频 → yt-dlp 下载 ────────────────────────────────
# 构造视频页面 URL 供 yt-dlp 使用（yt-dlp 可自动重试并获取最新 CDN URL）
download_url = video_url
...
# 后台线程执行 yt-dlp 下载
def _bg_yt_dlp():
    try:
        batch_download([download_url], ...)
    ...
threading.Thread(target=_bg_yt_dlp, daemon=True).start()
```

**改造**：在 `download_url` 赋值之前加 SPH 链接识别分支：

```python
# server/__main__.py 改造点（伪代码）
if video_url.startswith("https://weixin.qq.com/sph/"):
    # SPH 链接 → 先解析 → 拿到 origin_video_url
    from server.sp_modules.sph_parser.core import fetch_video_profile
    from config.settings import get_sph_cookie
    profile = await fetch_video_profile(video_url, get_sph_cookie())
    download_url = profile["data"]["feedInfo"]["originVideoUrl"]
    # 同步写一条 history（sph_url, video_url, ...）
    # 然后走原有的 batch_download(...) 路径
```

**为什么不另起炉灶写"专门给 SPH 的下载器"**：yt-dlp 处理视频下载本身已成熟，重复实现是浪费；唯一差异是 URL 来源。

### 5.4 测试策略

#### 单元测试（`tests/test_sph_parser_unit.py`）

- `test_clean_video_url()`：URL 清洗（保留 encfilekey + token）
- `test_generate_rid()`：rid 格式（hex 时间戳 + 8 位 hex）
- `test_update_cookie_memory()`：内存变量与 config.json 一致
- `test_mask_config_for_response_with_sph_cookie()`：mask 后值 = `***`
- `test_set_sph_cookie_encryption()`：加密值以 `enc:` 开头，明文可解密还原

#### 集成测试（`tests/test_sph_api_contract.py`）

- `test_parse_sph_url_validation()`：400 错误码路径
- `test_parse_sph_no_cookie_401()`：未配 cookie
- `test_parse_sph_with_cookie_mocked_httpx()`：mock httpx 返回
- `test_batch_parse_concurrency()`：≤50 条并发解析
- `test_cookie_post_validation()`：三段格式校验
- `test_history_pagination()`：limit/offset/keyword

#### 子进程测试（`tests/test_sph_cookie_storage.py`）

- `test_refresh_state_transitions()`：idle → running → success/failed
- `test_refresh_idempotent_409()`：已有任务时返回 409
- `test_refresh_cancel_running()`：可取消并清理

#### Mock 策略

- `httpx.AsyncClient` 全 mock（不真正调微信 API）
- SQLite 用 `tmp_path` fixture，每个测试独立 DB
- `config.json` 测试前后用 backup/restore
- 子进程脚本测试用 `monkeypatch` 替换 `subprocess.Popen`

#### 覆盖率目标

- `server/sp_modules/sph_parser/`：≥ 80%
- 新增的 9 个路由 handler：≥ 70%（mock httpx 困难的部分允许降）

### 5.5 关键风险与缓解

| # | 风险 | 严重度 | 缓解 |
|---|---|---|---|
| 1 | 腾讯对 SPH 解析有反爬指纹（`sph.py` 硬编码的 `x-t-userid`/`x-id`/`x-hy92` 等 20+ header），cookie 失效快 | P0 | 实施时第一周单独跑 PoC：拿真 cookie 跑通后再开始集成；不通过则降级到 Playwright 自动续期 |
| 2 | 解析出的 `videoUrl` 含 `encfilekey` + `token`，可能短期有效 | P0 | 解析后立即 yt-dlp 下载（决策 4），不存 URL 留给用户自己下 |
| 3 | Playwright 头部指纹过严，被 yuanbao 识别为机器人 | P1 | 起步用 headed + 人工完成首次登录；storage_state 复用；如失败给用户清晰错误信息 |
| 4 | `server/__main__.py` 已 6357 行，新加 9 个路由会进一步膨胀 | P1 | 路由全部在 `sph_parser/routes.py` 独立文件，main 只 import + include |
| 5 | Playwright 子进程死锁/僵尸 | P1 | 主进程启动子进程时记录 pid，监控心跳；超时 5 分钟自动 SIGTERM → SIGKILL |
| 6 | `pinia-plugin-persistedstate` 未装导致前端持久化失败 | P2 | 实施前先检查 package.json；未装则降级为纯内存 |
| 7 | FastAPI 未在主 requirements.txt 中显式列出 | P2 | 实施前 grep 确认；若缺则添加到 requirements.txt |
| 8 | i18n 漏条目导致前端显示 raw key | P2 | 实施时跑 `frontend-vue t('channels.xxx')` 覆盖率检查 |
| 9 | 主进程被 kill 时子进程残留 | P2 | 注册 `atexit` 钩子清理子进程 |
| 10 | config.json 误提交含真实 cookie | P2 | `.gitignore` 已含 `config.json`（commit 2/2 完成时已验证） |

### 5.6 回滚方案

**最小回滚粒度**：单一 revert commit

1. **后端回滚**：`git revert <feature commit 1>..<feature commit N>`，主进程启动时检测到 `sph_parser` import 失败 → 自动跳过（用 try/except 包裹 include_router）
2. **前端回滚**：删除 `frontend-vue/src/views/Channels/` 目录 + 移除 router 中 `/channels` 路由 + 删除 i18n 词条
3. **数据库回滚**：`DROP TABLE IF EXISTS sph_parse_history;`（不破坏现有 monitor.db）
4. **配置文件回滚**：从 `config.json` 移除 `sph_cookie*` 4 个字段（其他用户配置不受影响）

**回滚后功能**：YouTube 监控 + 批量下载 + 其他 Tab 完全不受影响（验证：`grep -r "sph" server/__main__.py` 应无业务代码调用）。

### 5.7 验证清单（实施完成前自检）

- [ ] `python -m pytest tests/test_sph_*` 全绿
- [ ] `python -m pytest tests/ -k "not sph"` 全绿（无回归）
- [ ] 端到端 PoC：真 SPH 链接 + 真 cookie + 解析 + yt-dlp 下载 → 视频文件存在
- [ ] Playwright PoC：用户首次 headed 登录 → 抓 cookie → 写 config.json → 主进程用新 cookie 解析成功
- [ ] 前端：4 个子组件 `vue-tsc` 类型检查通过
- [ ] 前端：`vite build` 产物可加载，无 console error
- [ ] i18n 49 词条 × 2 语言全部命中（无 raw key）
- [ ] a11y：键盘 Tab 顺序合理，aria-label 完整
- [ ] 响应式：375 / 768 / 1024 / 1440 四档截图无破版
- [ ] `.gitignore` 已含 `data/sph/`
- [ ] `wx-sph-parser/README_DEV.md` 已写明"集成后仅作 dev 参考"
- [ ] PyInstaller 打包脚本确认未打包 playwright（如有.spec 需更新）

---

## 附录 A：依赖与不依赖项

### A.1 Python 后端新增依赖

**已有**（无需新增）：`fastapi`（待核查 main requirements）、`httpx 0.28.1`、`pydantic`（待核查 v2）

**新增**（仅 playwright 子进程需要）：`playwright>=1.40`

**重要**：playwright 不打包进主 PyInstaller exe。子进程由 `python scripts/sph_cookie_refresher.py` 启动，用系统 Python 环境。

### A.2 frontend-vue 新增依赖

**无**（所有功能用现有依赖覆盖，见 §4.9）。

### A.3 系统级要求

- Python ≥ 3.12
- 浏览器二进制：playwright install chromium（首次运行触发，~150MB 下载到 `~/.cache/ms-playwright/`）

---

## 附录 B：变更文件总清单（按 commit 拆分）

| Commit | 文件 | 说明 |
|---|---|---|
| #1 `chore(config)` | `config/settings.py` | +sph_cookie 加解密钩入 |
| #1 | `config/schema.json`（或 template） | +sph_cookie 4 字段定义 |
| #2 `feat(sp_modules)` | `server/sp_modules/sph_parser/__init__.py` | 新增 |
| #2 | `server/sp_modules/sph_parser/core.py` | 从 wx-sph-parser 移植 + 微调 |
| #2 | `server/sp_modules/sph_parser/config.py` | 改用 config.json 读取 |
| #2 | `server/sp_modules/sph_parser/schemas.py` | 原样移植 |
| #2 | `server/sp_modules/sph_parser/routes.py` | 9 个 FastAPI 路由 |
| #3 `feat(server)` | `server/__main__.py` | +import + include_router + 通用视频分支识别 SPH |
| #4 `feat(playwright)` | `scripts/sph_cookie_refresher.py` | 新增子进程脚本 |
| #5 `feat(frontend-vue)` | `frontend-vue/src/views/Channels/` ×4 | 4 个子组件 |
| #5 | `frontend-vue/src/api/channels.ts` | API 封装 |
| #5 | `frontend-vue/src/stores/sphCookie.ts` | cookie 状态管理 |
| #5 | `frontend-vue/src/stores/sphQueue.ts` | 批量队列状态 |
| #5 | `frontend-vue/src/router/index.ts` | +/channels 路由 |
| #5 | `frontend-vue/src/i18n/locales/{zh-CN,en-US}.json` | +49 词条 |
| #5 | `frontend-vue/src/styles/layout.css` | 末尾追加 ~30 行 .sph-* 语义类 |
| #6 `test(sp_modules)` | `tests/test_sph_parser_unit.py` | 单元测试 |
| #6 | `tests/test_sph_api_contract.py` | API 集成测试 |
| #6 | `tests/test_sph_cookie_storage.py` | 子进程协议测试 |
| #7 `docs(dev)` | `wx-sph-parser/README_DEV.md` | 说明集成后定位 |
| #7 | `.gitignore` | 追加 `data/sph/` |

---

## 附录 C：术语表

| 术语 | 含义 |
|---|---|
| SPH | 微信视频号分享链接格式（`https://weixin.qq.com/sph/xxx`） |
| Cookie 三段 | `hy_source` / `hy_user` / `hy_token`（从 yuanbao.tencent.com 抓取） |
| encfilekey + token | 微信视频 API 返回的视频 URL 中的两个关键参数，缺一不可 |
| Storage state | Playwright 的登录态保存文件（复用下次免登录） |
| Mask sentinel | 服务端 GET `/api/config` 时把已存密钥 mask 为 `***`，前端识别它为"未重新输入"信号 |
| 主进程 / 子进程 | 主进程 = `server/__main__.py`；子进程 = `scripts/sph_cookie_refresher.py`（独立 Python 进程） |
| .sph-* 语义类 | 仿 `.bd-*`（BatchDownload 命名）的 SPH Tab 内部组件类前缀 |

---

**Spec 状态**：完整 5 个 Section + 1 个视觉约束子节 + 3 个附录，均已通过用户 review。

**下一步**：用户 review 本文档后，进入 `superpowers:writing-plans` skill 产出实施计划（按 commit 拆分任务）。
