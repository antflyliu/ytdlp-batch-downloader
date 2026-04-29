# list_api 实现计划

> 文档版本：v1
> 日期：2026-04-07
> 状态：实施指导
> 依据：docs/system-dynamic-proxy-list-api-unified-ingestion-design.md
> 范围：从设计文档到可执行代码的完整拆解，含里程碑、文件清单、风险与验证步骤

---

## 0. 当前代码状态（实施起点）

| 模块 | 当前状态 | 与设计的差距 |
|---|---|---|
| `monitor/proxy_router.py` | `_resolve_list_api()` 返回 `[]`；router 已支持 `proxy` 和 `proxy_pool` 双输出 | 需要新增候选池消费逻辑替代空列表 |
| `monitor/db.py` | `dynamic_proxy_providers` 表已存在；`_encrypt_config_secrets` 已实现 | 需要新增 `dynamic_proxy_candidates` 表及 CRUD |
| `monitor/schema.sql` | `dynamic_proxy_providers` 和 `download_decision_logs` 已定义 | 需要新增 `dynamic_proxy_candidates` 表 |
| `monitor/provider_health.py` | `list_api` 分支返回 `healthy`，无实际探测 | 需要重构为 source-level freshness 报告 |
| `tests/test_proxy_router.py` | 13 项测试覆盖核心路由分支 | 需要新增 list_api 候选路由测试 |
| `tests/test_dynamic_proxy_config.py` | 20 项测试覆盖配置/CRUD/加密/日志 | 需要新增候选池 CRUD/加密/模板测试 |

**结论：一切从新增模块和数据库表开始，不改动已有稳定模块。**

---

## 1. 阶段划分

总原则：每阶段可独立测试、可回滚、不破坏已有功能。

```
Phase A  ─── 基础设施层 ───────────────────────────
Phase B  ─── 候选池 + 路由集成 ───────────────────
Phase C  ─── 质量层 + API 增强 ────────────────────
Phase D  ─── 复杂 provider 扩展（可选）────────────
```

---

## 2. Phase A — 基础设施层

### 2.1 目标

建立 `CanonicalProxyCandidate` 模型、`dynamic_proxy_candidates` 表和基础 CRUD，使 router 有候选池可读。

### 2.2 新增文件

#### 2.2.1 `monitor/proxy_candidate.py`

**职责**：定义 `CanonicalProxyCandidate` dataclass 及相关类型枚举。

```python
# 核心 dataclass
@dataclass
class CanonicalProxyCandidate:
    candidate_key: str          # sha256(provider_id + protocol + host + port + username)
    provider_id: int
    provider_name: str
    adapter_type: str           # 'list_api' | 'public_feed'
    protocol: str               # 'http' | 'https' | 'socks5' | 'socks4'
    host: str
    port: int
    username: str | None
    password: str | None        # 运行时解密，DB 存储加密
    proxy_url: str               # 标准化后的完整 URL（仅内存/内部传递，不写明文）
    country_code: str | None
    anonymity: str              # 'elite' | 'anonymous' | 'transparent'
    risk_level: str             # 'low' | 'medium' | 'high'
    supports_https: bool
    supports_cookies: bool
    supports_auto_download: bool
    supports_sticky_session: bool
    latency_ms: int | None
    last_probe_status: str      # 'unknown' | 'healthy' | 'degraded' | 'down'
    last_probe_at: str | None
    success_count: int
    failure_count: int
    consecutive_failures: int
    score: float
    ttl_expires_at: str | None
    last_seen_at: str
```

**枚举**（按 Python 标准写法）：
- `ProxyProtocol = Literal['http', 'https', 'socks5', 'socks4']`
- `AnonymityLevel = Literal['elite', 'anonymous', 'transparent']`
- `RiskLevel = Literal['low', 'medium', 'high']`
- `ProbeStatus = Literal['unknown', 'healthy', 'degraded', 'down']`

**关键方法**：
- `make_candidate_key(provider_id, protocol, host, port, username) -> str`：生成 sha256 唯一标识
- `build_proxy_url(protocol, host, port, username, password) -> str`：标准化 URL 构建，**永远不信任外部传入的原始 URL 字符串**
- `to_route_result(candidates: list[CanonicalProxyCandidate]) -> tuple[str | None, list[str]]`：将候选列表转换为 router 可消费的 `(single_proxy, proxy_pool)` 格式

**禁止**：
- 禁止在此模块直接调用外部 HTTP API
- 禁止在日志/返回值中暴露明文密码

#### 2.2.2 `monitor/schema.sql` — 新增表

在 `dynamic_proxy_providers` 索引块之后新增：

```sql
-- 动态代理候选池表（高频变更，与低频 provider 配置分离）
CREATE TABLE IF NOT EXISTS dynamic_proxy_candidates (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_key            TEXT    NOT NULL UNIQUE,
    provider_id              INTEGER NOT NULL,
    protocol                 TEXT    NOT NULL,
    host                     TEXT    NOT NULL,
    port                     INTEGER NOT NULL,
    username                 TEXT,
    password                 TEXT,
    proxy_url                TEXT    NOT NULL,
    country_code             TEXT,
    anonymity                TEXT    NOT NULL DEFAULT 'anonymous',
    risk_level               TEXT    NOT NULL DEFAULT 'medium',
    supports_https           INTEGER NOT NULL DEFAULT 1,
    supports_cookies         INTEGER NOT NULL DEFAULT 0,
    supports_auto_download   INTEGER NOT NULL DEFAULT 1,
    supports_sticky_session  INTEGER NOT NULL DEFAULT 0,
    latency_ms               INTEGER,
    last_probe_status        TEXT    NOT NULL DEFAULT 'unknown',
    last_probe_at            TEXT,
    score                    REAL    NOT NULL DEFAULT 0,
    success_count            INTEGER NOT NULL DEFAULT 0,
    failure_count            INTEGER NOT NULL DEFAULT 0,
    consecutive_failures     INTEGER NOT NULL DEFAULT 0,
    last_success_at          TEXT,
    last_failure_at          TEXT,
    last_error_message       TEXT,
    ttl_expires_at           TEXT,
    last_seen_at             TEXT    NOT NULL,
    created_at               TEXT    NOT NULL,
    updated_at               TEXT    NOT NULL,
    FOREIGN KEY(provider_id)  REFERENCES dynamic_proxy_providers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_dpc_provider_ttl     ON dynamic_proxy_candidates(provider_id, ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_dpc_provider_score    ON dynamic_proxy_candidates(provider_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_dpc_probe_status     ON dynamic_proxy_candidates(last_probe_status, ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_dpc_country_protocol ON dynamic_proxy_candidates(country_code, protocol);
CREATE INDEX IF NOT EXISTS idx_dpc_key              ON dynamic_proxy_candidates(candidate_key);
```

#### 2.2.3 `monitor/db.py` — 新增 CRUD

在 `dynamic_proxy_providers CRUD` 块之后新增：

```python
# ── dynamic_proxy_candidates CRUD ──────────────────────────────

def list_candidates(
    provider_id: int | None = None,
    is_auto_download: bool | None = None,
    cookies_present: bool | None = None,
    country_codes: list[str] | None = None,
    min_score: float = 0,
    limit: int = 100,
) -> list[dict]:
    """
    查询候选池，支持场景化筛选。

    筛选顺序：
    1. provider_id 过滤
    2. ttl 未过期
    3. last_probe_status 非 'down'
    4. 场景能力过滤（auto_download / cookies）
    5. 国家过滤
    6. 最低评分过滤
    7. 按 score 倒序取 top N
    """

def upsert_candidate(candidate: CanonicalProxyCandidate) -> int:
    """插入或更新单个候选（基于 candidate_key 做 UPSERT）。"""

def bulk_upsert_candidates(candidates: list[CanonicalProxyCandidate]) -> int:
    """批量 UPSERT，返回实际写入数量。"""

def update_candidate_probe_result(candidate_key: str, probe_result: ProbeResult) -> None:
    """回写探测结果到候选，更新 score、failure_count、last_probe_* 等字段。"""

def record_candidate_download_result(candidate_key: str, success: bool, error_message: str | None = None) -> None:
    """
    记录候选在下载阶段的使用结果。
    success=True → success_count++，consecutive_failures=0，score 上调
    success=False → failure_count++，consecutive_failures++，score 下降
    """

def delete_expired_candidates(provider_id: int | None = None) -> int:
    """删除 ttl_expires_at 早于当前的候选，返回删除数量。"""

def delete_candidates_by_provider(provider_id: int) -> int:
    """删除指定 provider 的全部候选（provider 删除时级联调用）。"""

def get_candidate_stats(provider_id: int) -> dict:
    """返回 provider 的候选统计：总数、有效数、各状态分布。"""
```

**关键约束**：
- `bulk_upsert_candidates` 使用 SQLite 的 `INSERT ... ON CONFLICT(candidate_key) DO UPDATE`
- 所有候选的 `password` 字段落库前必须调用 `_encrypt_config_secrets`（复用现有加密机制）
- 读取时 `_decrypt_config_secrets` 解密后仅在内存传递，不进返回值序列化

#### 2.2.4 `monitor/db.py` — schema migration

在 `_migrate_monitor_accounts()` 中新增：

```python
# v8: dynamic_proxy_candidates 表
if "v8_list_api_candidates" not in applied:
    conn.execute("""CREATE TABLE IF NOT EXISTS dynamic_proxy_candidates ( ...")  # 同 schema.sql
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dpc_provider_ttl ...")
    # ... 各索引
    conn.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                 ("v8_list_api_candidates", today))
```

### 2.3 Phase A 里程碑

| 里程碑 | 验收条件 |
|---|---|
| MA-1 | 新表创建成功，migration 幂等 |
| MA-2 | `CanonicalProxyCandidate` dataclass 定义正确，枚举类型完整 |
| MA-3 | CRUD 函数全部通过单元测试（mock DB） |
| MA-4 | 候选密码加密/解密往返测试通过（利用现有 `_encrypt_config_secrets` 回归） |
| MA-5 | 已有 `test_proxy_router.py` 和 `test_dynamic_proxy_config.py` 继续通过（无破坏） |

### 2.4 Phase A 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 候选表写入量大导致 DB 锁竞争 | 中 | 批量 UPSERT，减少事务数；WAL 模式已有 |
| 加密 key 变更导致旧候选密码无法解密 | 低 | Fernet 解密失败时原值返回（现有行为） |
| candidate_key 计算漂移导致重复写入 | 中 | 在 `bulk_upsert_candidates` 前加 sha256 一致性验证单元测试 |

---

## 3. Phase B — 候选池 + 路由集成

### 3.1 目标

实现 list_api fetcher、模板执行器、候选池填充；改造 router 从候选池读取替代空列表；使 preview API 首次能返回真实的 list_api 候选。

### 3.2 新增文件

#### 3.2.1 `monitor/proxy_templates.py`

**职责**：模板型 provider 的请求构建、响应解析、字段归一化。

```python
"""
Provider Fetcher / Template Engine

支持两种接入模式：
- template: 通过 config_json 描述请求/响应规则，无需写代码
- custom: 通过注册 adapter 类处理特殊逻辑
"""

class BaseFetcher(ABC):
    @abstractmethod
    def build_request(self, config: dict) -> FetchRequest:
        """从 config_json 构建 HTTP 请求。"""

    @abstractmethod
    def extract_items(self, response_body: bytes, config: dict) -> list[dict]:
        """从响应 body 提取原始代理条目列表。"""

    @abstractmethod
    def normalize_item(self, item: dict, config: dict) -> CanonicalProxyCandidate | None:
        """将单个原始条目归一化为候选对象。返回 None 表示该条目不合法被过滤。"""

class TemplateFetcher(BaseFetcher):
    """通过 config_json 模板配置驱动的 fetcher。"""

    def __init__(self, config_json: dict):
        self.config = config_json

    def build_request(self) -> FetchRequest:
        # 从 config_json 读取：
        # base_url, list_path, method, auth, query_defaults, pagination
        # 返回 FetchRequest(name, url, method, headers, body, timeout)

    def extract_items(self, body: bytes) -> list[dict]:
        # 按 response.items_path 做 JSON path 提取
        # 返回原始条目列表

    def normalize_item(self, item: dict) -> CanonicalProxyCandidate | None:
        # 按 field_mapping 将外部字段映射到 canonical 字段
        # 做安全过滤（私网地址、非法端口等）
        # 归一化协议、认证、地址
        # 不合法 → return None

def fetch_provider(provider: dict) -> FetchResult:
    """
    完整执行 provider 拉取 → 归一化 → 候选列表。
    返回 FetchResult(raw_count, valid_count, candidates, errors)。
    """
```

**SSRF 防护**（在 `build_request` 内强制执行）：
```python
def _validate_fetch_url(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"禁止的非 HTTP scheme: {parsed.scheme}")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("禁止请求 localhost")
    # 私网检查：10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
    # ...（复用 proxy_candidate.py 中的安全过滤函数）
    return url
```

**字段归一化规则**（核心逻辑）：
- 协议：映射 `protocol`/`protocols`/`type`/`scheme` 字段；数组取第一个；未知值丢弃
- 地址：`host`/`ip`/`proxy`/`proxy_address` 映射；禁止完整 URL 直接作为 host
- 端口：整数 1~65535；字符串数字转换；禁止负数/超范围
- 认证：从 `username`/`user`/`auth.username` 读取；`password`/`auth.password`
- 国家：从 `country`/`countryCode`/`location.country` 读取；统一转大写 ISO 3166-1 alpha-2
- 匿名度：从 `anonymity`/`type`/`elite` 读取；映射为 `elite`/`anonymous`/`transparent`
- risk_level：默认 `medium`；付费 provider 可默认 `low`

#### 3.2.2 `monitor/proxy_fetcher.py`

**职责**：Provider 生命周期管理、拉取编排、缓存协调。

```python
"""
Provider Fetch Orchestrator

管理 list_api / public_feed provider 的拉取与缓存生命周期。
"""

class ProviderFetcher:
    def __init__(self, db_module=None):
        self._db = db_module or _db

    def refresh_provider(self, provider_id: int) -> FetchResult:
        """
        对单个 provider 执行完整拉取流程：
        1. 加载 provider 配置（db）
        2. 构建 fetcher（template 或 custom）
        3. 发送 HTTP 请求
        4. 提取并归一化条目
        5. 批量写入候选池
        6. 更新 provider health 状态
        7. 返回结果

        异常处理：
        - 网络错误 → 记录 fetch_error，更新 cooldown_until
        - 认证错误 → 标记 auth_error，不写候选
        - 归一化失败 → 记录 normalize_error，继续处理其他条目
        """

    def refresh_all_enabled(self) -> dict[int, FetchResult]:
        """遍历所有启用的 list_api / public_feed provider 并行拉取。"""

    def select_candidates(
        self,
        provider_id: int,
        scenario: RoutingScenario,
        top_n: int,
    ) -> list[CanonicalProxyCandidate]:
        """
        从候选池中为指定场景选取 top-N 候选。
        RoutingScenario 包含：is_auto_download, cookies_present, country_pref, protocol_pref

        执行顺序：
        1. 查内存热缓存（按 scenario key）
        2. 缓存命中 → 返回 top-N
        3. 缓存未命中 → 查 SQLite 候选池
        4. SQLite 有数据 → 重建内存缓存，返回 top-N
        5. SQLite 也空 → 可选触发一次补拉（仅 manual 场景）
        """
```

**内存热缓存设计**：
```python
from functools import lru_cache

@lru_cache(maxsize=128)
def _scenario_cache_key(provider_id: int, is_auto: bool, cookies: bool,
                        country: str | None, protocol: str | None) -> str:
    return f"{provider_id}:{is_auto}:{cookies}:{country or '*'}:{protocol or '*'}"

# 缓存内容：FrozenSet[int]（top-N 候选 ID）
# 失效：provider 配置变更 / 候选池写入 / TTL 到期
```

#### 3.2.3 改造 `monitor/proxy_router.py`

**改造点 1**：修改 `_resolve_list_api()`

```python
# 旧（占位）
def _resolve_list_api(config_json: dict) -> list[str]:
    return []

# 新
def _resolve_list_api(provider: ProxyProviderCandidate, scenario: RoutingScenario) -> list[str]:
    """
    从候选池获取 list_api 候选，转换为 proxy URL 列表。
    不直接调用外部 API，只读缓存/SQLite。
    """
    from monitor.proxy_fetcher import ProviderFetcher
    fetcher = ProviderFetcher()
    candidates = fetcher.select_candidates(
        provider_id=provider.provider_id,
        scenario=scenario,
        top_n=global_config.get("candidate_prefetch_count", 5),
    )
    # 将 CanonicalProxyCandidate 列表转换为 URL 列表
    return [c.proxy_url for c in candidates if c.proxy_url]
```

**改造点 2**：新增 `RoutingScenario` 参数传递

在 `resolve_proxy_download` → `_try_system_proxy` → `_resolve_provider_proxy` 的调用链中，增加 `scenario` 参数（含 `is_auto_download`、`cookies_present`）。

**改造点 3**：修改 `_try_system_proxy` 中 pool adapter 处理逻辑

```python
# 旧逻辑：pool adapter 返回空 → 跳过
is_pool_adapter = cand.adapter_type in ("public_feed", "list_api")
if proxy is None or (is_pool_adapter and not proxy):
    warnings.append(f"提供方 {cand.name} 类型 {cand.adapter_type} 在 v1 中无候选，跳过")
    continue

# 新逻辑：pool adapter 调用候选池选择器
if cand.adapter_type == "list_api":
    urls = _resolve_list_api(cand, scenario)
    if not urls:
        warnings.append(f"提供方 {cand.name} 候选池为空，跳过")
        continue
    # 返回第一个 URL 作为 proxy（下载器会处理 pool 轮换）
    return ProxyRouteResult(
        resolved_mode="list_api_system",
        proxy=urls[0],
        proxy_pool=urls,        # 关键：list_api 返回 proxy_pool
        resolved_proxy_source="system_list_api",
        ...
    )
elif cand.adapter_type == "public_feed":
    # 类似处理
```

**改造点 4**：`ProxyRouteResult` 新增可选字段

```python
@dataclass
class ProxyRouteResult:
    # ... 现有字段 ...
    candidate_source: str | None = None   # 'memory_cache' | 'db_pool' | 'fresh_fetch' | None
    candidate_count: int | None = None    # 本次路由选中的候选数量
```

#### 3.2.4 改造 `monitor/provider_health.py`

**改造点**：`list_api` 分支从"无 gateway 可探针"改为"source-level freshness 报告"

```python
elif adapter == "list_api":
    # 查询候选池 freshness
    from monitor.proxy_fetcher import ProviderFetcher
    fetcher = ProviderFetcher()
    stats = _db.get_candidate_stats(provider_id)  # 新增 db 函数
    if stats['valid_count'] == 0:
        return ProbeResult(status="down", latency_ms=-1,
                          error_message="候选池为空，list_api 未返回可用代理")
    # 有候选但都过期了
    if stats['all_expired']:
        return ProbeResult(status="degraded", latency_ms=0,
                          error_message=f"候选池 {stats['valid_count']} 个但已全部过期")
    return ProbeResult(status="healthy", latency_ms=0,
                      error_message=f"候选池 {stats['valid_count']} 个可用")
```

### 3.3 Phase B 里程碑

| 里程碑 | 验收条件 |
|---|---|
| MB-1 | `TemplateFetcher` 能正确解析模拟响应并归一化为候选 |
| MB-2 | `bulk_upsert_candidates` 能正确做 candidate_key 去重 UPSERT |
| MB-3 | `_resolve_list_api()` 在有候选池时返回 proxy_pool；池空时返回空列表 |
| MB-4 | router 在手动/auto 场景下能正确消费 list_api proxy_pool |
| MB-5 | `check_provider_health` 对 list_api 报告有意义的 freshness 状态 |
| MB-6 | `GET /api/routing-preview` 首次返回真实的 list_api 候选数量（非空） |
| MB-7 | 已有 `test_proxy_router.py` 全部 13 项继续通过 |
| MB-8 | 新增 `test_proxy_candidates.py`（Phase A/BDD 的后续测试）覆盖核心归一化逻辑 |

### 3.4 Phase B 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 候选池为空时 router 跳过 provider 导致无代理可用 | 高 | Phase B 同时实现手动补拉触发（见 3.5） |
| SQLite 大量 UPSERT 导致写入放大 | 中 | Phase B 完成后评估是否需要 WAL batch commit |
| 字段归一化对各家 API 格式适配不足 | 中 | Phase B 先只支持 1 家已知结构（如 Geonode）；后续 Phase D 扩展模板 |
| router 增加 scenario 参数影响面大 | 中 | scenario 参数加默认值保证向后兼容；仅新增 provider 类型使用 |

### 3.5 手动补拉触发（Phase B 内完成）

仅在**手动场景**且**候选池为空/过期**时触发：

```python
# 在 proxy_fetcher.py 的 select_candidates 中
def select_candidates(self, provider_id, scenario, top_n):
    # ... 缓存/SQLite 查询逻辑 ...
    if not candidates and not scenario.is_auto_download:
        # 手动场景 + 池空 → 尝试一次即时补拉
        result = self.refresh_provider(provider_id)
        if result.candidates:
            candidates = self._select_from_result(result, scenario, top_n)
    return candidates
```

**禁止**：auto_download 场景触发同步补拉。

---

## 4. Phase C — 质量层 + API 增强

### 4.1 目标

实现分层验证、评分模型、候选探测回写、provider/candidate 双层熔断、新增 API 接口。

### 4.2 验证层

#### 4.2.1 `monitor/probe_validator.py`

```python
"""
Candidate Probe Validator

三层验证：
- Level 0: 结构与安全校验（在 normalize_item 内已完成）
- Level 1: 轻量连通性探测
- Level 2: 场景化验证（仅高优先级候选触发）
"""

class CandidateProbeValidator:
    def probe_lightweight(self, candidate: CanonicalProxyCandidate, timeout: int = 8) -> ProbeResult:
        """
        Level 1: TCP 握手 + 极轻量 HTTP HEAD。
        目标：判断代理本身是否可达。
        """

    def probe_for_auto_download(self, candidate: CanonicalProxyCandidate) -> ProbeResult:
        """
        Level 2: 访问 YouTube 轻量端点，确认代理在目标场景可用。
        仅对 auto_download 候选的前 candidate_validate_count 个执行。
        """
```

#### 4.2.2 集成到 fetcher

在 `refresh_provider()` 流程中，候选归一化后执行 Level 1 探测（批量，非逐个阻塞），探测结果通过 `update_candidate_probe_result()` 回写。

### 4.3 评分模型

在 `proxy_candidate.py` 中实现：

```python
def calculate_score(candidate: CanonicalProxyCandidate, config: dict) -> float:
    """
    评分公式（0~100）：

    score = 基础分(30)
            + provider优先级分(0~20)     # 从 provider priority 映射
            + 最近成功加分(0~15)          # success_count / (success_count + failure_count) * 15
            - 连续失败惩罚(0~-15)         # min(consecutive_failures * 3, 15)
            - 高延迟惩罚(0~-10)           # latency_ms > 2000ms 时扣分
            - 高风险扣分(0~-10)          # high=-10, medium=-3, low=0
            + 协议偏好加分(0~5)           # 是否匹配 default_proxy_protocol_order
            + 国家命中加分(0~5)           # 是否匹配 default_proxy_country_codes
    """
```

### 4.4 熔断机制

#### 4.4.1 Provider 级熔断

在 `proxy_fetcher.py` 中：

```python
def _handle_fetch_error(self, provider_id: int, error_type: str, error_msg: str):
    """
    连续 fetch_error → 写 cooldown_until
    - 连续 2 次 → cooldown 5min
    - 连续 3 次 → cooldown 15min
    - 连续 5 次 → cooldown 60min
    认证错误 → 直接标记 auth_error，不重试
    """
```

#### 4.4.2 Candidate 级降权

在 `record_candidate_download_result()` 中：
- `consecutive_failures >= 5` → 候选标记为 `last_probe_status='down'` 并从池中软删除（不物理删除，保留历史）
- `consecutive_failures >= 3` → 降权但不删除

### 4.5 新增 API

#### 4.5.1 `POST /api/dynamic-providers/{id}/refresh`

在 `monitor_server.py` 中：

```python
def _api_provider_refresh(self, provider_id):
    fetcher = ProviderFetcher()
    result = fetcher.refresh_provider(provider_id)
    self._send_json({
        "raw_count": result.raw_count,
        "valid_count": result.valid_count,
        "normalize_errors": result.normalize_errors,
        "fetch_error": result.fetch_error,
    })
```

#### 4.5.2 `GET /api/dynamic-providers/{id}/candidates/preview`

```python
def _api_candidates_preview(self, provider_id):
    stats = _db.get_candidate_stats(provider_id)
    candidates = _db.list_candidates(provider_id, limit=10)
    return {
        "provider_id": provider_id,
        "total_count": stats["total_count"],
        "valid_count": stats["valid_count"],
        "expired_count": stats["expired_count"],
        "preview": [_mask_candidate(c) for c in candidates],  # 掩码后输出
    }
```

#### 4.5.3 `POST /api/dynamic-providers/template/validate`

```python
def _api_template_validate(self):
    # 接收 config_json 模板片段
    # 用 TemplateFetcher 发送一次模拟请求（不写库）
    # 返回提取结果预览或错误
```

#### 4.5.4 `GET /api/routing-preview` 增强

已返回字段增加：
```json
{
  "candidate_count": 5,
  "candidate_source": "memory_cache",
  "proxy_pool": ["***:****@1.2.3.4:8080", "***:****@5.6.7.8:9090"]
}
```

### 4.6 Phase C 里程碑

| 里程碑 | 验收条件 |
|---|---|
| MC-1 | Level 1 轻量探测在 8s 内完成，不阻塞拉取主流程 |
| MC-2 | 连续失败候选在 5 次后被降权，查询时自动过滤 |
| MC-3 | Provider 连续拉取失败触发正确的 cooldown 时间递增 |
| MC-4 | `/api/dynamic-providers/{id}/refresh` 返回 raw/valid count |
| MC-5 | `/api/dynamic-providers/{id}/candidates/preview` 返回掩码候选列表 |
| MC-6 | `/api/dynamic-providers/template/validate` 能识别字段映射错误 |
| MC-7 | `/api/routing-preview` 返回 candidate_count 和 proxy_pool（非空） |

---

## 5. Phase D — 复杂 Provider 扩展（可选/后续）

### 5.1 Custom Adapter 注册机制

```python
class ProxyAdapterRegistry:
    _adapters: dict[str, type[BaseFetcher]] = {}

    @classmethod
    def register(cls, name: str, fetcher_cls: type[BaseFetcher]):
        cls._adapters[name] = fetcher_cls

    @classmethod
    def get(cls, name: str) -> BaseFetcher | None:
        return cls._adapters.get(name)
```

config_json 中 `{"mode": "custom", "adapter_name": "geonode_v1"}` 时，从注册表获取 adapter。

### 5.2 Geonode 专属 Adapter

```python
class GeonodeFetcher(BaseFetcher):
    """Geonode API 专属适配器（支持其分页规则、认证方式、字段结构）。"""
```

### 5.3 后台刷新调度

在 `monitor/scheduler.py` 或独立调度入口中注册：

```python
def schedule_provider_refresh():
    """定时刷新所有启用的 list_api / public_feed provider。"""
    # 每 provider.refresh_interval_seconds 执行一次
```

---

## 6. 测试矩阵

### 6.1 Phase A 测试

| 测试项 | 覆盖 |
|---|---|
| `CanonicalProxyCandidate` 各字段赋值 | 边界值、None、默认值 |
| `make_candidate_key` 一致性 | 相同输入→相同 key，不同输入→不同 key |
| `build_proxy_url` 格式正确性 | http/https/socks5/socks4 格式验证 |
| `to_route_result` 转换正确性 | 空列表、单元素、多元素 |
| `bulk_upsert_candidates` UPSERT 去重 | 同一 candidate_key 第二次写入 → 更新而非重复 |
| 密码加密/解密往返 | 加密后解密等于原文 |
| migration v8 幂等执行 | 重复执行不报错 |
| 已有测试回归 | `test_proxy_router.py` + `test_dynamic_proxy_config.py` 继续通过 |

### 6.2 Phase B 测试

| 测试项 | 覆盖 |
|---|---|
| 模板字段映射（模拟 Geonode 响应） | 各字段类型/位置映射正确 |
| 协议归一化 | 数组/单值/未知值处理 |
| 地址安全过滤 | 私网/loopback/非法端口 |
| SSRF 防护 | localhost/非 http scheme |
| `_resolve_list_api` 从候选池返回 proxy_pool | mock 候选池 |
| router 消费 list_api proxy_pool | mock fetcher + 真实 router 逻辑 |
| 手动场景触发即时补拉 | 池空 + is_auto=False → refresh 调用 |
| auto 场景禁止同步补拉 | 池空 + is_auto=True → 不调用 refresh |
| 已有路由测试回归 | 13 项全部通过 |

### 6.3 Phase C 测试

| 测试项 | 覆盖 |
|---|---|
| Level 1 探测超时时状态正确 | timeout → down |
| Level 1 认证错误时状态正确 | 407 → auth_error |
| 评分公式各因子 | 模拟各种 candidate 状态验证分数 |
| 连续失败降权 | 5 次 failure → down |
| Provider 级 cooldown 时间递增 | 2/3/5 次错误对应 5/15/60min |
| refresh API 返回结构 | raw_count + valid_count + errors |
| candidates preview API 掩码 | 确认无明文密码输出 |

---

## 7. 回归保护清单

实施任何阶段前，必须确认以下已有行为不受影响：

| 已保护行为 | 验证方式 |
|---|---|
| `account_static` 路由不受影响 | `test_proxy_router.py::test_auto_mode_with_static_proxy` |
| `system_only` 忽略固定代理 | `test_proxy_router.py::test_system_only_mode` |
| `account_only` 无固定代理时失败 | `test_proxy_router.py::test_account_only_mode_no_proxy` |
| `direct_only` 永远直连 | `test_proxy_router.py::test_direct_only_mode` |
| auto download 禁用免费代理 | `test_proxy_router.py::test_auto_download_skips_free_proxy` |
| cookie download 禁用免费代理 | `test_proxy_router.py::test_cookie_download_skips_free_proxy` |
| 已有账户不启用系统回退 | `test_proxy_router.py::test_existing_account_without_switch_does_not_fallback_to_system` |
| Provider cooldown 正确跳过 | `test_proxy_router.py::test_provider_in_cooldown_skipped` |
| 固定代理 CRUD 正常 | `test_dynamic_proxy_config.py` 相关项 |
| 配置加密往返正常 | `test_dynamic_proxy_config.py::test_config_secrets_encrypted_roundtrip` |
| 决策日志写入正常 | `test_dynamic_proxy_config.py::test_download_decision_log` |

---

## 8. 文件变更总览

### 8.1 新增文件

| 文件 | Phase | 说明 |
|---|---|---|
| `monitor/proxy_candidate.py` | A | CanonicalProxyCandidate 模型 + 工具函数 |
| `monitor/proxy_templates.py` | B | 模板执行器 + 字段归一化 + SSRF 防护 |
| `monitor/probe_validator.py` | C | 分层验证器 |
| `tests/test_proxy_candidates.py` | A | Phase A 候选模型单元测试 |
| `tests/test_proxy_templates.py` | B | 模板解析与归一化测试 |

### 8.2 修改文件

| 文件 | Phase | 改动说明 |
|---|---|---|
| `monitor/schema.sql` | A | 新增 `dynamic_proxy_candidates` 表及索引 |
| `monitor/db.py` | A | 新增 v8 migration + 候选池 CRUD |
| `monitor/proxy_router.py` | B | 改造 `_resolve_list_api` + scenario 参数传递 + proxy_pool 输出 |
| `monitor/provider_health.py` | B | `list_api` 改报告候选池 freshness |
| `monitor_server.py` | B/C | 新增 refresh API + candidates preview API + template validate API + routing-preview 增强 |
| `tests/test_proxy_router.py` | B | 新增 list_api 候选路由测试 |
| `tests/test_dynamic_proxy_config.py` | A | 新增候选池 CRUD + 加密往返测试 |

### 8.3 不修改文件（证明无破坏）

- `monitor/dynamic_provider_resolver.py` — thin wrapper，无需改动
- `monitor/scheduler.py` — 已有 no-silent-direct 逻辑，不受影响
- `monitor_web/index.html` — 前端暂不改动，待 Phase B/C API 完成后由专门前端任务处理

---

## 9. 实施顺序建议

```
Week 1
├── Phase A
│   ├── 定义 CanonicalProxyCandidate dataclass
│   ├── schema.sql 新增候选池表
│   ├── db.py 新增 migration + CRUD
│   └── Phase A 单元测试
│
Week 2
├── Phase B
│   ├── proxy_templates.py 模板执行器
│   ├── proxy_fetcher.py 编排器 + 内存缓存
│   ├── proxy_router.py 改造（scenario + proxy_pool）
│   ├── provider_health.py 改造
│   ├── Phase B 单元测试
│   └── 端到端手动验证（创建 list_api provider → refresh → preview）
│
Week 3
├── Phase C
│   ├── probe_validator.py 验证层
│   ├── 评分模型实现
│   ├── 熔断机制
│   ├── 新增 API endpoints
│   └── Phase C 测试
│
Week 4
├── Phase D（可选）
│   ├── Custom adapter 注册机制
│   └── Geonode 专属 adapter
```

---

## 10. 回滚方案

| 阶段 | 回滚方式 |
|---|---|
| Phase A | 删除 migration v8 中的 `dynamic_proxy_candidates` 表创建语句（幂等设计）；已存在的候选数据可保留，不影响 router（因 router 尚未消费） |
| Phase B | `proxy_router.py` 改动加 feature flag `LIST_API_ROUTING_ENABLED`（默认 False）；仅在明确开启时使用新路径；关闭时回退到 Phase A 的空列表行为 |
| Phase C | API endpoints 加版本前缀 `/api/v2/`；Phase B feature flag 关闭时自然降级 |

---

## 11. 验收检查表（实施完成后）

- [ ] Phase A 里程碑全部通过
- [ ] Phase B 里程碑全部通过
- [ ] Phase C 里程碑全部通过
- [ ] 回归测试清单 100% 通过（13 + 20 + 新增项）
- [ ] list_api provider 从创建 → refresh → preview → 实际下载路由 全链路跑通
- [ ] 密码不在日志/UI/API 响应中暴露
- [ ] auto download 不触发同步补拉
- [ ] provider 级和 candidate 级熔断独立工作
- [ ] 文档更新（产品 spec 和架构设计中的 Phase 状态）
