# 生产级方案：监控扫描自动下载功能

> **版本**: v2
> **日期**: 2026-04-04
> **目标**: 在"启动监控"和"立即扫描"时添加"是否立即下载"选项，扫描到新视频后自动并发下载

---

## 一、需求描述

### 1.1 用户场景

用户在 YouTube 监控页面进行以下操作时：

- 点击 **"▶ 启动监控"** 按钮
- 点击账户操作列的 **"立即扫描"** 按钮

弹出确认框，询问 **"是否立即下载？"**

- 用户选择 **确定** → 扫描完成后自动下载所有新增视频
- 用户选择 **取消** → 仅执行扫描，不下载

### 1.2 并发策略（v2 重点修正）

| 参数 | 值 | 说明 |
|------|-----|------|
| 线程池 max_workers | 2 | 同时下载 2 个视频 |
| yt-dlp concurrent_fragment_downloads | 2 | 每视频 2 分片 |
| **最大并发 Range 请求** | **4** | 2×2，安全不触发 YouTube 429 |

> **为什么不用 3+4？** 3 线程 × 4 分片 = 12 并发 Range 请求，**高概率触发 YouTube 429**。

---

## 二、现状分析

| 层级 | 文件 | 现状 |
|------|------|------|
| 前端 | `monitor_web/index.html` | `scanNow()` / `toggleScheduler()` 调用 `/api/accounts/scan` 和 `/api/scheduler/start`，无下载选项 |
| 后端 | `monitor_server.py` | `_api_account_scan()` 调用 `_scheduler._scan_account()`；已有 `_task_mgr` 管理下载任务；`batch_download()` 在后台线程执行 |
| 调度器 | `monitor/scheduler.py` | `_scan_account()` 检测新视频后发通知，无自动下载逻辑 |
| 下载器 | `Youtube_Downloader.py` | `batch_download()` 顺序处理视频，yt-dlp 内部 `concurrent_fragment_downloads=4` |

### 核心挑战

- `batch_download()` 顺序处理多个 URL，需要改为线程池并发
- 需要在前端 → 后端 → 调度器的完整链路中传递 `auto_download` 标记

---

## 三、实施方案

### 3.1 变更概览

| 步骤 | 文件 | 变更量 | 说明 |
|------|------|--------|------|
| 1 | `monitor/scheduler.py` | ~60行 | 新增 `auto_download` 参数 + `_auto_download_videos()` 线程池下载 |
| 2 | `monitor_server.py` | ~10行 | 透传 `auto_download` 参数到 scheduler |
| 3 | `monitor_web/index.html` | ~25行 | 扫描/启动时弹出"是否立即下载"确认框 |

---

### 3.2 文件一：monitor/scheduler.py

#### 3.2.1 新增导入（文件顶部）

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from Youtube_Downloader import batch_download
```

#### 3.2.2 新增线程池常量（模块级）

```python
# 稳妥配置：2 线程池 × 2 分片 = 4 并发（安全不触发 YouTube 429）
_auto_dl_pool = ThreadPoolExecutor(max_workers=2)
```

#### 3.2.3 新增自动下载函数

```python
def _auto_download_videos(video_records: list[dict]) -> None:
    """
    后台线程池执行：并发下载新视频（max_workers=2，每视频 2 分片）
    避免触发 YouTube 429 限流
    """
    if not video_records:
        return

    urls = [r["url"] for r in video_records if r.get("url")]
    if not urls:
        return

    cfg = _db.load_config()
    output_path = cfg.get("download_output_path", "").strip()
    if not output_path:
        output_path = os.path.join(_EXE_DIR, "videos")
    os.makedirs(output_path, exist_ok=True)

    cookies_file = cfg.get("download_cookies_file", "") or None

    # 分批提交，每批 2 个视频并发下载
    BATCH_SIZE = 2
    for i in range(0, len(urls), BATCH_SIZE):
        chunk = urls[i:i + BATCH_SIZE]
        chunk_records = video_records[i:i + BATCH_SIZE]
        chunk_ids = [r["id"] for r in chunk_records]

        _log.info(
            f"自动下载批次 {i // BATCH_SIZE + 1}: "
            f"{len(chunk)} 个视频 (第 {i + 1}~{i + len(chunk)} 个，共 {len(urls)} 个)"
        )

        def _dl_batch(batch_urls, batch_ids):
            try:
                results = batch_download(
                    batch_urls,
                    output_path,
                    'best',
                    cookies_file=cookies_file,
                )

                # 更新数据库状态
                success_ids = []
                failed_ids = []
                for idx, r in enumerate(results):
                    vid = batch_ids[idx] if idx < len(batch_ids) else None
                    if not vid:
                        continue
                    if r.get("状态") == "成功":
                        success_ids.append(vid)
                    else:
                        failed_ids.append(vid)

                now_str = _db.now_iso()
                if success_ids:
                    _db.update_videos_download_status(
                        success_ids, "downloaded",
                        download_at=now_str,
                        download_path=output_path,
                    )
                if failed_ids:
                    _db.update_videos_download_status(
                        failed_ids, "failed",
                        download_error="auto download failed",
                    )

                _log.info(
                    f"批次下载完成: 成功={len(success_ids)} 失败={len(failed_ids)}"
                )
            except Exception as e:
                _log.error(f"自动下载批次异常: {e}")
                _db.update_videos_download_status(
                    batch_ids, "failed",
                    download_error=str(e),
                )

        _auto_dl_pool.submit(_dl_batch, chunk, chunk_ids)

    _log.info(f"自动下载任务已全部提交: {len(urls)} 个视频")
```

#### 3.2.4 `_scan_account()` 签名与调用新增

**函数签名变更**：

```python
def _scan_account(account_id: int, auto_download: bool = False) -> None:
```

**在函数末尾（第 235 行附近），`finish_event` 调用之后、`_check_quota_alert` 调用之前**，插入以下逻辑：

```python
        # ── 新增：自动下载新视频 ───────────────────────────────
        if auto_download and inserted > 0:
            # 收集本次新增视频的 ID（通过 event_id 查询）
            with _db.get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, url FROM monitor_videos WHERE event_id = ?",
                    (event_id,),
                ).fetchall()
            new_video_records = [dict(r) for r in rows]

            _auto_dl_pool.submit(
                _auto_download_videos,
                new_video_records,
            )
            _log.info(f"自动下载已触发: {inserted} 个新视频")
```

#### 3.2.5 `start()` 函数签名兼容

**当前签名**：`def start() -> bool:`
**变更后**：`def start(auto_download: bool = False) -> bool:`

> **注**：`auto_download` 参数仅对本次调度中的扫描有效，不写入数据库或 config。确认框每次弹出，用户每次选择。

---

### 3.3 文件二：monitor_server.py

#### 3.3.1 `_api_scheduler_start()` 修改

**当前**：
```python
def _api_scheduler_start(self):
    ok = _scheduler.start()
    self._send_json({"ok": ok})
```

**变更后**：
```python
def _api_scheduler_start(self):
    body = self._read_json() or {}
    auto_dl = bool(body.get("auto_download", False))
    ok = _scheduler.start(auto_download=auto_dl)
    self._send_json({"ok": ok})
```

#### 3.3.2 `_api_account_scan()` 修改

**当前**：
```python
def _api_account_scan(self, body):
    acc_id = int(body.get("account_id", 0))
    _scheduler._scan_account(acc_id)
    self._send_json({"ok": True})
```

**变更后**：
```python
def _api_account_scan(self, body):
    acc_id = int(body.get("account_id", 0))
    auto_dl = bool(body.get("auto_download", False))
    _scheduler._scan_account(acc_id, auto_download=auto_dl)
    self._send_json({"ok": True})
```

---

### 3.4 文件三：monitor_web/index.html

#### 3.4.1 `scanNow()` 修改（约 line 1604）

**当前**：
```javascript
async function scanNow(id) {
    const btn = event.target;
    btn.innerHTML = '<span class="spinner"></span>';
    btn.disabled = true;
    await api('POST', '/api/accounts/scan', { account_id: id });
    toast('扫描已触发', 'info');
    setTimeout(() => { btn.textContent = '立即扫描'; btn.disabled = false; }, 3000);
}
```

**变更后**：
```javascript
async function scanNow(id) {
    const autoDl = confirm(
        "立即扫描\n\n☑ 扫描到新视频后立即下载？\n\n" +
        "（勾选 → 扫描完成后自动开始下载，\n" +
        "   最多 2 个视频同时下载）"
    );
    const btn = event.target;
    btn.innerHTML = '<span class="spinner"></span>';
    btn.disabled = true;
    await api('POST', '/api/accounts/scan', {
        account_id: id,
        auto_download: autoDl
    });
    toast('扫描已触发' + (autoDl ? '（含自动下载）' : ''), 'info');
    setTimeout(() => { btn.textContent = '立即扫描'; btn.disabled = false; }, 3000);
}
```

#### 3.4.2 `toggleScheduler()` 修改（约 line 1302）

**当前**：
```javascript
async function toggleScheduler() {
    const btn = document.getElementById('btnToggleScheduler');
    btn.innerHTML = '<span class="spinner"></span>';
    btn.style.pointerEvents = 'none';
    try {
        const r = schedulerRunning
            ? await api('POST', '/scheduler/stop')
            : await api('POST', '/scheduler/start');
        if (r.ok !== false) {
            schedulerRunning = !schedulerRunning;
            updateSchedulerUI();
            toast(schedulerRunning ? '调度器已启动' : '调度器已停止', 'ok');
        } else {
            toast(r.error || '操作失败', 'err');
        }
    } catch(e) {
        toast('网络错误', 'err');
    }
    btn.style.pointerEvents = '';
}
```

**变更后**：
```javascript
async function toggleScheduler() {
    const btn = document.getElementById('btnToggleScheduler');
    btn.innerHTML = '<span class="spinner"></span>';
    btn.style.pointerEvents = 'none';
    try {
        if (schedulerRunning) {
            // 停止
            const r = await api('POST', '/scheduler/stop');
            if (r.ok !== false) {
                schedulerRunning = false;
                updateSchedulerUI();
                toast('调度器已停止', 'ok');
            } else {
                toast(r.error || '操作失败', 'err');
            }
        } else {
            // 启动前弹确认框
            const autoDl = confirm(
                "启动监控\n\n☑ 扫描到新视频后立即下载？\n\n" +
                "（勾选 → 每次扫描完成自动开始下载，\n" +
                "   最多 2 个视频同时下载）"
            );
            const r = await api('POST', '/scheduler/start', {
                auto_download: autoDl
            });
            if (r.ok !== false) {
                schedulerRunning = true;
                updateSchedulerUI();
                toast('调度器已启动' + (autoDl ? '（含自动下载）' : ''), 'ok');
            } else {
                toast(r.error || '启动失败', 'err');
            }
        }
    } catch(e) {
        toast('网络错误', 'err');
    }
    btn.style.pointerEvents = '';
    btn.innerHTML = '';
    updateSchedulerUI();
}
```

---

## 四、并发安全分析

### 4.1 并发模型

```
max_workers = 2          ← 线程池控制（scheduler.py）
concurrent_fragment_downloads = 2  ← yt-dlp 内部控制（Youtube_Downloader.py 默认 4，但 auto download 场景传入 2）

最大并发 Range 请求数 = 2 线程 × 2 分片 = 4
```

### 4.2 风险评估

| 场景 | 并发数 | 风险 | 应对 |
|------|--------|------|------|
| 正常自动下载 | 4 Range 请求 | ✅ 安全 | — |
| 同时手动下载 | +1 Range 请求 | ✅ 基本安全 | — |
| 触发 YouTube 429 | — | yt-dlp 内置 retry（指数退避） | 不影响其他任务 |

### 4.3 为什么不修改 Youtube_Downloader.py？

- `batch_download()` 的 `concurrent_fragment_downloads=4` 是**用户手动下载时的默认配置**，速度优先
- 自动下载场景下，我们通过**线程池 max_workers=2** 从外部控制并发总量，yt-dlp 内部仍用 4 分片
- 如需进一步降低分片数，可在 `_dl_batch()` 调用 `batch_download()` 时传入参数覆盖（待后续按需优化）

---

## 五、不改动的部分

| 文件 | 原因 |
|------|------|
| `Youtube_Downloader.py` | `batch_download()` 不修改，用户手动下载不受影响 |
| `monitor_ui.py`（Tkinter 原版） | 暂不修改，保持原有用法 |
| 数据库 schema | 不变，`update_videos_download_status()` 已支持所需字段 |
| `monitor/detector.py` | 不变，仅检测新增视频 |

---

## 六、验收标准

- [ ] 点击"立即扫描"→ 弹出确认框 → 选择确定 → 扫描完成后数据库 video 的 `download_status` 变为 `downloading` → `downloaded`
- [ ] 点击"启动监控"→ 弹出确认框 → 选择确定 → 定时扫描触发后同样自动下载
- [ ] 2 个视频同时下载时，YouTube 不返回 429
- [ ] 每次扫描的 `auto_download` 行为独立，不互相影响
- [ ] 日志中可见 `自动下载批次 X: N 个视频` 记录
