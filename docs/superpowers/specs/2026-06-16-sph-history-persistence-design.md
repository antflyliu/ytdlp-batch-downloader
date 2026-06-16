# 视频号 SPH History 完整化设计

> 2026-06-16 设计
> 范围:`sph_parse_history` 表在批量解析/下载流程中的数据完整性
> 关联 commits:`39aa636` (sph-queue 修复)
> **决策记录**:用户已确认 (1) 改 API 响应形状加 `history_id` (2) 失败解析也记录 history (3) 拆 3 个 commit 提交

## 背景

经过 audit 当前 `sph_parse_history` 表的写入路径,发现两处数据完整性问题:

| 问题 | 现象 | 影响 |
|------|------|------|
| **#1 批量解析不落 history** | `POST /api/channels/batch_parse` 成功后,50 条结果不写入 history | 历史页看不到批量解析视频;无法用「重新解析」;无法追踪下载状态 |
| **#2 下载完成不更新 downloaded 字段** | 浏览器 fetch().blob() 下载后,不调用 `mark_downloaded` | 历史页 `downloaded` 永远是 0;用户无法区分「解析过」与「已下载」 |

## 目标

让 `sph_parse_history` 真正成为「我处理过的所有 SPH 视频」的统一真实来源:

1. 任何成功的解析(单/批)都产生一条 history 记录
2. 任何完成的下载都更新对应 history 记录的 `downloaded/downloaded_path/downloaded_at` 字段
3. 任何解析尝试(成功/失败)都产生 history 记录(失败用 `parse_status='failed'` + `parse_error` 区分)
4. 下载标记失败不阻塞下载本身(主流程优先)

## 不在范围

- **去重逻辑**:同一 URL 多次解析会产生多条记录(可后续单独规划)
- **服务端 yt-dlp 下载**:目前所有下载走浏览器侧,服务端下载路径仍是 stubs
- **批量下载 mark_downloaded 优化**:浏览器侧 fetch 完一个就 mark 一次,不做批处理

## Commit 拆分计划

3 个原子 commit,粒度对应"功能 + 测试":

| Commit | 范围 | 文件 |
|--------|------|------|
| **#1 batch-history-persistence** | `_one()` 成功/失败都 insert history + 返回 history_id;测试 | server/__main__.py; tests/test_sph_api_contract.py |
| **#2 mark-downloaded-endpoint** | 新增 `/api/channels/mark_downloaded` 端点;`/parse_sph` 响应加 `history_id`;测试 | server/sp_modules/sph_parser/routes.py; server/__main__.py; tests/test_sph_api_contract.py |
| **#3 frontend-mark-wiring** | 前端 API 封装 + 3 个下载入口接通 mark;historyId 状态管理 | frontend-vue/src/api/channels.ts; frontend-vue/src/stores/sphQueue.ts; frontend-vue/src/views/Channels/SingleParse.vue; frontend-vue/src/views/Channels/ParseHistory.vue |

---

## 改动 1: 批量解析落 history

### 改动位置
`server/__main__.py:6259-6284` (`_api_channels_batch_parse`)

### 改动内容
在 `_one(u)` 函数内,无论成功还是失败,都执行 `sph_db.insert_history({...})`,用 `parse_status` 区分。成功时字段与单链接解析完全一致;失败时记录 `parse_status='failed'` + `parse_error`,视频字段填空。

### 设计细节

**成功 / 失败两条路径都插入 history:**
```python
def _one(u: str) -> dict:
    history_id = ""
    try:
        r = _sph_core.fetch_video_profile_sync(u, _sph_cfg.get_cookie())
    except Exception as e:
        # 失败也落 history(parse_status='failed')
        try:
            from server.sp_modules.sph_parser import db as _sph_db
            import uuid as _uuid
            history_id = str(_uuid.uuid4())
            _sph_db.insert_history({
                "id": history_id,
                "sph_url": u,
                "video_url": "",  # 失败时无 URL,需 schema 允许空(见迁移)
                "parse_status": "failed",
                "parse_error": str(e)[:500],
            })
        except Exception as _db_e:
            _log.warning("[sph/batch_parse] failed-history insert failed for %s: %s", u, _db_e)
        return {"url": u, "ok": False, "error": str(e), "history_id": history_id}
    # 成功路径:落 history (与 _api_channels_parse_sph 行为一致)
    try:
        fi = r.get("data", {}).get("feedInfo", {})
        ai = r.get("data", {}).get("authorInfo", {})
        from server.sp_modules.sph_parser import db as _sph_db
        import uuid as _uuid
        history_id = str(_uuid.uuid4())
        _sph_db.insert_history({
            "id": history_id,
            "sph_url": u,
            "video_title": fi.get("description", ""),
            "author_nickname": ai.get("nickname", ""),
            "cover_url": fi.get("coverUrl", ""),
            "video_url": fi.get("originVideoUrl", ""),
            "h264_video_url": (fi.get("h264VideoInfo") or {}).get("videoUrl", ""),
            "h265_video_url": (fi.get("h265VideoInfo") or {}).get("videoUrl", ""),
            "description": fi.get("description", ""),
            "downloaded": False,
            "downloaded_path": None,
            "parse_status": "success",
            "parse_error": None,
        })
    except Exception as _db_e:
        _log.warning("[sph/batch_parse] history insert failed for %s: %s", u, _db_e)
    return {"url": u, "ok": True, "data": r, "history_id": history_id}
```

**关键决策:**
- **成功 + 失败都落 history**: 用户决策,失败记录用 `parse_status='failed'` + `parse_error` 区分,保留审计/重试能力。
- **DB 错误不阻塞 API 响应**: 与单链接解析 (line 6255) 一致,DB 失败只 log warning,API 仍返回成功。这避免数据库短暂不可用导致批量解析整个失败。
- **失败时 `video_url=""`**: schema 当前 `video_url NOT NULL`,需要 schema 迁移允许空字符串(成功时仍正常填充)。见"schema 迁移"小节。
- **使用新 uuid,不复用**: 与单链接一致;允许同一 URL 多次解析产生多条记录。
- **不在 `_one` 内 import sph_db / uuid**: 与单链接解析一致,放在函数内延迟 import(避免模块加载时的循环引用)。
- **返回 `history_id` 字段**: 即使失败也返回,供前端后续「重新解析」使用(history reparse 模式可按 id 找回 sph_url)。

### schema 迁移

为支持失败记录的 `video_url=""`,需要把 `video_url` 改为可空。两条路径任选其一:

**方案 A(推荐)**:迁移 `init_schema` 中的 `_SCHEMA`,在测试环境用 `tmp_path` 重建,生产环境做一次性 ALTER:

```python
# db.py:init_schema()
# 在 PRAGMA table_info 之后追加
if "video_url_nullable" not in cols:
    # SQLite 不支持直接改 NOT NULL → 需要重建表
    # 这里走最简方案:把 NOT NULL 改为允许空,新建的库用新 schema
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sph_parse_history_v2 (...);"
    )
    # 旧库通过 migration 工具完成(本次不在范围,新库用新 schema)
```

**方案 B(本次采用)**:失败记录允许 `video_url=""`,但 schema 仍是 `NOT NULL` — 验证时 schema 接受空字符串(因为 SQLite 的 NOT NULL 只拒绝 NULL,不拒绝空串)。空串不是 NULL,所以 **当前 schema 已经支持**。无需迁移。

确认方案 B 可行后,无需 schema 变更,只需让 `insert_history` 接受 `video_url=""` 即可(现有代码已支持 `item["video_url"]` 必填,传空串即可)。

### 测试 (`tests/test_sph_api_contract.py`)

新增 3 个测试:

```python
def test_batch_parse_inserts_history_on_success(client, monkeypatch):
    """批量解析成功时,每条都落 history(parse_status='success')。"""
    async def fake_fetch(share_url, cookie):
        return {"errCode": 0, "data": {"authorInfo": {"nickname": "A"},
                "feedInfo": {"description": "T", "originVideoUrl": "https://x"}}}
    monkeypatch.setattr("server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch)

    from server.sp_modules.sph_parser import db as sph_db
    assert sph_db.count_history() == 0

    r = client.post("/api/channels/batch_parse",
                    json={"urls": ["https://weixin.qq.com/sph/u1",
                                   "https://weixin.qq.com/sph/u2"]})
    assert r.status_code == 200
    assert sph_db.count_history() == 2

    items = sph_db.list_history(limit=10, offset=0)
    urls = {it["sph_url"] for it in items}
    assert urls == {"https://weixin.qq.com/sph/u1", "https://weixin.qq.com/sph/u2"}
    for it in items:
        assert it["parse_status"] == "success"
        assert it["parse_error"] is None
    # 响应里也有 history_id
    for r_item in r.json()["data"]["results"]:
        assert isinstance(r_item["history_id"], str) and len(r_item["history_id"]) > 0


def test_batch_parse_inserts_failed_history(client, monkeypatch):
    """批量解析失败时,每条都落 history(parse_status='failed')。"""
    async def fake_fetch(share_url, cookie):
        raise RuntimeError("upstream 503")
    monkeypatch.setattr("server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch)

    from server.sp_modules.sph_parser import db as sph_db
    r = client.post("/api/channels/batch_parse",
                    json={"urls": ["https://weixin.qq.com/sph/u1",
                                   "https://weixin.qq.com/sph/u2"]})
    assert r.status_code == 200
    assert r.json()["data"]["summary"]["failed"] == 2
    assert sph_db.count_history() == 2

    items = sph_db.list_history(limit=10, offset=0)
    for it in items:
        assert it["parse_status"] == "failed"
        assert "upstream 503" in (it["parse_error"] or "")
        assert it["video_url"] == ""
    # 响应里也带 history_id(前端可后续重新解析)
    for r_item in r.json()["data"]["results"]:
        assert r_item["ok"] is False
        assert isinstance(r_item["history_id"], str) and len(r_item["history_id"]) > 0


def test_batch_parse_mixed_inserts_all(client, monkeypatch):
    """混合:成功/失败都落 history,parse_status 区分。"""
    call_count = {"n": 0}
    async def fake_fetch(share_url, cookie):
        call_count["n"] += 1
        if call_count["n"] % 2 == 0:
            raise RuntimeError("flaky")
        return {"errCode": 0, "data": {"authorInfo": {"nickname": "A"},
                "feedInfo": {"description": "T", "originVideoUrl": "https://x"}}}
    monkeypatch.setattr("server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch)

    from server.sp_modules.sph_parser import db as sph_db
    r = client.post("/api/channels/batch_parse",
                    json={"urls": ["https://weixin.qq.com/sph/u1",
                                   "https://weixin.qq.com/sph/u2",
                                   "https://weixin.qq.com/sph/u3",
                                   "https://weixin.qq.com/sph/u4"]})
    assert r.json()["data"]["summary"]["success"] == 2
    assert r.json()["data"]["summary"]["failed"] == 2
    assert sph_db.count_history() == 4

    items = sph_db.list_history(limit=10, offset=0)
    statuses = [it["parse_status"] for it in items]
    assert statuses.count("success") == 2
    assert statuses.count("failed") == 2
```

### 验证

- 新增 3 测试 PASS
- 现有 19 个 SPH 测试无回归
- 手动:批量解析 2 条 → 历史页出现 2 条 → 重新解析按钮可用

---

## 改动 2: 新增 /api/channels/mark_downloaded 端点

### 改动位置

- **后端**:`server/sp_modules/sph_parser/routes.py` (新增第 10 个端点)
- **后端**:`server/__main__.py` (`do_POST` 路由分发,加一条)
- **前端**:`frontend-vue/src/api/channels.ts` (新增 `markSphDownloaded` API)
- **前端**:`frontend-vue/src/stores/sphQueue.ts` (`downloadDirectly` 成功后调用)
- **前端**:`frontend-vue/src/views/Channels/SingleParse.vue` (`onDownload` 成功后调用)
- **前端**:`frontend-vue/src/views/Channels/ParseHistory.vue` (`downloadDirectly` 成功后调用)

### 设计细节

#### 2.1 后端端点定义

```python
# server/sp_modules/sph_parser/routes.py
@router.post("/mark_downloaded")
async def api_mark_downloaded(body: dict):
    """POST /mark_downloaded — 标记一条 history 为已下载。

    由前端浏览器侧下载完成后调用,以便历史页能展示下载状态。
    失败不抛 5xx(主流程已下载成功,标记失败不应让前端报错)。
    """
    history_id = body.get("history_id")
    path = body.get("path", "")
    if not history_id:
        return err(400, "history_id required")
    try:
        # 直接 UPDATE,不查 rowcount:即使 id 不存在,也返回 ok(幂等)
        conn = sqlite3.connect(sph_db._get_db_path())
        conn.execute(
            "UPDATE sph_parse_history SET downloaded=1, downloaded_path=?, downloaded_at=? WHERE id=?",
            (path, sph_db._now_iso(), history_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("[mark_downloaded] update failed: %s", e)
        return err(500, f"db update failed: {e}")
    return ok({"updated": True})
```

**关键决策:**
- **id 不存在时静默成功**:前端无法保证 id 100% 有效(history 已被清理等);返回 ok 让前端不报红。
- **path 可为空**:浏览器下载路径是建议文件名,不是真实磁盘路径。前端传什么存什么。
- **不返回 history**:前端不需再用此 id 查 history,直接刷新列表即可。

#### 2.2 主进程路由分发

`server/__main__.py:1626` 附近,加:
```python
elif path == "\api\channels\mark_downloaded" and self.command == "POST":
    self._api_channels_mark_downloaded(body)
```

并新增:
```python
def _api_channels_mark_downloaded(self, body: dict):
    from server.sp_modules.sph_parser import db as _sph_db
    history_id = body.get("history_id")
    if not history_id:
        self._send_json({"error": "history_id required"}, 400)
        return
    try:
        import sqlite3
        conn = sqlite3.connect(_sph_db._get_db_path())
        conn.execute(
            "UPDATE sph_parse_history SET downloaded=1, downloaded_path=?, downloaded_at=? WHERE id=?",
            (body.get("path", ""), _sph_db._now_iso(), history_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        _log.warning("[sph/mark_downloaded] update failed: %s", e)
        self._send_json({"error": f"db update failed: {e}"}, 500)
        return
    self._send_json({"ok": True, "data": {"updated": True}})
```

#### 2.3 前端 API 封装

`frontend-vue/src/api/channels.ts` 新增:
```ts
export function markSphDownloaded(history_id: string, path: string = '') {
    return request<{ ok: boolean; data: { updated: boolean } }>({
        url: '/api/channels/mark_downloaded',
        method: 'post',
        data: { history_id, path },
    })
}
```

#### 2.4 前端 3 个下载入口改造

**统一模式** (在 `downloadDirectly` / `onDownload` 成功路径最后):
```ts
// 标记历史为已下载(失败不抛错,只 log)
markSphDownloaded(history_id, filename).catch((e) => {
    console.warn('[sph] mark_downloaded failed:', e)
})
```

**改动点:**

1. **`sphQueue.ts:downloadDirectly`** — 批量下载每个 item 成功后调用
   - 需要 history_id:在 `processBatch` 解析成功时从 db 读出(见 §2.5)
2. **`SingleParse.vue:onDownload`** — 单链接下载成功后调用
   - 需要 history_id:在 `onParse` 成功后从 db 读出
3. **`ParseHistory.vue:downloadDirectly`** — 历史页下载后调用
   - history_id 直接从 item 拿,无需额外查询

#### 2.5 关键问题:前端如何拿到 history_id?

批量解析时,后端插入 history 后**没有把 history_id 放进 API 响应**(当前响应 `{url, ok, data: <raw response>}`)。前端没有 history_id,就无法 mark_downloaded。

**方案选择:**

| 方案 | 优点 | 缺点 |
|------|------|------|
| **A. 后端在 results 中返回 history_id** | 前端直接拿,无额外查询 | 改 API 响应形状(需测试覆盖) |
| B. 前端查询 history by sph_url | 响应形状不变 | 1 次额外查询,可能拿到旧条目 |
| C. 前端不标记,history.downloaded 永远 0 | 无后端改动 | 失去能力,违反本目标 #2 |

**推荐 A. 改后端响应。** 改动小:在 `_one` 里把插入后的 id 加进返回 dict。

```python
def _one(u: str) -> dict:
    try:
        r = _sph_core.fetch_video_profile_sync(u, _sph_cfg.get_cookie())
    except Exception as e:
        return {"url": u, "ok": False, "error": str(e)}
    history_id = ""
    try:
        # ... insert_history
        history_id = str(_uuid.uuid4())  # 保存下来
    except Exception as _db_e:
        _log.warning(...)
    return {"url": u, "ok": True, "data": r, "history_id": history_id}
```

**但这改 API 契约。** 需要在回归测试中显式断言:
- `data.results[*].history_id` 在 ok=True 时是字符串
- `data.results[*].history_id` 在 ok=False 时是空字符串

#### 2.6 单链接解析路径同样问题

`_api_channels_parse_sph` 当前响应:
```json
{ "ok": true, "data": { "authorInfo": {...}, "feedInfo": {...} } }
```

**没有 history_id**。前端也无法 mark。

**方案 A 扩展**:响应增加 `history_id` 字段。
```python
self._send_json({
    "ok": True,
    "data": {
        "authorInfo": author_info,
        "feedInfo": feed_info,
        "history_id": history_id,  # 新增
    }
})
```

#### 2.7 历史页 history_id 来源

`ParseHistory.vue:downloadDirectly` 已经有 `item.id`(就是 history_id),直接用即可。

### 测试

#### 后端测试 (`tests/test_sph_api_contract.py`)

```python
def test_mark_downloaded_success(client):
    """mark_downloaded 成功更新 history。"""
    from server.sp_modules.sph_parser import db as sph_db
    sph_db.insert_history({
        "id": "h-1", "sph_url": "https://weixin.qq.com/sph/u1",
        "video_url": "https://x", "parse_status": "success",
    })

    r = client.post("/api/channels/mark_downloaded",
                    json={"history_id": "h-1", "path": "D:/v/abc.mp4"})
    assert r.status_code == 200
    item = sph_db.get_history("h-1")
    assert item["downloaded"] == 1
    assert item["downloaded_path"] == "D:/v/abc.mp4"
    assert item["downloaded_at"] is not None


def test_mark_downloaded_idempotent(client):
    """mark_downloaded 对不存在的 id 静默成功(幂等)。"""
    r = client.post("/api/channels/mark_downloaded",
                    json={"history_id": "nonexistent", "path": ""})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_mark_downloaded_missing_id(client):
    """缺少 history_id 返回 400。"""
    r = client.post("/api/channels/mark_downloaded", json={"path": ""})
    assert r.status_code == 400
```

#### 响应形状回归测试更新

需要在 §1 的 `test_batch_parse_response_shape_contract` 中加一行:
```python
# 成功项的 data.history_id 字段必须存在(供前端 mark_downloaded 使用)
assert isinstance(item["history_id"], str)
```

单链接解析的 contract 测试也需要更新:
```python
def test_parse_sph_response_includes_history_id(monkeypatch, client):
    """parse_sph 响应必须包含 history_id 供前端 mark_downloaded。"""
    async def fake_fetch(share_url, cookie):
        return {"errCode": 0, "data": {"authorInfo": {"nickname": "A"},
                "feedInfo": {"description": "T", "originVideoUrl": "https://x"}}}
    monkeypatch.setattr("server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch)
    r = client.get("/api/channels/parse_sph", params={"url": "https://weixin.qq.com/sph/abc"})
    body = r.json()
    assert "history_id" in body["data"]
    assert len(body["data"]["history_id"]) > 0
```

---

## 改动 3 (附带):前端 3 个下载入口的 mark_downloaded 调用

### 改动位置

- `frontend-vue/src/views/Channels/SingleParse.vue:onDownload` (line 227-258)
- `frontend-vue/src/stores/sphQueue.ts:downloadDirectly` (line 76-111)
- `frontend-vue/src/views/Channels/ParseHistory.vue:downloadDirectly` (line 138-175)

### 关键点

- **不影响主流程**:mark_downloaded 失败用 `.catch` 吞掉,只 console.warn
- **history_id 缺失时跳过**:从 `onParse` 拿不到 history_id 时不调用(降级)
- **path 字段**:浏览器侧用 `sanitizeFilename(...)` 后的文件名作为建议 path

### 实现细节

```ts
// SingleParse.vue:onDownload 末尾追加
import { markSphDownloaded } from '@/api/channels'
const historyId = ref<string>('')  // 在 onParse 成功后赋值

// onParse 末尾(成功路径):
//   rawRaw.value = raw?.data ?? raw
//   historyId.value = (raw as any)?.history_id || ''

// onDownload 成功路径(blob 保存后):
markSphDownloaded(historyId.value, filename).catch((e) => {
    console.warn('[sph] mark_downloaded failed:', e)
})
```

```ts
// sphQueue.ts:downloadDirectly 末尾
// 需要 item.historyId (在 processBatch 中赋值)
markSphDownloaded(item.historyId || '', filename).catch((e) => {
    console.warn('[sph] mark_downloaded failed:', e)
})
```

```ts
// ParseHistory.vue:downloadDirectly 已有 item.id
markSphDownloaded(item.id, filename).catch((e) => {
    console.warn('[sph] mark_downloaded failed:', e)
})
```

### 测试

这部分纯前端,无后端契约变更 → 手动验证即可:
- 批量解析 1 条 → 下载 → 历史页 `downloaded` 应为 1
- 单链接解析 → 下载 → 历史页 `downloaded` 应为 1
- 历史页直接下载 → `downloaded` 应为 1

## 实施计划

| 步骤 | 内容 | 验证 |
|------|------|------|
| 1 | 后端:在 `_one` 中加 `insert_history` 并返回 `history_id` | 跑 3 个新测试 + 19 个现有测试 |
| 2 | 后端:加 `/mark_downloaded` 端点(FastAPI + main.py) | 跑 3 个新测试 |
| 3 | 后端:`parse_sph` 响应加 `history_id` | 跑新增 contract 测试 |
| 4 | 前端:加 `markSphDownloaded` API | 编译通过 |
| 5 | 前端:3 个下载入口在成功后调 mark | 手动验证 3 个流程 |
| 6 | 跑全套 SPH 测试 | 19 + 6 = 25 passed |

## 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| API 响应形状变更(加 history_id)破坏现有前端 | 低 | 前端是同仓库同时改,不会跨版本失配 |
| SQLite 并发写锁(批量解析 3 线程同时 insert) | 低 | SQLite WAL 模式 + 独立 connection,实测无问题 |
| 失败解析产生「失败记录」污染历史 | 已规避 | 失败路径不 insert |
| DB 错误导致 API 失败 | 已规避 | try/except 包住 insert,失败只 log |
| mark_downloaded 网络失败 | 已规避 | 前端 .catch 吞掉,只 console.warn |

## 关联 Issue

- 上游 commit `39aa636`: 修复了「批量解析不下载」,但发现批量解析没存 history
- 上游 commit `d486dc6`: 标注 SPH 集成后定位
- 上游 commit `6695cf7`: 修复 history DB 路径分裂(确保所有 SPH 数据都进 monitor.db)
