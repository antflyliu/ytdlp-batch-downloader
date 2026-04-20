# 监控下载队列重试与退避机制设计

## 背景与目标

当前监控模块的自动下载存在三个问题：

1. **全局池竞争** — 多账户共用 `ThreadPoolExecutor(max_workers=2)`，一个账户视频多时会占用其他账户的下载带宽
2. **下载失败无持久化** — daemon 线程退出后未完成任务直接丢失，进程重启后无法恢复
3. **429 无退避重试** — YouTube 下载 429 时直接切换代理/直连，不等待冷却，重试效率低

---

## 需求

1. **per-account 独立下载池** — 每账户独立线程池（max_workers 可配置，默认 2），账户间互不干扰
2. **429 退避重试** — 直连/代理 429 后按退避时间重试（60s → 120s → 180s，上限，最多 3 次；每次加 0~10s jitter）
3. **失败持久化** — 3 次重试均失败后写入 `monitor_videos` 表（含 event_id 批次信息），Web UI 手动勾选重试

---

## 架构概览

### 全局状态（线程安全）

```python
import threading

# scheduler.py — 全局退避状态（进程级别，线程安全）
_proxy_cooldown_until: dict[str, float]  # proxy_url → 退避截止时间（monotonic）
_proxy_retry_count: dict[str, int]       # proxy_url → 当前重试次数
_proxy_lock = threading.Lock()            # 保护 proxy 退避状态的写入

_direct_cooldown_until: float | None     # 全局直连退避截止时间
_direct_retry_count: int = 0             # 全局直连退避重试次数
_direct_lock = threading.Lock()           # 保护直连退避状态的写入
```

> **线程安全**：所有对 `_proxy_cooldown_until` / `_direct_cooldown_until` 的读写必须包在 lock 内，防止多线程并发写入导致丢失更新。

### per-account 池

```python
# scheduler.py
_account_pools: dict[int, ThreadPoolExecutor]  # account_id → 独立池
_account_pools_lock = threading.Lock()          # 保护账户池的创建/销毁
```

每个账户有独立 `ThreadPoolExecutor(max_workers=2)`，账户间下载完全隔离。

**池生命周期**：
- 创建：首次触发该账户下载时 lazily 创建
- 销毁：账户被禁用时销毁；进程退出时通过 `_shutdown_auto_download_pool` 处理

### 视频状态机（内存状态，`pending_retry` 不持久化）

```
pending → running → pending_retry → pending_retry → pending_retry → failed/done
                 ↓
            （429 时进入 pending_retry，仅内存状态，进程重启后丢失）
```

> `pending_retry` 是纯内存状态，不写入 SQLite。进程重启时，正在退避中的视频会留在 `running` 状态 → 重启恢复时统一标记为 `failed`。

---

## 下载流程

### 取到视频后，决策路径

```
退避时间 = min(60 * retry_count, 180) + random(0, 10)
# retry_count=1 → 60~70s, retry_count=2 → 120~130s, retry_count=3 → 180~190s

if 使用代理:
    if proxy 在退避中:
        → 等退避结束 → 重试同一代理
    else:
        → 下载
            ├─ 429 → with _proxy_lock: proxy_cooldown[proxy] = now + 退避时间; retry_count++
            │         ├─ retry_count <= 3: sleep(退避时间) → 重试
            │         └─ retry_count > 3:  标记 failed（最终失败）
            └─ 非429失败 → 直接标记 failed

else（直连）:
    if 直连在退避中:
        → 等退避结束 → 下载
            ├─ 429 → with _direct_lock: retry_count++; cooldown = min(60*retry_count, 180)+jitter
            │         └─ retry_count > 3 → 标记 failed（最终失败）
            └─ 非429失败 → 直接标记 failed
    else:
        → 下载（同上）
```

### 429 检测

当前 `batch_download` 返回值中无 `rate_limited` 标识，429 通过 `is_proxy_retryable_error()` 函数在内部决定是否切换代理，但不返回给调用方。

**新增检测点**：在 `batch_download` 内部，捕获 yt-dlp 错误输出，当 `is_proxy_retryable_error(err)` 为 True 且错误信息含 `429` 时，设置返回值中的 `is_rate_limited=True`。

```python
# Youtube_Downloader.py 新增返回值字段
result = {
    "url": url,
    "状态": "失败",
    "信息": error_msg,
    "is_rate_limited": True,  # 新增：标识是否为 429
}
```

调用方（scheduler）据此判断是否为 429，进入退避流程。

### 代理 429 失败后切直连

```
proxy 第 3 次 429 仍失败 → 标记 video 为 pending，切换直连下载
→ 走直连退避逻辑
```

### 持久化时机

- 视频 `retry_count > 3` 最终失败
- 或 yt-dlp 返回非 429 的明确错误（如网络中断、文件写入失败）

```sql
UPDATE monitor_videos
SET download_status = 'failed',
    failed_reason = :reason,      -- e.g. "429 rate limit after 3 retries"
    failed_at = :now,
    failed_event_id = :event_id,   -- 关联触发扫描的 event
    retry_count = :retry_count
WHERE id = :video_id
```

---

## 数据模型

### monitor_videos 新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `failed_reason` | TEXT | 最后一次失败原因 |
| `failed_at` | TEXT | ISO 时间 |
| `failed_event_id` | INTEGER | 关联 event_id（FK → monitor_events.id） |
| `retry_count` | INTEGER DEFAULT 0 | 当前重试次数 |

迁移 SQL（`monitor/db/migrations.py`）：

```sql
ALTER TABLE monitor_videos
  ADD COLUMN failed_reason TEXT;
ALTER TABLE monitor_videos
  ADD COLUMN failed_at TEXT;
ALTER TABLE monitor_videos
  ADD COLUMN failed_event_id INTEGER REFERENCES monitor_events(id);
ALTER TABLE monitor_videos
  ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
```

### 重试计数持久化

每次提交下载前，更新 `retry_count` 到 SQLite：
```sql
UPDATE monitor_videos SET retry_count = :n WHERE id = :id
```

---

## Web UI 改动

### 视频列表状态筛选

- 新增 status 筛选项：**all / downloading / downloaded / failed**
- 默认显示 non-failed（避免每次看到一堆历史失败）

### 批量重试

1. 筛选 `download_status='failed'`
2. 勾选目标视频
3. 点击"重试失败"按钮 → POST `/api/videos/retry`

**新增 API 端点** `POST /api/videos/retry`：

Request body:
```json
{
  "video_ids": [1, 2, 3],  // 视频 ID 数组
  "account_id": 1               // 账户 ID（必填）
}
```

行为：
- 将指定 `video_ids` 的 `failed` 视频 `retry_count` 重置为 0
- 将 `download_status` 从 `failed` 改为 `pending`
- 视频重新入对应账户的下载队列

```sql
UPDATE monitor_videos
SET download_status = 'pending',
    retry_count = 0,
    failed_reason = NULL,
    failed_at = NULL,
    failed_event_id = NULL
WHERE id IN (:video_ids) AND download_status = 'failed'
```

### 重试行信息

- failed 行 tooltip 显示 `failed_reason` 和 `failed_at`
- 重试成功后清除 failed 相关字段

---

## 重启恢复

进程启动时，将 `download_status='running'` 的记录标记为 `failed`（防止僵尸任务）：

```sql
UPDATE monitor_videos
SET download_status = 'failed',
    failed_reason = '服务重启导致任务中断'
WHERE download_status = 'running'
```

---

## 错误恢复策略总结

| 场景 | 处理方式 |
|------|---------|
| 直连 429 | 退避（60s→120s→180s），jitter(0~10s)，最多 3 次 |
| 代理 429 | 等退避结束重试同代理；3 次后切直连 |
| 共用代理被限 | 使用同一 proxy 的所有账户共享退避状态 |
| 非 429 失败 | 直接标记 failed，一次到位 |
| 代理切直连后 429 | 继承直连退避逻辑 |
| 退避期间其他视频 | 代理视频继续；直连视频等退避结束 |

---

## 关键实现点

1. **429 检测点** — `batch_download` 新增 `is_rate_limited=True` 返回值，调用方据此进入退避流程
2. **线程安全退避状态** — `_proxy_lock` / `_direct_lock` 保护所有退避状态的读写
3. **per-account 池** — `_account_pools[account_id]` 管理账户独立线程池，lazy 创建，账户禁用时销毁
4. **退避时间** — `min(60 * retry_count, 180) + random(0, 10)`，上限 180s
5. **持久化** — 每次提交下载前更新 `retry_count`，最终失败时写入 `failed_reason/failed_at/failed_event_id`
6. **重启恢复** — 服务启动时将 `running` 标记为 `failed`
7. **pending_retry 纯内存** — 不写入 SQLite，进程重启时在退避中的视频会丢失（由重启恢复统一处理）

---

## 不纳入本次的设计点

- cooldown 期间后台探测代理是否恢复（复杂度高，jitter 足够）
- 多代理账户的代理轮换策略（现有 proxy_pool 逻辑已处理）
- 直连退避状态精细化到 per-IP（当前为全局直连退避，够用）
- cooldown 期间用新代理绕过退避（需额外 proxy provider 逻辑）
