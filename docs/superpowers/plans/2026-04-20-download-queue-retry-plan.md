# 下载队列重试与退避机制实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 per-account 独立下载池 + 429 指数退避重试 + 失败持久化

**Architecture:**
- 全局退避状态（`_proxy_cooldown_until`/`_direct_cooldown_until`）受 lock 保护，per-account 独立线程池
- 429 退避时间 `min(60*retry_count, 180) + jitter(0~10)`，上限 180s
- pending_retry 纯内存状态，进程重启后由 restart recovery 统一标记 failed

**Tech Stack:** threading.Lock, ThreadPoolExecutor, SQLite migrations

---

## 文件变更总览

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `monitor/db/migrations.py` | 修改 | 新增 v5 failed_videos 迁移 |
| `monitor/db/queries/videos.py` | 修改 | 新增 failed/retry 查询 |
| `Youtube_Downloader.py` | 修改 | batch_download 返回值新增 is_rate_limited 字段 |
| `monitor/scheduler.py` | 修改 | per-account 池 + 退避状态 + 重试逻辑 |
| `server/__main__.py` | 修改 | 新增 POST /api/videos/retry 端点 |
| `monitor_web/static/js/app.js` | 修改 | 视频列表状态筛选 + 重试按钮 |
| `monitor_web/templates/pages/settings-accounts.html` | 修改 | 视频列表 HTML |

---

## Phase 1：数据层（DB迁移 + YoutubeDownloader）

### Task 1.1：数据库迁移 — monitor_videos 新增字段

**Files:**
- Modify: `monitor/db/migrations.py`
- Test: `tests/test_monitor_schema_bootstrap.py`

---

- [ ] **Step 1: 在 migrations.py 添加 v5 迁移**

在 `run_all_migrations()` 函数末尾添加：

```python
# v5: monitor_videos 失败重试字段
if "v5_failed_retry_fields" not in _get_applied_versions(conn):
    cur = conn.execute("PRAGMA table_info(monitor_videos)")
    cols = {row[1] for row in cur.fetchall()}
    for col, ddl in [
        ("failed_reason", "TEXT"),
        ("failed_at", "TEXT"),
        ("failed_event_id", "INTEGER REFERENCES monitor_events(id)"),
        ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE monitor_videos ADD COLUMN {col} {ddl}")
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        ("v5_failed_retry_fields", today),
    )
```

---

- [ ] **Step 2: 验证迁移不影响现有功能**

```bash
pytest tests/test_monitor_schema_bootstrap.py -v -x
```
期望：PASS

---

### Task 1.2：YoutubeDownloader 返回值新增 `is_rate_limited`

**Files:**
- Modify: `Youtube_Downloader.py:493-521`
- Test: 新建 `tests/test_youtube_downloader_rate_limit.py`

---

- [ ] **Step 1: 新建测试文件 `tests/test_youtube_downloader_rate_limited.py`**

```python
"""tests/test_youtube_downloader_is_rate_limited.py"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import Youtube_Downloader as yd

def test_batch_download_returns_rate_limited_field():
    """batch_download 结果中每条记录应包含 is_rate_limited 字段（bool）"""
    # 用一个无效 URL 触发错误路径
    results = yd.batch_download(
        ["https://www.youtube.com/watch?v=invalid_url_xyz"],
        output_path=".",
        resolution="best",
    )
    for r in results:
        assert "is_rate_limited" in r, f"缺少 is_rate_limited 字段: {r}"
        assert isinstance(r["is_rate_limited"], bool), f"is_rate_limited 应为 bool: {r}"
```

- [ ] **Step 2: 运行测试验证失败（预期 FAIL — is_rate_limited 不存在）**

```bash
pytest tests/test_youtube_downloader_is_rate_limited.py -v
```
期望：FAIL — "is_rate_limited 字段不存在"

---

- [ ] **Step 3: 修改 Youtube_Downloader.py 添加 is_rate_limited 字段**

在 `Youtube_Downloader.py` 的代理失败处理分支（is_proxy_retryable_error 分支前）添加：

```python
# 检测是否 429（rate limit）
is_429 = "429" in error_msg.lower() or "rate limit" in error_msg.lower()
results.append({
    "url": url,
    "状态": "失败",
    "信息": f"{error_msg} | 代理: {current_proxy or '直连'}",
    "is_rate_limited": is_429,   # 新增
})
```

注意：429 检测应在 append result 之前判断，并携带到返回值中。

完整修改段（Youtube_Downloader.py:493-521）：

```python
except (yt_dlp.utils.DownloadError, Exception) as e:
    error_msg = str(e)
    if mode == "direct":
        is_429 = "429" in error_msg.lower() or "rate limit" in error_msg.lower()
        results.append({
            "url": url,
            "状态": "失败",
            "信息": f"{error_msg} | 代理: 直连",
            "is_rate_limited": is_429,
        })
        finished = True
        break

    retryable = is_proxy_retryable_error(error_msg)
    has_next = att_idx + 1 < len(attempts_plan)
    if retryable and has_next:
        nxt = attempts_plan[att_idx + 1]
        nxt_label = "直连" if nxt[0] == "direct" else (nxt[1] or "")
        _log.warning(f"代理失败 [{i+1}/{total}]: {current_proxy} → 切换 {nxt_label}")
        print(f" [{i+1}/{total}] 代理 {current_proxy} 失败，切换下一个...")
        continue

    # 最终失败（无可用代理 或 非重试错误）
    is_429 = retryable and "429" in error_msg.lower()
    results.append({
        "url": url,
        "状态": "失败",
        "信息": f"{error_msg} | 代理: {current_proxy or '直连'}",
        "is_rate_limited": is_429,
    })
    finished = True
    break
```

---

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/test_youtube_downloader_is_rate_limited.py -v
```
期望：PASS

---

- [ ] **Step 5: 提交 Phase 1**

```bash
git add monitor/db/migrations.py Youtube_Downloader.py tests/test_youtube_downloader_is_rate_limited.py
git commit -m "feat: monitor DB迁移 + batch_download新增is_rate_limited字段

- migrations: v5 新增failed_reason/failed_at/failed_event_id/retry_count字段
- Youtube_Downloader.batch_download: 返回值新增is_rate_limited=True标识429错误"
```

---

## Phase 2：调度器核心（per-account池 + 退避 + 重试）

### Task 2.1：全局退避状态管理函数

**Files:**
- Modify: `monitor/scheduler.py`
- Test: 新建 `tests/test_monitor_cooldown_state.py`

---

- [ ] **Step 1: 新建测试文件 `tests/test_monitor_cooldown_state.py`**

```python
"""tests/test_monitor_cooldown_state.py"""
import pytest, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 直接导入 scheduler 模块测试（不启动服务）
# 使用 mock patch 避免干扰现有状态
from monitor import scheduler as sched

def test_proxy_cooldown_serialization():
    """_proxy_cooldown_until 字典读写应原子"""
    # 模拟设置 proxy cooldown
    proxy = "http://test:123@1.2.3.4:8080"
    sched._proxy_cooldown_until[proxy] = time.monotonic() + 60
    assert proxy in sched._proxy_cooldown_until
    # 清理
    sched._proxy_cooldown_until.pop(proxy, None)

def test_proxy_cooldown_respect_retry_count():
    """retry_count 字典应独立计数"""
    proxy = "http://test:123@1.2.3.4:8080"
    sched._proxy_retry_count[proxy] = 2
    assert sched._proxy_retry_count[proxy] == 2
    sched._proxy_retry_count.pop(proxy, None)
```

---

- [ ] **Step 2: 添加退避状态模块到 scheduler.py**

在 `scheduler.py` 顶部（import 后）添加：

```python
# ── 下载退避状态（线程安全）────────────────────────────────────────────
import random as _random

_proxy_cooldown_until: dict[str, float] = {}   # proxy_url → 退避截止时间（monotonic）
_proxy_retry_count: dict[str, int] = {}        # proxy_url → 当前重试次数
_proxy_lock = threading.Lock()                  # 保护 proxy 退避字典

_direct_cooldown_until: float | None = None    # 全局直连退避截止时间
_direct_retry_count: int = 0
_direct_lock = threading.Lock()                  # 保护直连退避字典


def _get_backoff_seconds(retry_count: int) -> float:
    """退避时间 = min(60 * retry_count, 180) + jitter(0~10)"""
    return min(60 * retry_count, 180) + _random.uniform(0, 10)


def _wait_for_proxy_cooldown(proxy: str) -> bool:
    """
    等待 proxy 退避结束。
    返回 True 表示已退出等待（退避完成）；返回 False 表示超时。
    """
    with _proxy_lock:
        deadline = _proxy_cooldown_until.get(proxy)
    if deadline is None:
        return True
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return True
    time.sleep(remaining)
    return True


def _set_proxy_cooldown(proxy: str, retry_count: int) -> None:
    """设置 proxy 退避状态（线程安全）"""
    with _proxy_lock:
        _proxy_cooldown_until[proxy] = time.monotonic() + _get_backoff_seconds(retry_count)
        _proxy_retry_count[proxy] = retry_count


def _wait_for_direct_cooldown() -> bool:
    """等待全局直连退避结束。"""
    global _direct_cooldown_until
    with _direct_lock:
        deadline = _direct_cooldown_until
    if deadline is None:
        return True
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return True
    time.sleep(remaining)
    return True


def _set_direct_cooldown(retry_count: int) -> None:
    """设置全局直连退避状态（线程安全）"""
    global _direct_cooldown_until, _direct_retry_count
    with _direct_lock:
        _direct_cooldown_until = time.monotonic() + _get_backoff_seconds(retry_count)
        _direct_retry_count = retry_count
```

---

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_monitor_cooldown_state.py -v
```
期望：PASS

---

- [ ] **Step 4: 提交退避状态模块**

```bash
git add monitor/scheduler.py tests/test_monitor_cooldown_state.py
git commit -m "feat: scheduler新增退避状态管理模块

- _proxy_cooldown_until/_proxy_retry_count（per-proxy 退避）
- _direct_cooldown_until/_direct_retry_count（全局直连退避）
- _get_backoff_seconds()/wait_for_proxy_cooldown()/wait_for_direct_cooldown()
- 线程安全：所有状态读写受 lock 保护"
```

---

### Task 2.2：per-account 下载池

**Files:**
- Modify: `monitor/scheduler.py:445-461`

---

- [ ] **Step 1: 添加 per-account 池到 scheduler.py**

替换现有的 `_auto_dl_pool` 相关代码：

```python
# ── per-account 下载池（替代全局 _auto_dl_pool）─────────────────────────

# 旧代码（删除）：
# _auto_dl_pool: ThreadPoolExecutor | None = ThreadPoolExecutor(max_workers=2)

# 新代码：
_account_pools: dict[int, ThreadPoolExecutor] = {}   # account_id → 独立池
_account_pools_lock = threading.Lock()               # 保护账户池创建/销毁

_POOL_MAX_WORKERS = 2  # 每账户最大并发下载数（可配置）


def _ensure_account_pool(account_id: int) -> ThreadPoolExecutor:
    """获取或创建指定账户的独立下载池（线程安全）。"""
    with _account_pools_lock:
        if account_id not in _account_pools:
            _account_pools[account_id] = ThreadPoolExecutor(max_workers=_POOL_MAX_WORKERS)
        return _account_pools[account_id]


def _shutdown_account_pool(account_id: int, wait: bool = False) -> None:
    """关闭指定账户的下载池。"""
    with _account_pools_lock:
        pool = _account_pools.pop(account_id, None)
    if pool is None:
        return
    try:
        pool.shutdown(wait=wait, cancel_futures=True)
    except TypeError:
        pool.shutdown(wait=wait)
```

同时删除旧的全局 `_ensure_auto_download_pool` / `_shutdown_auto_download_pool` 函数（已被上面的 `_ensure_account_pool` / `_shutdown_account_pool` 替代）。

---

- [ ] **Step 2: 验证语法正确**

```bash
python -m py_compile monitor/scheduler.py && echo "SYNTAX OK"
```

---

- [ ] **Step 3: 提交 per-account 池**

```bash
git add monitor/scheduler.py
git commit -m "refactor: 全局池改为 per-account 独立下载池

- 替换 _auto_dl_pool 为 _account_pools[account_id] 字典
- 新增 _ensure_account_pool()/_shutdown_account_pool() 函数
- 每账户 max_workers=2，lazy 创建，账户禁用时销毁"
```

---

### Task 2.3：退避重试循环（核心逻辑）

**Files:**
- Modify: `monitor/scheduler.py`（`_auto_download_videos` 函数重写）

---

- [ ] **Step 1: 重写 `_auto_download_videos` 函数**

将原 `_auto_download_videos` 替换为支持退避重试的版本：

```python
def _auto_download_videos(
    video_records: list[dict],
    proxy: str | None = None,
    account_id: int | None = None,
) -> None:
    """
    per-account 池执行下载，支持 429 指数退避重试。

    Args:
        video_records: 视频记录列表
        proxy: 代理 URL（无代理传 None）
        account_id: 账户 ID（用于获取独立池）
    """
    if not video_records:
        return
    urls = [r["url"] for r in video_records if r.get("url")]
    if not urls:
        return

    cfg = _get_config()
    output_path = cfg.get("download_output_path", "").strip()
    if not output_path:
        output_path = os.path.join(_MONITOR_ROOT, "..", "videos")
        output_path = os.path.normpath(output_path)
    os.makedirs(output_path, exist_ok=True)

    cookies_file = cfg.get("download_cookies_file", "") or None
    enable_aria2 = bool(cfg.get("enable_aria2", False))
    extra_ydl_opts = build_aria2_opts() if enable_aria2 else None

    BATCH_SIZE = 2
    pool = _ensure_account_pool(account_id) if account_id else None

    for i in range(0, len(urls), BATCH_SIZE):
        chunk = urls[i:i + BATCH_SIZE]
        chunk_records = video_records[i:i + BATCH_SIZE]
        chunk_ids = [r["id"] for r in chunk_records]

        _log.info(
            f"自动下载批次 {i // BATCH_SIZE + 1}: "
            f"{len(chunk)} 个视频 "
            f"{'[aria2]' if enable_aria2 else ''}"
            f"{'[proxy]' if proxy else '[直连]'}"
        )

        # 提交批次到线程池（不退避，由池内处理重试）
        _submit_download_batch(
            chunk, chunk_records, output_path, proxy,
            cookies_file, extra_ydl_opts, cfg, pool, account_id,
        )


def _submit_download_batch(
    batch_urls, batch_records, output_path, proxy, cookies_file,
    extra_ydl_opts, cfg, pool, account_id,
):
    """提交一个下载批次到线程池。"""
    def _dl_batch():
        try:
            _db.update_videos_download_status(batch_ids, "downloading")
            results = batch_download(
                batch_urls,
                output_path,
                "best",
                proxy=proxy,
                cookies_file=cookies_file,
                concurrent_fragments=2,
                no_subs=not cfg.get("auto_clip_enabled", False),
                extra_ydl_opts=extra_ydl_opts,
            )

            now_str = _db.now_iso()
            for idx, r in enumerate(results):
                vid = batch_ids[idx] if idx < len(batch_ids) else None
                if not vid:
                    continue
                if r.get("状态") == "成功":
                    # 成功：清除重试相关字段
                    file_path = r.get("video_path") or output_path
                    _db.update_videos_download_status(
                        [vid], "downloaded",
                        download_at=now_str,
                        download_path=file_path,
                        retry_count=0,
                    )
                elif r.get("is_rate_limited"):
                    # 429：进入退避重试流程
                    _handle_rate_limited(
                        vid, batch_urls[idx], batch_records[idx],
                        proxy, output_path, cookies_file, extra_ydl_opts, cfg,
                    )
                else:
                    # 非 429 失败：直接标记 failed
                    _db.update_videos_download_status(
                        [vid], "failed",
                        download_error=r.get("信息", ""),
                        retry_count=0,
                    )
        except Exception as exc:
            _log.error("批次下载异常", exc_info=True)
            _db.update_videos_download_status(
                batch_ids, "failed",
                download_error=f"自动下载异常: {type(exc).__name__}",
                retry_count=0,
            )

    if pool is not None:
        pool.submit(_dl_batch)
    else:
        threading.Thread(target=_dl_batch, daemon=True).start()


def _handle_rate_limited(
    vid: int, url: str, record: dict,
    proxy: str | None, output_path: str,
    cookies_file, extra_ydl_opts, cfg,
):
    """
    处理单个视频的 429 退避重试逻辑。
    支持代理退避和直连退避，指数退避最多 3 次（proxy 各 3 次 + 直连各 3 次）。
    """
    is_proxy = proxy is not None
    retry_count = record.get("retry_count", 0) or 0
    MAX_RETRIES = 3

    # 指数退避时间
    backoff = min(60 * retry_count, 180) + random.uniform(0, 10)

    if is_proxy:
        # 代理退避：等退避结束后重试同代理
        _wait_for_proxy_cooldown(proxy)
        _log.warning(f"代理退避结束，重试视频: {url}")
        retry_count += 1
        _db.update_videos_download_status([vid], retry_count=retry_count)
        try:
            results = batch_download(
                [url], output_path, "best",
                proxy=proxy,
                cookies_file=cookies_file,
                concurrent_fragments=2,
                extra_ydl_opts=extra_ydl_opts,
            )
            r = results[0] if results else {}
            if r.get("状态") == "成功":
                _db.update_videos_download_status(
                    [vid], "downloaded",
                    download_path=r.get("video_path", ""),
                    retry_count=0,
                )
                return
            if r.get("is_rate_limited"):
                # 代理再次 429
                if retry_count >= MAX_RETRIES:
                    # 代理重试次数用尽，切换直连
                    _log.warning(f"代理退避重试 {retry_count} 次后仍 429，切换直连: {url}")
                    _handle_direct_fallback(vid, url, record, output_path, cookies_file, extra_ydl_opts, cfg)
                else:
                    # 继续代理退避
                    _set_proxy_cooldown(proxy, retry_count)
                    _wait_for_proxy_cooldown(proxy)
                    _handle_rate_limited(
                        vid, url, record, proxy, output_path,
                        cookies_file, extra_ydl_opts, cfg,
                    )
            else:
                # 非 429 失败（文件错误等）
                _db.update_videos_download_status(
                    [vid], "failed",
                    download_error=r.get("信息"),
                    retry_count=0,
                )
        except Exception as exc:
            _db.update_videos_download_status(
                [vid], "failed",
                download_error=f"退避重试异常: {exc}",
                retry_count=0,
            )
    else:
        _handle_direct_fallback(vid, url, record, output_path, cookies_file, extra_ydl_opts, cfg)


def _handle_direct_fallback(
    vid, url, record, output_path, cookies_file, extra_ydl_opts, cfg,
):
    """直连 429 退避重试（独立于代理退避）。"""
    retry_count = record.get("retry_count", 0) or 0
    MAX_RETRIES = 3

    _wait_for_direct_cooldown()
    retry_count += 1
    _db.update_videos_download_status([vid], retry_count=retry_count)

    if retry_count > MAX_RETRIES:
        # 直连重试次数用尽，标记最终失败
        _db.update_videos_download_status(
            [vid], "failed",
            download_error=f"429 rate limit after {MAX_RETRIES} retries",
        )
        return

    _set_direct_cooldown(retry_count)
    _log.warning(f"直连退避 {retry_count}/{MAX_RETRIES} 次: {url}")

    try:
        results = batch_download(
            [url], output_path, "best",
            proxy=None,
            cookies_file=cookies_file,
            concurrent_fragments=2,
            extra_ydl_opts=extra_ydl_opts,
        )
        r = results[0] if results else {}
        if r.get("状态") == "成功":
            _db.update_videos_download_status(
                [vid], "downloaded",
                download_path=r.get("video_path", ""),
                retry_count=0,
            )
        elif r.get("is_rate_limited"):
            _handle_direct_fallback(vid, url, record, output_path, cookies_file, extra_ydl_opts, cfg)
        else:
            _db.update_videos_download_status(
                [vid], "failed",
                download_error=r.get("信息"),
                retry_count=0,
            )
    except Exception as exc:
        _db.update_videos_download_status(
            [vid], "failed",
            download_error=f"直连退避重试异常: {exc}",
            retry_count=0,
        )
```

> 注：`_db.update_videos_download_status` 新增 `retry_count` 参数，在 monitor/db/queries/videos.py 中实现。

---

- [ ] **Step 2: 验证语法**

```bash
python -m py_compile monitor/scheduler.py && echo "SYNTAX OK"
```

---

- [ ] **Step 3: 提交 Phase 2.3**

```bash
git add monitor/scheduler.py
git commit -m "feat: scheduler新增429退避重试逻辑

- _handle_rate_limited: 代理429退避重试（最多3次后切直连）
- _handle_direct_fallback: 直连退避重试（最多3次后标记failed）
- 线程安全：退避状态受_proxy_lock/_direct_lock保护
- 持久化：每次重试更新retry_count到SQLite"
```

---

## Phase 3：持久化查询 + Web UI + 重启恢复

### Task 3.1：DB 查询更新（update_videos_download_status + 重试）

**Files:**
- Modify: `monitor/db/queries/videos.py`
- Test: 新建 `tests/test_monitor_download_retry.py`

---

- [ ] **Step 1: 新建测试文件 `tests/test_monitor_download_retry.py`**

```python
"""tests/test_monitor_download_retry.py"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import monitor.db as _db
from monitor.db.queries.videos import update_videos_download_status

def test_update_retry_count_persists(tmp_path):
    """update_videos_download_status 应持久化 retry_count 字段"""
    # 创建临时测试数据库
    ...
    update_videos_download_status([vid], "downloading", retry_count=2)
    rows = db.execute("SELECT retry_count FROM monitor_videos WHERE id=?", (vid,)).fetchone()
    assert rows[0] == 2
```

---

- [ ] **Step 2: 修改 `update_videos_download_status` 函数**

在 `monitor/db/queries/videos.py` 中，`update_videos_download_status` 函数新增 `retry_count` 参数：

```python
def update_videos_download_status(
    video_ids: list[int],
    status: str | None = None,
    download_at: str | None = None,
    download_path: str | None = None,
    download_error: str | None = None,
    retry_count: int | None = None,  # 新增参数
    event_id: int | None = None,          # 新增参数（用于 failed_event_id）
    failed_reason: str | None = None,        # 新增参数
    failed_at: str | None = None,          # 新增参数
) -> None:
    """更新视频下载状态及重试字段"""
    fields = []
    values = []
    if status:
        fields.append("download_status=?")
        values.append(status)
    if download_at:
        fields.append("downloaded_at=?")
        values.append(download_at)
    if download_path:
        fields.append("downloaded_path=?")
        values.append(download_path)
    if download_error:
        fields.append("download_error=?")
        values.append(download_error)
    if retry_count is not None:
        fields.append("retry_count=?")
        values.append(retry_count)
    if failed_reason is not None:
        fields.append("failed_reason=?")
        values.append(failed_reason)
    if failed_at is not None:
        fields.append("failed_at=?")
        values.append(failed_at)
    if event_id is not None:
        fields.append("failed_event_id=?")
        values.append(event_id)
    if not fields:
        return
    values.extend(video_ids)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE monitor_videos SET {','.join(fields)} WHERE id IN ({','.join('?' * len(video_ids)})",
            values,
        )
```

同时修改调用方（scheduler.py 中的 `_db.update_videos_download_status` 调用）以传递 `retry_count`。

---

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_monitor_download_retry.py -v
```

---

- [ ] **Step 4: 提交 DB 查询更新**

```bash
git add monitor/db/queries/videos.py tests/test_monitor_download_retry.py
git commit -m "feat: update_videos_download_status新增retry_count/failed_reason/failed_at/failed_event_id参数"
```

---

### Task 3.2：API 端点 + 重启恢复

**Files:**
- Modify: `server/__main__.py`（新增 /api/videos/retry）
- Modify: `monitor/scheduler.py`（新增 restart recovery）
- Test: 新建 `tests/test_monitor_retry_endpoint.py`

---

- [ ] **Step 1: 新增 restart recovery 在 scheduler 启动时**

在 `scheduler.py` 的 `start()` 函数开头添加：

```python
def start(auto_download: bool = False) -> tuple[bool, bool]:
    # 重启恢复：running → failed
    _db.mark_stale_running_videos_interrupted()
    # ... 原有逻辑继续
```

在 `monitor/db/queries/videos.py` 添加：

```python
def mark_stale_running_videos_interrupted() -> None:
    """进程重启时调用：将 running 状态标记为 failed"""
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE monitor_videos
               SET download_status='failed',
                   failed_reason='服务重启导致任务中断',
                   failed_at=?,
                   retry_count=0
               WHERE download_status='running'""",
            (now,),
        )
```

---

- [ ] **Step 2: 新增 `POST /api/videos/retry` 端点**

在 `server/__main__.py` 的 API 路由部分添加：

```python
elif action == "retry":
    body = json.loads(self.rfile.read(int(self.headers["Content-Length"]))
    video_ids = body.get("video_ids", [])
    account_id = body.get("account_id")
    if not video_ids or not account_id:
        self.send_error(400, "video_ids 和 account_id 必填")
        return
    # 验证账户存在
    account = _db.get_account(account_id)
    if not account:
        self.send_error(404, "账户不存在")
        return
    # 重试：将 failed 视频重置为 pending
    from monitor.db.queries.videos import reset_videos_for_retry
    reset_videos_for_retry(video_ids, account_id)
    self._send_json({"ok": True, "retried": len(video_ids)})
```

`reset_videos_for_retry` 实现：

```python
def reset_videos_for_retry(video_ids: list[int], account_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE monitor_videos
               SET download_status='pending',
                   retry_count=0,
                   failed_reason=NULL,
                   failed_at=NULL,
                   failed_event_id=NULL
               WHERE id IN ({})
               AND download_status='failed'""",
            video_ids,
        )
```

---

- [ ] **Step 3: 验证语法 + 运行测试**

```bash
python -m py_compile server/__main__.py && echo "SYNTAX OK"
pytest tests/test_monitor_retry_endpoint.py -v
```

---

- [ ] **Step 4: 提交 API + 重启恢复**

```bash
git add server/__main__.py monitor/db/queries/videos.py monitor/scheduler.py
git commit -m "feat: POST /api/videos/retry端点 + restart recovery

- 重启时running→failed（防止僵尸任务）
- 重试端点：failed视频重置为pending，重新入队列"
```

---

## Phase 4：Web UI

### Task 4.1：视频列表状态筛选 + 重试按钮

**Files:**
- Modify: `monitor_web/static/js/app.js`
- Modify: `monitor_web/templates/pages/settings-accounts.html`

---

- [ ] **Step 1: JS 新增 status 筛选状态**

在 `app.js` 视频列表相关变量区添加：

```javascript
const VIDEO_STATUS_FILTERS = [
    { value: "all", label: "全部" },
    { value: "downloading", label: "下载中" },
    { value: "downloaded", label: "已下载" },
    { value: "failed", label: "失败" },
];
```

---

- [ ] **Step 2: 重试按钮逻辑**

添加重试按钮点击处理：

```javascript
// 选中 failed 视频后，点击"重试"按钮
async function retryFailedVideos(videoIds, accountId) {
    const resp = await fetch("/api/videos/retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_ids: videoIds, account_id: accountId }),
    });
    return resp.json();
}
```

---

- [ ] **Step 3: 提交 Web UI**

```bash
git add monitor_web/static/js/app.js monitor_web/templates/pages/settings-accounts.html
git commit -m "feat(Web UI): 视频列表状态筛选 + 重试按钮"
```

---

## 验证清单

- [ ] `pytest tests/test_monitor_cooldown_state.py` PASS
- [ ] `pytest tests/test_monitor_download_retry.py` PASS
- [ ] `pytest tests/test_monitor_retry_endpoint.py` PASS
- [ ] `python -m py_compile monitor/scheduler.py && echo "SYNTAX OK"
- [ ] 手动测试：429 场景触发退避逻辑

---

## 执行顺序

1. Task 1.1 → Task 1.2（数据层）
2. Task 2.1 → Task 2.2 → Task 2.3（核心调度）
3. Task 3.1 → Task 3.2（持久化 + API）
4. Task 4.1（Web UI）
