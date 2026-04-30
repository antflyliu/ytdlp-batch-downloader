# 微信公众号原生采集 Sticky Session 代理方案

> **目标：** 企业级多账号高并发采集场景下，确保同一会话的所有请求绑定同一代理 IP，避免微信风控触发。

---

## 1. 问题定义

### 1.1 当前行为

`proxy_policy.py` 的 `resolve_native_proxy_plan()` 调用 `proxy_router.resolve_proxy_download()`，对于 `list_api` 类型 Provider，返回的是一个**候选池**（5个代理），每次请求从池中按打分排序取 top：

```python
# 当前实现（proxy_candidate_pool.py）
def get_candidates_for_scenario(self, scenario, max_count=5):
    rows = conn.execute(SQL, params).fetchall()
    return rows[:max_count]  # 每次取不同的候选
```

同一 `biz` 账号的多次请求可能被分配到不同的代理 IP：

```
请求1: GET /searchbiz    → 代理 A (120.1.2.3)
请求2: GET /appmsgpublish → 代理 B (120.1.2.4)  ← 不同 IP！
请求3: GET /appmsgpublish → 代理 A (120.1.2.3)
```

### 1.2 微信风控触发条件

微信对账号维度的异常检测包括：
- 同一账号短时间内来自**多个不同 IP** → 高风险
- Cookie 中的登录态与请求 IP 不一致 → 极高风险
- 请求频率突增 + IP 分散 → 直接限流

### 1.3 影响范围

| 场景 | 当前风险 | 严重程度 |
|------|---------|---------|
| 扫码登录全程 | ✅ 已解决（proxy_plan 固定不变） | — |
| 登录后 API 调用（搜索/拉列表/下载） | ❌ 每次请求可能换 IP | 高 |
| 多账号并发采集 | ❌ 跨账号 IP 交叉污染 | 极高 |

---

## 2. 解决方案

### 2.1 核心思路：会话级代理亲和性

为每个采集会话分配一个**代理亲和标签**，同一标签的所有请求绑定同一代理 IP，直到会话结束或代理失效。

```
会话1 (biz=wxid_xxx, session_id=abc) → 代理 A (120.1.2.3)
会话2 (biz=wxid_yyy, session_id=def) → 代理 B (120.1.2.4)
会话3 (biz=wxid_zzz, session_id=ghi) → 代理 C (120.1.2.5)
```

### 2.2 方案选型

| 方案 | 思路 | 优点 | 缺点 | 推荐度 |
|------|------|------|------|--------|
| A. Session-ID → 代理绑定 | 会话 ID 与代理 IP 静态映射，存在 Redis/内存 | 实现简单，查询 O(1) | 单点，代理故障需手动切换 | ⭐⭐⭐ |
| B. 会话代理池 | 每个会话维护自己的小代理池（2-3个），主代理故障自动切换 | 容错强，隔离性好 | 实现复杂，资源占用高 | ⭐⭐ |
| **C. 代理亲和标签 + LRU 亲和缓存** | 将"账号+会话"组合作为亲和键，绑定候选池中的最优代理；通过 LRU 缓存保证同一会话复用同一 IP | 实现中等、改动小、天然支持会话内多请求绑定、自动亲和、无单点 | 需修改候选池查询逻辑 | **⭐⭐⭐⭐** |

**推荐方案 C**，改动最小、效果最佳。

---

## 3. 详细设计

### 3.1 数据模型变更

#### 3.1.1 新增 `proxy_session_affinity` 表

```sql
CREATE TABLE IF NOT EXISTS proxy_session_affinity (
    affinity_key     TEXT PRIMARY KEY,   -- 格式: "{account_id}:{session_id}"
    biz_username     TEXT,               -- 公众号原始 ID（用于调试）
    proxy_endpoint   TEXT NOT NULL,       -- 代理 URL (http://user:pass@host:port)
    masked_endpoint  TEXT NOT NULL,      -- 脱敏日志用 (http://***:****@host:port)
    provider_id     INTEGER,            -- 来源 Provider ID（用于健康追溯）
    provider_name   TEXT,               -- 来源 Provider 名称
    sticky          INTEGER NOT NULL DEFAULT 1,  -- 1=启用亲和 0=禁用
    hit_count       INTEGER NOT NULL DEFAULT 0,    -- 命中次数
    created_at      TEXT NOT NULL,
    last_used_at    TEXT NOT NULL,
    expires_at      TEXT                -- 会话过期时间（NULL=不过期）
);

CREATE INDEX IF NOT EXISTS idx_psa_affinity_key ON proxy_session_affinity(affinity_key);
CREATE INDEX IF NOT EXISTS idx_psa_last_used ON proxy_session_affinity(last_used_at);
CREATE INDEX IF NOT EXISTS idx_psa_expires ON proxy_session_affinity(expires_at);
```

#### 3.1.2 亲和键（Affinity Key）生成规则

```
affinity_key = f"{account_id}:{session_id}"
```

| 场景 | account_id | session_id | affinity_key 示例 |
|------|-----------|-----------|-----------------|
| 单次采集会话 | account 表 id | UUID 或采集任务 ID | `42:abc123-def456` |
| 长连接轮询 | account 表 id | `poll_{task_id}` | `42:poll_task789` |

#### 3.1.3 亲和键生命周期

- **创建**：首次为某会话解析代理时写入
- **更新**：每次代理请求后更新 `last_used_at` 和 `hit_count`
- **过期**：`expires_at` 为空表示不过期，由会话主动清理；LRU 缓存负责内存淘汰

### 3.2 核心流程变更

#### 3.2.1 新增亲和缓存模块

在 `monitor/proxy/` 下新增 `session_affinity.py`：

```python
from functools import lru_cache
from threading import RLock
from monitor.proxy.session_affinity import ProxySessionAffinity

_affinity = ProxySessionAffinity()

# --- LRU 内存缓存（进程内，秒级访问） ---
@lru_cache(maxsize=1024)
def _get_cached_affinity(affinity_key: str) -> str | None:
    """线程安全的 LRU 缓存，同一会话多次调用直接返回缓存值。"""
    return _affinity.get(affinity_key)

def resolve_proxy_for_session(
    account_id: int,
    session_id: str,
    *,
    allow_sticky: bool = True,
) -> ProxyRouteResult | None:
    """
    为指定会话解析代理。
    1. 先查 LRU 缓存 → 亲和命中
    2. 再查 DB 亲和表 → 亲和命中
    3. 最后走 proxy_router 选一个新代理 → 建立亲和绑定
    """
    affinity_key = f"{account_id}:{session_id}"

    # Step 1: LRU 缓存命中
    cached = _get_cached_affinity(affinity_key)
    if cached:
        return ProxyRouteResult(proxy_url=cached, source="affinity_cache", ...)

    # Step 2: DB 亲和命中
    db_affinity = _affinity.get(affinity_key)
    if db_affinity and db_affinity.get("sticky"):
        _get_cached_affinity.cache_clear()  # 局部清除让新值进缓存
        _get_cached_affinity(affinity_key)  # 重新触发缓存填充
        return ProxyRouteResult(proxy_url=db_affinity["proxy_endpoint"], source="affinity_db", ...)

    # Step 3: 无亲和 → 走 Router 选新代理
    new_result = proxy_router.resolve_proxy_download(account_id=account_id, ...)
    if new_result and allow_sticky:
        _affinity.bind(affinity_key, new_result)
        _get_cached_affinity.cache_clear()
        _get_cached_affinity(affinity_key)

    return new_result
```

#### 3.2.2 修改 `proxy_policy.py` 的入口函数

```python
# proxy_policy.py
def resolve_native_proxy_plan(
    account: dict,
    *,
    cookies_present: bool = False,
    session_id: str | None = None,   # ← 新增参数
    allow_sticky: bool = True,         # ← 新增参数
) -> SubtitleProxyPlan:
    # ... 原有逻辑 ...

    if session_id and allow_sticky:
        # 替换原有的 proxy_router 调用
        result = resolve_proxy_for_session(
            account_id=account.get("id"),
            session_id=session_id,
            allow_sticky=True,
        )
        if result:
            return SubtitleProxyPlan(
                proxies=[result.masked_proxy_endpoint],
                source="affinity",
                reason=f"会话亲和: {session_id}",
                direct_fallback=False,
            )

    # 回退到原有逻辑
    raw = proxy_router.resolve_proxy_download(account_id=account.get("id"), ...)
    ...
```

#### 3.2.3 修改 `native_client.py` 的会话初始化

```python
# native_client.py
class WechatNativeClient:
    def __init__(self, account_id: int, session_id: str | None = None):
        self.account_id = account_id
        self.session_id = session_id or str(uuid.uuid4())
        self.proxy_plan: SubtitleProxyPlan | None = None

    def _resolve_proxy(self) -> SubtitleProxyPlan:
        return resolve_native_proxy_plan(
            account=self.account,
            cookies_present=bool(self.session_cookies),
            session_id=self.session_id,       # 透传
            allow_sticky=True,               # 默认启用亲和
        )
```

#### 3.2.4 亲和绑定时机

| 时机 | 操作 |
|------|------|
| `start_login()` | 首次解析代理 → 建立亲和 `account_id:session_id` |
| `poll_scan()` | 复用已有亲和（同 session_id） |
| `confirm_login()` | 复用已有亲和（同 session_id） |
| `search_biz()` | 复用已有亲和（同 session_id） |
| `fetch_article_list()` | 复用已有亲和（同 session_id） |
| `logout()` | 清除亲和绑定 |

#### 3.2.5 亲和失效与切换

**亲和失效条件：**
- 代理返回 403/401/302（登录态失效）→ 清除亲和，下次请求重新选代理
- 代理连续失败 N 次（N=3，可配置）→ 降级并清除亲和
- 会话主动 `logout()` → 清除亲和

```python
# 亲和失效时调用
_affinity.unbind(affinity_key)
_get_cached_affinity.cache_clear()

# 自动切换到下一个可用代理（不改变 session_id）
new_result = resolve_proxy_for_session(
    account_id=account_id,
    session_id=session_id,  # 同一个 session_id
    allow_sticky=True,       # 重新建立亲和
)
```

### 3.3 健康检查与亲和更新

**亲和代理健康状态追踪：**

```python
def report_proxy_result(affinity_key: str, success: bool, latency_ms: int | None):
    """每次代理请求完成后报告结果，自动更新亲和代理质量。"""
    entry = _affinity.get(affinity_key)
    if not entry:
        return

    entry["hit_count"] += 1
    entry["last_used_at"] = now_iso()

    if not success:
        entry["failure_count"] = entry.get("failure_count", 0) + 1
        if entry["failure_count"] >= 3:
            # 连续3次失败 → 解除亲和，下次重新选
            _affinity.unbind(affinity_key)
            _get_cached_affinity.cache_clear()
    else:
        entry["failure_count"] = 0
```

### 3.4 多账号并发隔离

```
账号A 会话1 (biz=wxid_aaa) → 代理 X
账号A 会话2 (biz=wxid_bbb) → 代理 Y          ← 不同会话，不同代理
账号B 会话1 (biz=wxid_ccc) → 代理 Z          ← 不同账号，不同代理
```

每个 `account_id:session_id` 组合独立绑定，互不干扰。

---

## 4. 数据库迁移

```sql
-- 新增 proxy_session_affinity 表
CREATE TABLE IF NOT EXISTS proxy_session_affinity (
    affinity_key     TEXT PRIMARY KEY,
    biz_username     TEXT,
    proxy_endpoint   TEXT NOT NULL,
    masked_endpoint  TEXT NOT NULL,
    provider_id     INTEGER,
    provider_name   TEXT,
    sticky          INTEGER NOT NULL DEFAULT 1,
    hit_count       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    last_used_at    TEXT NOT NULL,
    expires_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_psa_affinity_key ON proxy_session_affinity(affinity_key);
CREATE INDEX IF NOT EXISTS idx_psa_last_used ON proxy_session_affinity(last_used_at);
CREATE INDEX IF NOT EXISTS idx_psa_expires ON proxy_session_affinity(expires_at);

-- 定期清理过期亲和（可配置 TTL，默认 24 小时）
-- DELETE FROM proxy_session_affinity WHERE last_used_at < datetime('now', '-1 day');
```

---

## 5. 配置项

| 配置项 | 默认值 | 说明 |
|-------|--------|------|
| `wechat_sticky_session_enabled` | `true` | 公众号采集会话代理亲和总开关 |
| `wechat_sticky_session_ttl_hours` | `24` | 亲和记录过期时间（小时） |
| `wechat_sticky_max_failures` | `3` | 连续失败次数阈值，超过则解除亲和 |
| `wechat_sticky_lru_cache_size` | `1024` | 进程内 LRU 缓存容量 |

---

## 6. 实施计划

### Phase 1: 核心基础设施（改动最小路径）
1. 新增 `proxy_session_affinity.py` 模块（亲和缓存 + DB 持久化）
2. 新增 `proxy_session_affinity` 数据库表
3. 修改 `proxy_policy.py` 入口，增加 `session_id` 参数
4. 修改 `native_client.py`，在初始化时生成 `session_id` 并透传给 `resolve_native_proxy_plan`
5. 修改 `html_export.py`，传递 `session_id`

### Phase 2: 健康追踪
6. 实现 `report_proxy_result()` — 亲和代理质量追踪
7. 实现亲和失效自动切换逻辑
8. 实现 `logout()` 清除亲和

### Phase 3: 运维增强
9. 管理后台：查看当前活跃会话与代理绑定关系
10. 管理后台：手动解绑/强制切换代理
11. 定时任务：清理过期亲和记录

---

## 7. 测试场景

| # | 场景 | 预期行为 |
|---|------|---------|
| T1 | 同一 session_id 连续 10 次 API 调用 | 全部命中同一代理 IP |
| T2 | session_id=A 和 session_id=B 并发调用 | 分别命中不同代理 IP |
| T3 | 亲和代理返回 403 连续 3 次 | 第3次后解除亲和，下次重新选代理 |
| T4 | 服务重启后，同一 session_id 请求 | LRU 缓存 miss → DB 亲和表 hit → 复用同一代理 |
| T5 | logout() 后同一 session_id 新请求 | 亲和已清除 → 分配新代理 |

---

## 8. 非功能性考量

- **向后兼容**：`allow_sticky=True` 为默认，现有调用方式无需改动
- **回滚友好**：只需关闭 `wechat_sticky_session_enabled`，系统回退到当前行为
- **日志可追踪**：亲和命中/失效均输出带 `sticky_session` 标签的 INFO 日志
- **资源占用**：LRU 缓存最大 1024 条，按 1 条 ~200B 估算，约 200KB
- **DB 写入**：仅在亲和建立/失效时写入，不影响请求路径性能
