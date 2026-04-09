# list_api 统一接入方案实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `list_api` 类型动态代理提供方建立一套生产级统一接入平台，支持多种外部代理 API 归一化为候选代理池，并完整集成到现有下载路由链路。

**Architecture:** 采用模板优先 + 专属 adapter 兜底的混合接入策略；SQLite 持久候选池 + 内存热缓存的双层存储；安全校验 → 轻量探测 → 场景化验证的分层质量门控；`list_api` 输出 `proxy_pool` 接入现有 router，不破坏 `rotating_gateway` / `local_gateway` 的单 proxy 语义。

**Tech Stack:** Python 3.12 / SQLite (WAL) / Fernet (secrets) / yt-dlp / 现有 monitor 模块

---

## 依赖关系总图

```
Phase 1（平台基础）
  └─ Phase 2（模板执行器 + 路由集成）
        └─ Phase 3（质量与观测）
              └─ Phase 4（专属 adapter，按需）
```

---

## 文件归属

### 新增文件

| 文件 | 职责 |
|---|---|
| `monitor/schema.sql` (改) | 新增 `dynamic_proxy_candidates` 表 |
| `monitor/db.py` (改) | 新增候选池 CRUD、secret 加密/解密 |
| `monitor/proxy_router.py` (改) | 扩展 canonical model、改造 `_resolve_list_api` 调 selector |
| `monitor/provider_templates.py` | 模板执行器：build_request / fetch / extract / normalize |
| `monitor/provider_adapters/` | 专属 adapter 目录（复杂 provider 按需扩展） |
| `monitor/proxy_candidate_pool.py` | SQLite 持久池 + 内存热缓存 + TTL + 去重 |
| `monitor/proxy_selector.py` | 场景过滤 + score 排序 + topN 输出 |
| `monitor/proxy_validator.py` | Level 0/1/2 验证链路 |
| `monitor/provider_health.py` (改) | 扩展支持 candidate 级熔断 |
| `monitor_server.py` (改) | 新增 provider 候选预览、手动刷新、模板校验 API |
| `monitor/scheduler.py` (改) | 复用现有 APScheduler 注册 provider refresh / cleanup / reprobe 周期任务 |
| `tests/test_proxy_candidates.py` | 候选池 CRUD 测试 |
| `tests/test_proxy_templates.py` | 模板执行器测试 |
| `tests/test_proxy_selector.py` | selector 测试 |
| `tests/test_proxy_validator.py` | 验证层测试 |
| `tests/test_list_api_routing.py` | list_api 路由集成测试 |
| `tests/test_provider_health_extended.py` | candidate 级熔断测试 |

### 不改文件

| 文件 | 原因 |
|---|---|
| `Youtube_Downloader.py` | 继续只吃 `proxy` / `proxy_pool` |
| `monitor/dynamic_provider_resolver.py` | 继续只调 `proxy_router` |

---

## Phase 1：平台基础层

**目标：** 建立 canonical candidate 模型、持久化候选池表、基础 CRUD，并明确候选 secret 加密、TTL 清理与调度注册边界。`list_api` provider 配置后能落库，能被 router 查询到（此时还不拉外部 API，selector 返回空池）。

---

### Task 1: 新增 `dynamic_proxy_candidates` 表

**Files:**
- Modify: `monitor/schema.sql`（在文件末尾 `dynamic_proxy_providers` 表定义后追加）
- Modify: `monitor/db.py`（新增迁移 `v8_dynamic_proxy_candidates`）
- Create: `tests/test_proxy_candidates.py`

- [ ] **Step 1: 写失败的测试**

```python
def test_candidate_table_exists(self):
    conn = _db.get_connection()
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dynamic_proxy_candidates'").fetchall()
    self.assertEqual(len(rows), 1)

def test_add_and_get_candidate(self):
    pid = _db.add_dynamic_proxy_provider(name="Test", billing_tier="free", adapter_type="list_api", config_json={})
    cid = _db.add_proxy_candidate(provider_id=pid, protocol="http", host="1.2.3.4", port=8080, proxy_url="http://1.2.3.4:8080")
    c = _db.get_proxy_candidate(cid)
    self.assertEqual(c["host"], "1.2.3.4")
    self.assertEqual(c["protocol"], "http")

def test_candidate_key_uniqueness(self):
    pid = _db.add_dynamic_proxy_provider(name="Test2", billing_tier="free", adapter_type="list_api", config_json={})
    _db.add_proxy_candidate(provider_id=pid, protocol="http", host="1.2.3.4", port=8080, proxy_url="http://1.2.3.4:8080")
    # 同一 provider 同一条 proxy 不应重复写入
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        _db.add_proxy_candidate(provider_id=pid, protocol="http", host="1.2.3.4", port=8080, proxy_url="http://1.2.3.4:8080")

def test_cascade_delete_candidates_on_provider_delete(self):
    pid = _db.add_dynamic_proxy_provider(name="CascadeTest", billing_tier="free", adapter_type="list_api", config_json={})
    _db.add_proxy_candidate(provider_id=pid, protocol="http", host="5.6.7.8", port=80, proxy_url="http://5.6.7.8:80")
    _db.delete_dynamic_proxy_provider(pid)
    c = _db.get_proxy_candidate_by_provider(pid)
    self.assertEqual(len(c), 0)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd D:/WORKSPACE/video-download-space/ytdlp-batch-downloader && python -m pytest tests/test_proxy_candidates.py -v -x`
Expected: FAIL（表不存在，函数不存在）

- [ ] **Step 3: 在 schema.sql 末尾追加候选表 DDL**

```sql
-- dynamic_proxy_candidates 表
CREATE TABLE IF NOT EXISTS dynamic_proxy_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_key TEXT UNIQUE NOT NULL,
    provider_id INTEGER NOT NULL,
    protocol TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT,
    password_enc TEXT,
    auth_type TEXT DEFAULT 'none',
    masked_proxy_endpoint TEXT NOT NULL,
    country_code TEXT,
    region TEXT,
    city TEXT,
    anonymity TEXT,
    risk_level TEXT NOT NULL DEFAULT 'medium',
    supports_https INTEGER NOT NULL DEFAULT 1,
    supports_cookies INTEGER NOT NULL DEFAULT 0,
    supports_auto_download INTEGER NOT NULL DEFAULT 1,
    supports_sticky_session INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    last_probe_status TEXT DEFAULT 'unknown',
    last_probe_at TEXT,
    score REAL NOT NULL DEFAULT 0.0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_error_message TEXT,
    failure_category TEXT,
    provider_reference_id TEXT,
    ttl_expires_at TEXT,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (provider_id) REFERENCES dynamic_proxy_providers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_candidates_provider_ttl ON dynamic_proxy_candidates(provider_id, ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_candidates_score ON dynamic_proxy_candidates(score DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_probe ON dynamic_proxy_candidates(last_probe_status, ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_candidates_ttl ON dynamic_proxy_candidates(ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_candidates_key ON dynamic_proxy_candidates(candidate_key);
```

- [ ] **Step 4: 在 db.py 新增迁移 v8**

在 `_migrate_monitor_accounts` 中追加：

```python
if "v8_dynamic_proxy_candidates" not in applied:
    conn.execute("""CREATE TABLE IF NOT EXISTS dynamic_proxy_candidates (...全DDL...""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_provider_ttl ...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_score ...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_probe ...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_key ...")
    conn.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                 ("v8_dynamic_proxy_candidates", today))
```

- [ ] **Step 5: 在 db.py 新增候选池 CRUD 函数与 secret 工具**

- [ ] **Step 5.1: 新增候选 secret 工具函数**

```python
def _encrypt_candidate_secret(value: str | None) -> str | None:
    ...

def _decrypt_candidate_secret(value: str | None) -> str | None:
    ...

def _build_runtime_proxy_url(protocol: str, host: str, port: int,
                             username: str | None = None,
                             password: str | None = None) -> str:
    ...
```

- [ ] **Step 5.2: 实现候选池 CRUD 与运行时 URL 构造**

```python
def add_proxy_candidate(provider_id: int, protocol: str, host: str, port: int,
                        username: str = None, password: str = None,
                        auth_type: str = "none", country_code: str = None,
                        risk_level: str = "medium", provider_reference_id: str = None,
                        **kwargs) -> int:
    ...

def build_runtime_proxy_url(candidate: dict) -> str:
    ...

def get_proxy_candidate(candidate_id: int) -> dict | None:
    ...

def get_proxy_candidate_by_provider(provider_id: int, valid_only: bool = True) -> list[dict]:
    ...

def delete_expired_candidates() -> int:
    ...

def update_candidate_quality(candidate_id: int, success: bool, latency_ms: int = None,
                            error_message: str = None, failure_category: str | None = None) -> None:
    ...

def _iso_future(seconds: int) -> str:
    ...
```

- [ ] **Step 6: 运行测试验证通过**

Run: `python -m pytest tests/test_proxy_candidates.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add monitor/schema.sql monitor/db.py tests/test_proxy_candidates.py
git commit -m "feat(monitor): add dynamic_proxy_candidates table and CRUD"
```

---

### Task 2: Canonical Candidate Model dataclass

**Files:**
- Modify: `monitor/proxy_router.py`（在文件顶部 dataclass 区域追加）

- [ ] **Step 1: 写失败的测试**

```python
def test_canonical_candidate_dataclass_fields(self):
    from monitor.proxy_router import CanonicalProxyCandidate
    c = CanonicalProxyCandidate(
        candidate_key="abc123",
        provider_id=1,
        provider_name="geonode",
        protocol="http",
        host="1.2.3.4",
        port=8080,
        proxy_url="http://1.2.3.4:8080",
    )
    self.assertEqual(c.protocol, "http")
    self.assertEqual(c.score, 0.0)
    self.assertFalse(c.is_expired)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_proxy_router.py::TestProxyRouterDecisionLogic -v -k canonical`
Expected: FAIL（导入错误）

- [ ] **Step 3: 在 proxy_router.py 顶部 dataclass 区域追加**

```python
@dataclass
class CanonicalProxyCandidate:
    """统一候选代理模型。所有 list_api/public_feed 提供方最终归一为此对象。"""
    candidate_key: str
    provider_id: int
    provider_name: str
    provider_adapter: str = ""
    provider_reference_id: str | None = None
    protocol: str = "http"
    host: str = ""
    port: int = 0
    username: str | None = None
    password_enc: str | None = None
    auth_type: str = "none"           # none | basic | bearer | api_key
    masked_proxy_endpoint: str = ""
    country_code: str | None = None
    anonymity: str | None = None
    risk_level: str = "medium"
    supports_https: bool = True
    supports_cookies: bool = False
    supports_auto_download: bool = True
    supports_sticky_session: bool = False
    latency_ms: int | None = None
    last_probe_status: str = "unknown"
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    score: float = 0.0
    ttl_expires_at: str | None = None
    last_seen_at: str | None = None
    @property
    def is_expired(self) -> bool:
        ...

    def to_proxy_url(self, decrypt_secret=None, mask: bool = False) -> str:
        if mask:
            return self.masked_proxy_endpoint
        password = decrypt_secret(self.password_enc) if decrypt_secret and self.password_enc else None
        ...
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_proxy_router.py::TestProxyRouterDecisionLogic -v -k canonical`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add monitor/proxy_router.py
git commit -m "feat(proxy_router): add CanonicalProxyCandidate dataclass"
```

---

### Task 3: 改造 `_resolve_list_api` 为可调用骨架

**Files:**
- Modify: `monitor/proxy_router.py`（改造 `_resolve_list_api` 和 `_resolve_provider_proxy`）

**注意：** 此 Task 只做骨架，外部 API 拉取逻辑在 Phase 2 实现。当前让 `_resolve_list_api` 返回空列表（与 v1 行为一致），但要准备好接收 `scenario_context` 参数。

- [ ] **Step 1: 写失败的测试**

```python
def test_resolve_list_api_accepts_scenario_context(self):
    """list_api 解析应能接收 scenario_context 参数（Phase2 填入真实逻辑）"""
    import monitor.proxy_router as pr
    cand = pr.CanonicalProxyCandidate(
        candidate_key="test001",
        provider_id=999,
        provider_name="TestProvider",
        protocol="http",
        host="1.2.3.4",
        port=8080,
        proxy_url="http://1.2.3.4:8080",
    )
    # 当前骨架应返回空列表（Phase2 填入逻辑）
    result = pr._resolve_list_api_with_candidates(
        provider={"id": 999, "name": "Test", "config_json": {}, "adapter_type": "list_api",
                  "supports_cookies": False, "supports_auto_download": True, "supports_sticky_session": False,
                  "risk_level": "medium", "priority": 1},
        scenario_context={"is_auto_download": False, "cookies_present": False, "country_codes": []}
    )
    self.assertIsInstance(result, list)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_proxy_router.py -v -k list_api`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 改造 proxy_router.py**

在 `_resolve_list_api` 下方新增：

```python
def _resolve_list_api_with_candidates(
    provider: dict,
    scenario_context: dict,
) -> list[CanonicalProxyCandidate]:
    """
    Phase1 骨架：list_api provider 返回空列表（外部 API 拉取在 Phase2 实现）。
    Phase2 将替换为本函数体内的真实逻辑。

    scenario_context 包含：
        is_auto_download: bool
        cookies_present: bool
        country_codes: list[str]
        protocol_order: list[str]
        max_candidates: int
    """
    # TODO(Phase2): 调用 proxy_selector 从候选池/缓存/外部 API 获取候选
    return []
```

改造 `_resolve_provider_proxy` 支持 `list_api` 返回 `proxy_pool`：

```python
def _resolve_provider_proxy(candidate: ProxyProviderCandidate) -> str | None:
    # ... 现有逻辑不变 ...
    elif adapter == "list_api":
        # Phase2: list_api 不在这里处理，由 selector 返回 proxy_pool
        # 此处返回 None，保留向后兼容
        return None
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_proxy_router.py -v -k list_api`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add monitor/proxy_router.py
git commit -m "feat(proxy_router): prepare list_api skeleton for Phase2 integration"
```

---

## Phase 2：模板执行器 + 路由集成

**目标：** 实现模板执行器，从外部 API 拉取候选 → 标准化 → 入池；selector 按场景过滤并输出 `proxy_pool`；router 正确调用并集成到下载链路。

---

### Task 4: 模板执行器

**Files:**
- Create: `monitor/provider_templates.py`
- Create: `tests/test_proxy_templates.py`

- [ ] **Step 1: 写失败的测试**

```python
def test_build_request_get(httpx_mock):
    from monitor.provider_templates import TemplateFetcher
    fetcher = TemplateFetcher({
        "mode": "template",
        "base_url": "https://api.example.com",
        "list_path": "/proxies",
        "method": "GET",
        "query_defaults": {"limit": 50},
    }, auth_secret="test-token")
    req = fetcher.build_request(page=1)
    assert req["url"] == "https://api.example.com/proxies?limit=50&page=1"
    assert req["headers"]["Authorization"] == "Bearer test-token"

def test_extract_items_with_jsonpath():
    from monitor.provider_templates import extract_items
    raw = {"data": [{"ip": "1.2.3.4", "port": 8080}]}
    items = extract_items(raw, {"items_path": "data"})
    assert len(items) == 1
    assert items[0]["ip"] == "1.2.3.4"

def test_normalize_item_geondoe_style():
    from monitor.provider_templates import normalize_item
    item = {
        "ip": "8.8.8.8",
        "port": 3128,
        "protocols": ["http", "socks5"],
        "country": "US",
        "username": "u1",
        "password": "p1",
    }
    result = normalize_item(item, {
        "field_mapping": {
            "host": ["ip", "host"],
            "port": ["port"],
            "protocol": ["protocols[0]", "protocol"],
            "username": ["username"],
            "password": ["password"],
            "country_code": ["country"],
        },
        "protocol_order": ["http", "https", "socks5"],
    })
    assert result is not None
    assert result.host == "8.8.8.8"
    assert result.port == 3128
    assert result.protocol == "http"  # 取 protocol_order 第一位

def test_normalize_item_drops_invalid_host():
    from monitor.provider_templates import normalize_item
    item = {"ip": "127.0.0.1", "port": 8080}
    result = normalize_item(item, {
        "field_mapping": {"host": ["ip"], "port": ["port"]}
    })
    assert result is None  # 私网地址应被过滤
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_proxy_templates.py -v -x`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `monitor/provider_templates.py`**

核心类和接口：

```python
class TemplateFetcher:
    """模板型 provider API 执行器"""
    def __init__(self, config: dict, auth_secret: str = None):
        self.config = config
        self.auth_secret = auth_secret

    def build_request(self, page: int = 1, **overrides) -> dict:
        """构造 HTTP 请求规格"""
        ...

    def fetch(self, request_spec: dict) -> dict:
        """执行 HTTP 请求。默认不跟随重定向；如需跟随，只允许同源 https 或 allowlist。"""
        import httpx
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            resp = client.request(**request_spec)
            resp.raise_for_status()
            return resp.json()

    def extract_items(self, raw: dict) -> list[dict]:
        """按 items_path 提取代理列表"""
        ...

    def next_page(self, raw: dict, current_page: int) -> int | None:
        """判断是否有下一页，返回下一页页码或 None"""
        ...

def normalize_item(item: dict, field_mapping: dict, protocol_order: list[str] = None) -> CanonicalProxyCandidate | None:
    """将单个原始代理项归一为 CanonicalProxyCandidate"""
    ...

def fetch_provider_candidates(provider: dict, scenario: dict) -> list[CanonicalProxyCandidate]:
    """完整链路：fetch → extract → normalize → 安全过滤"""
    ...
```

具体实现要点：

- `build_request`：根据 `method`、`auth`、`query_defaults`、`pagination` 构建 httpx 请求参数
- `extract_items`：支持 JSONPath 风格的 `items_path`（如 `data.proxies`）
- `normalize_item`：按 field_mapping 提取字段 → 协议归一化 → 安全过滤（私网地址等）→ 生成 `CanonicalProxyCandidate`
- `fetch_provider_candidates`：完整流程，控制分页深度（`max_pages`），每条做 normalize，返回 list

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_proxy_templates.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add monitor/provider_templates.py tests/test_proxy_templates.py
git commit -m "feat(monitor): add template-based provider API fetcher"
```

---

### Task 5: 候选池 + 热缓存

**Files:**
- Create: `monitor/proxy_candidate_pool.py`
- Create: `tests/test_proxy_candidate_pool.py`

- [ ] **Step 1: 写失败的测试**

```python
def test_pool_save_and_retrieve():
    from monitor.proxy_candidate_pool import ProxyCandidatePool
    pool = ProxyCandidatePool()
    cand = CanonicalProxyCandidate(candidate_key="k001", provider_id=1,
                                   provider_name="p1", protocol="http",
                                   host="1.2.3.4", port=80,
                                   masked_proxy_endpoint="http://***:****@1.2.3.4:80")
    pool.save_provider_candidates(1, [cand])
    retrieved = pool.get_candidates_for_scenario(1, is_auto=False, cookies=False)
    assert len(retrieved) == 1
    assert retrieved[0].host == "1.2.3.4"

def test_pool_deduplication():
    """同一 candidate_key 不应重复写入"""
    ...

def test_pool_ttl_expiry(self):
    """过期候选不应出现在热缓存中"""
    ...

def test_memory_cache_key(self):
    """不同场景应生成不同 cache key"""
    pool = ProxyCandidatePool()
    key1 = pool._cache_key(1, False, False)
    key2 = pool._cache_key(1, True, False)
    assert key1 != key2
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_proxy_candidate_pool.py -v -x`
Expected: FAIL

- [ ] **Step 3: 实现 `monitor/proxy_candidate_pool.py`**

核心接口：

```python
class ProxyCandidatePool:
    """SQLite 持久候选池 + 内存热缓存"""
    def __init__(self, db_module=None):
        import monitor.db as _db
        self._db = db_module or _db
        self._cache = {}
        self._lock = threading.RLock()
        self._default_cache_ttl_seconds = 45

    def get_candidates_for_scenario(
        self,
        provider_id: int,
        is_auto_download: bool,
        cookies_present: bool,
        country_codes: list[str] = None,
        protocol_order: list[str] = None,
        max_count: int = 5,
    ) -> list[CanonicalProxyCandidate]:
        """从缓存/池中获取满足场景约束的候选，按 score 排序"""

    def save_provider_candidates(
        self,
        provider_id: int,
        candidates: list[CanonicalProxyCandidate],
        ttl_seconds: int = None,
    ) -> int:
        """批量写入/更新候选，返回写入数量"""

    def refresh_provider(
        self,
        provider: dict,
        scenario: dict,
    ) -> list[CanonicalProxyCandidate]:
        """触发 provider 拉取 → 标准化 → 入池 → 更新缓存"""

    def invalidate_provider_cache(self, provider_id: int) -> None:
        """provider 配置更新、refresh 成功、cooldown 变化时清理所有场景缓存"""

    def _load_from_db(self, provider_id, valid_only=True) -> list[dict]:
        ...

    def _load_from_cache(self, provider_id, scenario) -> list[CanonicalProxyCandidate] | None:
        ...

    def _save_to_cache(self, provider_id, scenario, candidates):
        ...

    def _cache_key(self, provider_id, is_auto, cookies, country_codes=None, protocol_order=None) -> str:
        import hashlib, json
        key = json.dumps({
            "provider_id": provider_id,
            "is_auto": is_auto,
            "cookies": cookies,
            "country_pref": country_codes or [],
            "protocol_pref": protocol_order or [],
        }, sort_keys=True)
        return hashlib.md5(key.encode()).hexdigest()
```

要求：

- 每个 cache entry 必须带 `cache_expires_at`
- cache TTL 默认 45 秒，且不得超过 entry 内最短 candidate TTL
- 命中缓存前必须检查 candidate 是否已过期
- 手动 refresh 与后台 refresh 使用同一把 provider 级锁，避免并发写入 SQLite

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_proxy_candidate_pool.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add monitor/proxy_candidate_pool.py tests/test_proxy_candidate_pool.py
git commit -m "feat(monitor): add proxy candidate pool with SQLite persistence and memory cache"
```

---

### Task 6: Selector — 场景过滤 + 评分 + topN

**Files:**
- Create: `monitor/proxy_selector.py`
- Create: `tests/test_proxy_selector.py`

- [ ] **Step 1: 写失败的测试**

```python
def test_selector_filters_cookie_unsupported():
    pool = ProxyCandidatePool()
    c1 = CanonicalProxyCandidate(candidate_key="k1", provider_id=1, provider_name="p1",
                                 protocol="http", host="1.2.3.4", port=80,
                                 masked_proxy_endpoint="http://***:****@1.2.3.4:80",
                                 supports_cookies=False)
    pool.save_provider_candidates(1, [c1])
    selector = ProxySelector(pool)
    result = selector.select(provider_id=1, is_auto_download=False, cookies_present=True, max_count=3)
    assert len(result) == 0  # 不支持 cookies 的候选应被过滤

def test_selector_respects_free_proxy_disallow():
    selector = ProxySelector(pool)
    result = selector.select(provider_id=1, is_auto_download=True, cookies_present=False,
                            allow_free=False, max_count=3)
    # ...

def test_selector_score_ordering(self):
    """高分候选应排在前面"""
    ...

def test_selector_top_n(self):
    """返回数量不超过 max_count"""
    ...
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_proxy_selector.py -v -x`
Expected: FAIL

- [ ] **Step 3: 实现 `monitor/proxy_selector.py`**

```python
class ProxySelector:
    """按场景从候选池选路"""
    def __init__(self, candidate_pool: ProxyCandidatePool):
        self._pool = candidate_pool

    def select(
        self,
        provider_id: int,
        is_auto_download: bool,
        cookies_present: bool,
        country_codes: list[str] = None,
        protocol_order: list[str] = None,
        allow_free: bool = True,
        risk_threshold: str = "high",  # Cookie 场景下不允许 high
        max_count: int = 5,
        billing_tier: str = None,  # 来自 provider 元数据
    ) -> list[CanonicalProxyCandidate]:
        # 1. 从池获取候选
        # 2. 硬过滤：expired / cookies constraint / auto constraint / free constraint / risk constraint
        # 3. 评分排序
        # 4. 对 top1/top2 同步执行 Level2（自动下载 / Cookie / 历史质量不足场景）
        # 5. 返回 topN
        ...

    def _filter_hard(self, candidates: list, ...) -> list:
        """硬过滤"""
        ...

    def _score(self, cand: CanonicalProxyCandidate, country_codes=None, protocol_order=None) -> float:
        """统一评分（第一版固定权重）"""
        protocol_bonus = 0
        if protocol_order:
            ranking = {name: idx for idx, name in enumerate(protocol_order)}
            protocol_bonus = {0: 6, 1: 3}.get(ranking.get(cand.protocol, 99), 0)
        country_bonus = 5 if country_codes and cand.country_code in country_codes else 0
        skipped_penalty = -8 if cand.last_probe_status == "level2_skipped" else 0
        latency_penalty = min(15, (cand.latency_ms or 0) / 200)
        return (
            cand.score
            + (10 if cand.last_probe_status == "healthy" else -5)
            - min(20, cand.consecutive_failures * 4)
            - latency_penalty
            - (10 if cand.risk_level == "high" else 0)
            + protocol_bonus
            + country_bonus
            + skipped_penalty
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_proxy_selector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add monitor/proxy_selector.py tests/test_proxy_selector.py
git commit -m "feat(monitor): add proxy selector with scenario filtering and scoring"
```

---

### Task 7: 集成 list_api 到 Router

**Files:**
- Modify: `monitor/proxy_router.py`（改造 `_try_system_proxy` 和 `_resolve_list_api_with_candidates`）
- Modify: `tests/test_proxy_router.py`（新增 list_api 集成测试）

- [ ] **Step 1: 写失败的测试**

```python
def test_list_api_returns_proxy_pool(self):
    """list_api provider 应返回 proxy_pool 而非单个 proxy"""
    import monitor.proxy_router as pr
    provider = {
        "id": 10, "name": "ListAPI Provider", "enabled": 1,
        "adapter_type": "list_api", "billing_tier": "paid",
        "config_json": {"mode": "template", "base_url": "https://api.test.com"},
        "supports_cookies": True, "supports_auto_download": True,
        "supports_sticky_session": False, "risk_level": "low",
        "last_health_status": "healthy", "cooldown_until": None,
    }
    # Mock pool to return candidates
    with mock.patch('monitor.proxy_router._get_enabled_providers', return_value=[provider]):
        with mock.patch('monitor.proxy_router._select_candidates_for_provider') as mock_sel:
            c1 = pr.CanonicalProxyCandidate(
                candidate_key="k1", provider_id=10, provider_name="ListAPI Provider",
                protocol="http", host="1.2.3.4", port=8080, proxy_url="http://1.2.3.4:8080",
            )
            mock_sel.return_value = [c1]
            account = {"id": 1, "download_proxy_mode": "auto", "proxy_enabled": 0, "proxy_pool_id": None}
            with mock.patch('monitor.proxy_router._get_global_config',
                           return_value=self._make_config()):
                result = pr.resolve_proxy_download(account, is_auto_download=False, cookies_present=False)
    assert result.resolved_proxy_source == "system_paid"
    assert result.proxy_pool is not None
    assert len(result.proxy_pool) == 1
    assert result.proxy == None  # proxy_pool 优先级高于 proxy
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_proxy_router.py -v -k list_api`
Expected: FAIL

- [ ] **Step 3: 实现集成**

改造 `proxy_router.py`：

```python
# 新增顶层调用
def _select_candidates_for_provider(provider: dict, scenario: dict) -> list[CanonicalProxyCandidate]:
    """委托 selector 从候选池获取候选"""
    from monitor.proxy_candidate_pool import ProxyCandidatePool
    from monitor.proxy_selector import ProxySelector
    pool = ProxyCandidatePool()
    sel = ProxySelector(pool)
    return sel.select(
        provider_id=provider["id"],
        is_auto_download=scenario["is_auto_download"],
        cookies_present=scenario["cookies_present"],
        country_codes=scenario.get("country_codes"),
        protocol_order=scenario.get("protocol_order"),
        allow_free=scenario.get("allow_free", True),
        billing_tier=provider.get("billing_tier"),
        max_count=scenario.get("max_count", 5),
    )

def _resolve_list_api_with_candidates(provider: dict, scenario: dict) -> list[CanonicalProxyCandidate]:
    """Phase2 实现：从池/缓存/外部获取候选"""
    candidates = _select_candidates_for_provider(provider, scenario)
    # 从 CanonicalProxyCandidate 转回 ProxyRouteResult 字段
    return candidates
```

改造 `_try_system_proxy`：在遍历 candidates 阶段，如果 adapter 是 `list_api`，则：

```python
if cand.adapter_type in ("public_feed", "list_api"):
    # 获取候选池
    candidates = _select_candidates_for_provider({...raw_provider...}, scenario)
    if not candidates:
        warnings.append(f"提供方 {cand.name} 候选池为空，跳过")
        continue
    # 生成 proxy_pool
    proxy_urls = [c.to_proxy_url() for c in candidates]
    return ProxyRouteResult(
        resolved_mode="system_" + cand.billing_tier,
        proxy=None,
        proxy_pool=proxy_urls,
        provider_name=cand.name,
        provider_tier=cand.billing_tier,
        resolved_proxy_source="system_" + cand.billing_tier,
        reason=f"命中系统{cand.billing_tier}动态代理提供方 {cand.name}（list_api，{len(candidates)}个候选）",
        warnings=result_warnings,
        fallback_depth=1,
        masked_proxy_endpoint=f"{candidates[0].to_proxy_url(mask=True)} (+{len(candidates)-1})",
        session_mode="rotating",
    )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_proxy_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add monitor/proxy_router.py tests/test_proxy_router.py
git commit -m "feat(proxy_router): integrate list_api proxy_pool into routing"
```

---

## Phase 3：质量与观测层

**目标：** 实现分层验证链路、provider/candidate 双层熔断、候选预览与手动刷新 API。

---

### Task 8: 分层验证器

**Files:**
- Create: `monitor/proxy_validator.py`
- Create: `tests/test_proxy_validator.py`

**说明：** `validate_level2()` 的默认执行语义为：selector 在自动下载 / Cookie / 历史质量不足场景下对 top1/top2 同步执行；其余候选允许后台预热。若因预算或超时跳过，必须标记 `level2_skipped` 并降权。

- [ ] **Step 1: 写失败的测试**

```python
def test_level0_rejects_private_ip():
    from monitor.proxy_validator import ProxyValidator
    validator = ProxyValidator()
    result = validator.validate_level0(host="192.168.1.1", port=8080, protocol="http")
    assert result.rejected
    assert "私网" in result.reason

def test_level0_accepts_public_ip():
    result = ProxyValidator().validate_level0(host="8.8.8.8", port=8080, protocol="http")
    assert not result.rejected

def test_level1_tcp_probe_success(self, httpx_mock):
    httpx_mock.add_response("GET", "http://probe.example.com/ok", status_code=200)
    result = ProxyValidator().validate_level1("http", "8.8.8.8", 8080, timeout=5)
    assert result.status == "healthy"
    assert result.latency_ms > 0
```

- [ ] **Step 2-5: 实现验证链路**

Level 0（结构 + 安全）：
```python
@dataclass
class ProbeResult:
    status: str  # unknown | healthy | degraded | down | auth_error
    latency_ms: int | None = None
    error_message: str | None = None
    rejected: bool = False
    reason: str | None = None

class ProxyValidator:
    def validate_level0(self, host, port, protocol, **fields) -> ProbeResult:
        """结构合法性 + 私网/非法端口/畸形值"""
        ...

    async def validate_level1(self, protocol, host, port, timeout=8) -> ProbeResult:
        """轻量 TCP/SOCKS 握手探测"""
        ...

    async def validate_level2(self, protocol, host, port, target="https://www.youtube.com",
                             timeout=15) -> ProbeResult:
        """场景化目标站验证（仅关键场景触发）"""
        ...
```

- [ ] **Step 6: 运行测试验证通过**

Run: `python -m pytest tests/test_proxy_validator.py -v`

- [ ] **Step 7: Commit**

```bash
git add monitor/proxy_validator.py tests/test_proxy_validator.py
git commit -m "feat(monitor): add layered proxy validator (L0/L1/L2)"
```

---

### Task 9: Provider 候选预览 + 手动刷新 API

**Files:**
- Modify: `monitor_server.py`
- Modify: `monitor/scheduler.py`
- Create: `tests/test_list_api_routing.py`

**说明：** 手动 refresh 与后台 refresh 必须共享同一 refresh service，并对同一 provider 使用单飞锁；后台 refresh 由现有 APScheduler 注册，不新增第二套 scheduler。

- [ ] **Step 1: 写失败的测试**

```python
def test_candidates_preview_endpoint(self):
    # GET /api/dynamic-providers/{id}/candidates/preview
    ...

def test_manual_refresh_endpoint(self):
    # POST /api/dynamic-providers/{id}/refresh
    ...
```

- [ ] **Step 2-4: 实现 API 扩展**

在 `monitor_server.py` 中新增：

```python
elif path.startswith("/api/dynamic-providers/") and "/candidates/preview" in path:
    # GET /api/dynamic-providers/{id}/candidates/preview
    self._api_dynamic_provider_candidates_preview(provider_id)

elif match_provider_refresh(path):
    # POST /api/dynamic-providers/{id}/refresh
    self._api_dynamic_provider_refresh(provider_id)
```

```python
def _api_dynamic_provider_candidates_preview(self, provider_id):
    from monitor.proxy_candidate_pool import ProxyCandidatePool
    pool = ProxyCandidatePool()
    # 从 DB 读取最新候选（掩码后）
    # 返回数量、质量分布、最近探测状态
    ...

def _api_dynamic_provider_refresh(self, provider_id):
    # 触发 provider 完整拉取链路
    # 同步执行，返回结果
    ...
```

- [ ] **Step 5: 运行测试验证通过**

- [ ] **Step 6: Commit**

---

## Phase 4：专属 Adapter 扩展（按需）

**目标：** 支持无法用模板覆盖的复杂 provider。

---

### Task 10: Geonode 专属 Adapter（示例）

**Files:**
- Create: `monitor/provider_adapters/geonode_adapter.py`
- Modify: `monitor/provider_templates.py`（注册适配器发现机制）

- [ ] **Step 1: 写失败的测试**

```python
def test_geonode_adapter_extracts_session(self):
    from monitor.provider_adapters.geonode_adapter import GeonodeAdapter
    adapter = GeonodeAdapter({"base_url": "https://proxylist.geonode.com", "auth_secret": "..."})
    raw = adapter.fetch_page(1)
    items = adapter.extract_items(raw)
    assert len(items) > 0
    assert "ip" in items[0]
```

- [ ] **Step 2-4: 实现**

```python
# monitor/provider_adapters/__init__.py
ADAPTER_REGISTRY = {}

def register_adapter(name, cls):
    ADAPTER_REGISTRY[name] = cls

def get_adapter(name: str, config: dict):
    cls = ADAPTER_REGISTRY.get(name)
    return cls(config) if cls else None

# monitor/provider_adapters/geonode_adapter.py
class GeonodeAdapter:
    """Geonode 专属 adapter（处理其特定的分页和字段）"""
    def fetch_page(self, page: int) -> dict:
        ...
    def extract_items(self, raw: dict) -> list[dict]:
        # Geonode 返回结构：{"data": [{"ip": ..., "port": ..., "sessionId": ...}]}
        ...
```

- [ ] **Step 5: Commit**

---

### Task 11: 注册 provider refresh / cleanup / reprobe 周期任务

**Files:**
- Modify: `monitor/scheduler.py`
- Test: `tests/test_list_api_routing.py`

- [ ] **Step 1: 写失败的测试**

```python
def test_scheduler_registers_provider_refresh_jobs():
    ...
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_list_api_routing.py -v -k scheduler`
Expected: FAIL

- [ ] **Step 3: 在现有 APScheduler 中注册周期任务**

要求：
- 使用现有 scheduler 实例
- 按 provider `refresh_interval_seconds` 注册 refresh job
- 注册过期候选 cleanup job
- 注册高优先候选 reprobe job
- 所有 job 共享 provider 级单飞锁，避免手动 refresh 与后台 refresh 并发写入

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_list_api_routing.py -v -k scheduler`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add monitor/scheduler.py tests/test_list_api_routing.py
git commit -m "feat(monitor): register list_api refresh jobs in existing scheduler"
```

---

## 验证总检查清单

每期完成后必须执行：

1. `python -m pytest tests/test_proxy_candidates.py -v` — PASS
2. `python -m pytest tests/test_proxy_templates.py -v` — PASS
3. `python -m pytest tests/test_proxy_candidate_pool.py -v` — PASS
4. `python -m pytest tests/test_proxy_selector.py -v` — PASS
5. `python -m pytest tests/test_proxy_validator.py -v` — PASS
6. `python -m pytest tests/test_proxy_router.py -v` — PASS（全部，回归）
7. `python -m pytest tests/test_dynamic_proxy_config.py -v` — PASS（回归）
8. `python -m pytest tests/test_batch_download_api.py -v` — PASS（回归）
9. 手动：配置 Geonode 模板 → refresh → routing preview → 实际下载 → 全链路通

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 外部 API 不稳定影响下载 | 两层缓存兜底；TTL 保护；candidate 级失败不影响 provider 级 |
| 候选池太大占 DB 空间 | 定期清理过期/低分候选；TTL 控制在 5~15 分钟 |
| Secret 明文落盘 | 候选密码加密存储；日志/UI 只输出掩码 |
| 破坏现有路由 | 每期有独立回归测试；router 不理解 provider 细节 |
| 分页遍历耗尽 provider 配额 | `max_pages` 限制；`fetch_limit` 限制 |
