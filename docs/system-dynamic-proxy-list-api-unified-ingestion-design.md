# 系统默认动态代理 `list_api` 多提供方统一接入设计方案

> 文档版本：v1
> 日期：2026-04-07
> 状态：设计已确认，待实现计划
> 范围：为 `list_api` 设计一套兼容多种外部代理 API 的生产级统一接入架构，不直接实现代码

---

## 1. 背景与目标

当前系统已经具备：

- 账户固定代理（`proxy_pool_id + proxy_enabled`）
- 系统级动态代理提供方抽象（`dynamic_proxy_providers`）
- 手动/自动下载统一路由层（`monitor/proxy_router.py`）
- 下载器只接收最终 `proxy` 或 `proxy_pool` 的边界

但 `list_api` 仍处于占位状态：

- `monitor/proxy_router.py` 中 `_resolve_list_api()` 仍返回空列表
- 路由器目前只能稳定处理 `rotating_gateway` / `local_gateway`
- 缺少多 provider 的标准化模型、候选池、验证分层、缓存策略、观测体系

本方案的目标不是适配某一家 API，而是建立一层 **统一接入与标准化平台**，满足以下要求：

1. 支持多种外部代理 API，返回结构可不同
2. 对外统一为同一种候选代理模型
3. 路由层不理解 provider 差异，只理解候选质量和策略
4. 下载器继续只接收最终 `proxy` / `proxy_pool`
5. 支持未来接入 Geonode、Webshare、ProxyScrape、自建 API 等多种来源
6. 在生产环境下具备缓存、评分、验证、熔断、审计与排障能力

---

## 2. 设计结论

本次设计采用以下基线：

- **拉取策略：混合型**
  - 优先读本地候选池/热缓存
  - 候选不足或质量不足时再实时补拉 provider API
- **接入策略：混合型**
  - 大多数 provider 走模板化接入
  - 特殊 provider 支持专属代码适配器
- **存储策略：分层型**
  - SQLite 做持久候选池
  - 内存做热缓存
- **验证策略：分层型**
  - 安全校验 → 轻量探测 → 场景化验证

这是稳定性、扩展性、实现复杂度三者之间最平衡的生产方案。

---

## 3. 为什么不选另外两类极端方案

### 3.1 不选“纯实时拉取”

如果每次下载前都直接访问外部 provider API：

- 延迟不可控
- 外部 API 抖动会直接传导到下载链路
- provider 限流/失败会放大成用户可见故障
- 候选代理没有历史质量沉淀
- 很难做跨下载场景复用

结论：只能作为“补拉机制”，不能作为主路径。

### 3.2 不选“纯本地同步”

如果完全依赖后台定时同步：

- 一旦缓存池过期，下载成功率会下降
- 对更新快、时效强的代理 API 不够友好
- 容易出现“库里还有数据，但真实代理已经失效”的情况

结论：本地池应是主路径，但必须保留运行时补拉能力。

### 3.3 不选“纯配置驱动”或“纯代码适配器”

- 纯配置驱动：扩展快，但遇到特殊认证、分页、嵌套结构、签名请求就会脆弱
- 纯代码适配器：稳定，但每接一家就要写代码，维护成本高

结论：应采用 **模板优先 + 专属适配器兜底**。

---

## 4. 总体架构

建议新增一条独立于路由器本体的统一接入链路：

```text
外部 Provider API
    ↓
Provider Fetcher / Adapter
    ↓
Response Normalizer
    ↓
Canonical Proxy Candidate
    ↓
Security Filter
    ↓
Policy Filter
    ↓
Validator / Probe / Scoring
    ↓
SQLite Candidate Pool
    ↓
In-Memory Hot Cache
    ↓
Scenario-Aware Selector
    ↓
proxy_router
    ↓
Youtube_Downloader.batch_download(proxy/proxy_pool)
```

### 4.1 核心边界

- **provider adapter 层**：负责“怎么请求外部 API、怎么翻页、怎么读字段”
- **normalizer 层**：负责把不同返回格式统一成规范候选对象
- **candidate pool 层**：负责持久化、去重、TTL、评分、最近失败信息
- **selector 层**：负责按当前下载场景挑选可用候选
- **router 层**：负责固定代理 / 动态代理 / 直连之间的路由顺序
- **downloader 层**：保持不变，只消费 `proxy` / `proxy_pool`

### 4.2 设计原则

1. **路由器不懂 provider**
   - 路由器不再感知 Geonode / Webshare 等名字
   - 它只关心：有没有满足场景约束的候选

2. **候选模型是平台唯一真相**
   - 所有 provider 最终都要转成同一种 `CanonicalProxyCandidate`

3. **provider 级失败与 candidate 级失败分离**
   - provider API 拉取失败 ≠ 某个代理节点下载失败
   - 两类错误必须分别计数和熔断

4. **场景感知是选路前置条件**
   - 手动下载、自动下载、带 Cookie、系统严格模式等必须参与候选筛选

---

## 5. Canonical Proxy Candidate 统一模型

这是整个方案最核心的对象。

建议引入统一候选模型（逻辑结构，不要求此刻马上建成 dataclass）：

```json
{
  "candidate_key": "sha256(provider_id + protocol + host + port + username)",
  "provider_id": 12,
  "provider_name": "geonode",
  "provider_adapter": "list_api",
  "source_type": "api_list",
  "provider_reference_id": "geonode:8.8.8.8:8080",
  "protocol": "http",
  "host": "1.2.3.4",
  "port": 8080,
  "username": "user1",
  "password_enc": "enc:...",
  "auth_type": "basic",
  "masked_proxy_endpoint": "http://***:****@1.2.3.4:8080",
  "country_code": "US",
  "region": null,
  "city": null,
  "isp": null,
  "supports_https": true,
  "supports_cookies": false,
  "supports_auto_download": true,
  "supports_sticky_session": false,
  "anonymity": "elite",
  "risk_level": "medium",
  "latency_ms": null,
  "last_probe_status": "unknown",
  "last_probe_at": null,
  "success_count": 0,
  "failure_count": 0,
  "consecutive_failures": 0,
  "score": 0,
  "ttl_expires_at": "2026-04-07T10:00:00+08:00",
  "last_seen_at": "2026-04-07T09:55:00+08:00",
  "proxy_url_runtime": "(selector 中解密后临时构造，不落盘)"
}
```

### 5.1 统一字段分层

建议把字段分成 5 类：

1. **身份字段**
   - `candidate_key`
   - `provider_id`
   - `provider_name`
   - `provider_adapter`

2. **连接字段**
   - `protocol`
   - `host`
   - `port`
   - `username`
   - `password_enc`（持久层加密保存，运行时再解密）
   - `auth_type`
   - `masked_proxy_endpoint`
   - `proxy_url_runtime`（仅 selector / downloader 内存态生成，不落盘）

3. **能力字段**
   - `supports_https`
   - `supports_cookies`
   - `supports_auto_download`
   - `supports_sticky_session`

4. **属性字段**
   - `country_code`
   - `anonymity`
   - `risk_level`
   - `isp`
   - `provider_reference_id`（provider 返回的稳定标识或本地派生的外部引用 ID，绝不保存活对象引用）

5. **运行时质量字段**
   - `latency_ms`
   - `last_probe_status`
   - `success_count`
   - `failure_count`
   - `consecutive_failures`
   - `score`
   - `ttl_expires_at`

### 5.2 为什么必须先统一模型

因为不同 provider 可能分别返回：

- `ip`, `host`, `proxy`, `proxy_address`
- `protocol`, `protocols`, `type`, `scheme`
- `auth.username`, `user`, `username`
- `country`, `countryCode`, `location.country`
- `port` 为数字、字符串、甚至嵌套对象

如果没有 canonical model：

- 路由层会被迫认识 provider 差异
- 测试会分裂成“每家一套逻辑”
- 质量评分无法横向比较

---

## 6. Provider 接入模型

## 6.1 两级接入方式

建议 `list_api` 提供方分为两种接入形态：

### Type A：模板型 Provider

适用于：
- 标准 REST API
- 结构稳定
- 认证简单
- 分页规则清晰

通过 `config_json` 描述：

```json
{
  "mode": "template",
  "base_url": "https://proxylist.example.com",
  "list_path": "/api/proxies",
  "method": "GET",
  "auth": {
    "type": "bearer",
    "token_ref": "enc:..."
  },
  "query_defaults": {
    "limit": 100,
    "page": 1,
    "sort_by": "lastChecked",
    "sort_type": "desc"
  },
  "pagination": {
    "type": "page",
    "page_param": "page",
    "page_size_param": "limit",
    "max_pages": 3,
    "stop_when_empty": true
  },
  "response": {
    "items_path": "data",
    "field_mapping": {
      "host": ["ip", "host"],
      "port": ["port"],
      "protocol": ["protocol", "protocols[0]"],
      "username": ["username", "auth.username"],
      "password": ["password", "auth.password"],
      "country_code": ["country", "countryCode"]
    }
  }
}
```

### Type B：专属适配器 Provider

适用于：
- 复杂认证
- 奇怪分页
- 返回结构不稳定
- 请求需要二次变换或签名
- 字段推导依赖 provider 业务规则

此时 `config_json` 只负责存业务参数，实际解析由 adapter 类处理：

```json
{
  "mode": "custom",
  "adapter_name": "geonode_v1",
  "base_url": "https://proxylist.geonode.com",
  "refresh_defaults": {
    "limit": 200,
    "sort_by": "lastChecked"
  }
}
```

### 6.2 建议的 adapter 接口

统一抽象为：

- `build_request(config, context) -> RequestSpec`
- `fetch(request_spec) -> ProviderRawResponse`
- `extract_items(raw_response, config) -> list[dict]`
- `normalize_item(item, config) -> CanonicalProxyCandidate | None`
- `next_page(raw_response, current_state) -> PageState | None`

这样模板型与专属型都能挂到同一执行器下。

---

## 7. 标准化与字段归一化策略

## 7.1 协议统一

外部 provider 可能给出：

- `http`
- `https`
- `socks5`
- `socks4`
- `protocols: ["http", "https"]`
- `type: "elite"`（没有明确协议）

建议统一协议枚举：

- `http`
- `https`
- `socks5`
- `socks4`

归一规则：

1. 如果是数组，按系统配置中的 `default_proxy_protocol_order` 选最优协议
2. 如果 provider 没给协议但给了端口/常见模式，不做猜测，直接丢弃
3. 任何未知协议都不进入候选池

## 7.2 认证统一

支持：

- 无认证
- Basic 用户名密码
- API 返回中内嵌用户密码
- provider 配置中统一用户名/密码前缀

建议区分：

- **candidate runtime auth**：真正用于拼接 `proxy_url` 的认证信息
- **provider fetch auth**：调用 provider API 本身使用的 token/api_key/bearer

这两类 secret 必须完全分开。

## 7.3 地址统一

统一为：

- `host`
- `port`
- `proxy_url`

规则：

1. `host` 必须是公网 IPv4 / IPv6 / 合法域名
2. 禁止把完整 URL 直接当 host
3. `port` 必须是 1~65535 整数
4. `proxy_url` 只在标准化完成后生成，不能信任外部直接给的整串 URL

---

## 8. 安全过滤层

在候选进入验证前，必须做强制安全过滤。

## 8.1 必须拦截的对象

1. 私网地址
   - `10.0.0.0/8`
   - `172.16.0.0/12`
   - `192.168.0.0/16`
2. loopback
   - `127.0.0.0/8`
   - `::1`
3. link-local / multicast / unspecified
4. 非法端口
5. 空 host / 空 protocol
6. 明显恶意或畸形值
   - `http://http://...`
   - `user:pass@:8080`
   - 超长字段

## 8.2 Secret 处理原则

- provider API token / bearer / auth_secret 必须沿用当前 `config_json` 加密存储模式
- candidate 级别的用户名密码如需持久化，必须以 `password_enc` 形式加密落库；selector 在内存中解密后即时构造 `proxy_url_runtime`
- `dynamic_proxy_candidates` 不持久化含明文认证信息的完整 `proxy_url`
- 如果 provider 返回的每条代理都带独立用户名密码，建议：
  - SQLite 落盘时加密保存
  - 日志永远只存 `masked_proxy_endpoint`
  - UI 永远不回显原始密码

## 8.3 SSRF 与滥用防护

因为 `list_api` 本质上是在“让系统去请求外部 URL”，因此 provider 配置本身要限制：

- 只允许 `http/https`
- 禁止 `file://`, `ftp://`, `gopher://` 等
- 禁止请求 localhost / 私网 API
- 默认 **不跟随重定向**；如确需跟随，必须限定为同源 `https` 或显式 allowlist，并对重定向目标重复执行 SSRF 校验
- 可选：增加允许域名白名单或管理员确认机制

---

## 9. 候选池存储设计

建议新增独立候选池表，而不是把所有节点塞进 `dynamic_proxy_providers.config_json`。

建议新增表：`dynamic_proxy_candidates`

```sql
id INTEGER PK
candidate_key TEXT UNIQUE
provider_id INTEGER NOT NULL
protocol TEXT NOT NULL
host TEXT NOT NULL
port INTEGER NOT NULL
username TEXT
password_enc TEXT
auth_type TEXT
masked_proxy_endpoint TEXT NOT NULL
country_code TEXT
region TEXT
city TEXT
anonymity TEXT
risk_level TEXT NOT NULL DEFAULT 'medium'
supports_https INTEGER NOT NULL DEFAULT 1
supports_cookies INTEGER NOT NULL DEFAULT 0
supports_auto_download INTEGER NOT NULL DEFAULT 1
supports_sticky_session INTEGER NOT NULL DEFAULT 0
latency_ms INTEGER
last_probe_status TEXT
last_probe_at TEXT
score REAL NOT NULL DEFAULT 0
success_count INTEGER NOT NULL DEFAULT 0
failure_count INTEGER NOT NULL DEFAULT 0
consecutive_failures INTEGER NOT NULL DEFAULT 0
last_success_at TEXT
last_failure_at TEXT
last_error_message TEXT
failure_category TEXT
provider_reference_id TEXT
ttl_expires_at TEXT
last_seen_at TEXT NOT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
FOREIGN KEY(provider_id) REFERENCES dynamic_proxy_providers(id) ON DELETE CASCADE
```

索引建议：

- `(provider_id, ttl_expires_at)`
- `(provider_id, score DESC)`
- `(last_probe_status, ttl_expires_at)`
- `(country_code, protocol)`
- `(ttl_expires_at)`（供清理任务高效扫描过期候选）

### 9.1 为什么必须单独建表

因为候选是高频变化对象，而 provider 是低频配置对象。

把两者混在一起会导致：

- 配置和运行时状态耦合
- 更新大 JSON 性能差
- 很难做去重、排序、筛选和失效回收

---

## 10. 缓存设计

采用两层缓存：

## 10.1 SQLite 持久层

作用：
- 系统重启后保留候选质量历史
- 支持 TTL
- 支持失败计数和评分沉淀
- 支持 UI 查看与排障

## 10.2 内存热缓存

建议按 **场景维度** 建 cache key：

```text
(provider_id, is_auto_download, cookies_present, country_pref, protocol_pref)
```

其中：

- `country_pref` 来自全局配置 `default_proxy_country_codes` 与后续可扩展的账户级偏好合并结果；当前版本若账户无独立国家偏好，则仅使用全局配置
- `protocol_pref` 来自全局配置 `default_proxy_protocol_order`

缓存内容：
- 该场景下排序后的 top-N 候选 ID 列表
- 生成时间
- 最后探测时间
- cache entry 自身过期时间 `cache_expires_at`

热缓存要求：

- **每个 cache entry 必须有独立 TTL**，默认建议 30~60 秒，且不得超过命中的最短 candidate TTL
- 若 cache entry 中任一 candidate 已过期，则该 entry 整体失效并回源 SQLite
- provider 配置更新、provider 冷却状态变化、手动 refresh 成功后，必须主动清除此 provider 的全部场景缓存
- 实现必须保证线程安全；推荐使用进程内锁（如 `threading.RLock`）保护缓存读写，避免 APScheduler 线程池与手动刷新同时写入时发生竞态

### 10.3 缓存失效策略

以下任一条件触发失效：

1. provider 配置更新
2. provider 被禁用
3. provider 冷却状态变化
4. 候选 TTL 到期
5. 路由命中后连续失败超阈值
6. 场景策略变更（如 cookies / auto_download 开关变化）

---

## 11. 分层验证策略

## 11.1 Level 0：结构与安全校验

进入候选池前执行：

- 字段完整性
- 协议合法性
- host/port 合法性
- 私网/回环地址拦截
- 凭据长度与格式合法性

不通过直接丢弃。

## 11.2 Level 1：轻量连通性探测

目标：判断“代理本身是否可连”

建议探测：
- 建 TCP / SOCKS / HTTP 代理握手
- 访问极轻量的公共探测地址
- 获取耗时和基础响应状态

结果写入：
- `last_probe_status`
- `latency_ms`
- `last_probe_at`

## 11.3 Level 2：场景化验证

仅在以下情况触发：

- 候选将进入高优先级热集
- 用于自动下载
- 用于 Cookie 下载
- 前几个候选历史质量不足

执行语义必须明确：

- **默认采用同步验证用于 top1/top2 关键候选**：当 selector 准备把候选放入当前场景热集时，对前 1~2 个候选同步执行 Level 2；验证失败则降权或剔除，避免未验证候选直接进入关键下载链路
- **异步预热仅用于补充候选**：对 top3 之后的候选可后台预热，不影响当前请求返回
- 若当前请求因预算或超时限制无法执行 Level 2，同步路径必须显式记录 `level2_skipped`，并降低其默认分值，而不是把它视为等同已验证

建议验证目标：
- 轻量访问与 YouTube 相关的可公开端点
- 确认 HTTPS 隧道质量
- 可选验证“是否容易被截断/重置”

注意：
- 不能把场景化验证做成每次全量执行
- 否则会增加 provider 消耗与外部访问压力

---

## 12. 评分与选择策略

候选选择不能只靠“最新拉到的排前面”，要引入统一评分。

建议 score 由以下组成：

```text
总分 = 基础优先级分
    + provider优先级分
    + 最近成功加分
    - 最近失败扣分
    - 连续失败惩罚
    - 高延迟惩罚
    - 高风险扣分
    + 协议偏好加分
    + 国家命中加分
    + 场景能力匹配加分
```

推荐默认权重（第一版可直接采用）：

- provider 优先级：`max(0, 20 - priority)`
- 最近成功：`+8`
- 最近失败：`-6`
- 连续失败：每次 `-4`，上限 `-20`
- 延迟惩罚：`latency_ms / 200`，上限 `-15`
- 高风险：`-10`（Cookie 场景下通常已被硬过滤）
- 协议偏好：按 `default_proxy_protocol_order` 给 `+6 / +3 / +0`
- 国家命中：`+5`
- `level2_skipped`：`-8`

这些权重的目的不是追求数学最优，而是明确第一版排序倾向，避免不同实现者各自猜测。

### 12.1 场景约束优先于评分

先做硬过滤，再做排序。

硬过滤条件包括：

- `cookies_present=true` 时必须满足 `supports_cookies`
- `is_auto_download=true` 时必须满足 `supports_auto_download`
- 若全局不允许免费代理，则 free 全部过滤
- 若 `risk_level=high` 且当前为 Cookie 场景，则直接过滤

### 12.2 评分的目的

评分不是决定“能不能用”，而是决定“优先用谁”。

---

## 13. 熔断、冷却与失败回写

## 13.1 provider 级冷却

当以下情况发生时，对 provider 整体冷却：

- API 拉取连续失败
- 认证失败
- 返回结构连续异常
- provider 明确限流

这类冷却应写回 `dynamic_proxy_providers.cooldown_until`。

## 13.2 candidate 级降权

当单个代理在下载执行阶段失败时：

- 增加 `failure_count`
- 增加 `consecutive_failures`
- 降低 `score`
- 超阈值后标记短暂不可用

不要把单个 candidate 失败直接等同为 provider 全体失败。

### 13.3 失败分层

建议把失败分成：

- `fetch_error`：provider API 请求阶段失败，包括 DNS/连接超时、TLS 错误、HTTP 4xx/5xx、认证失败、限流、重定向被安全策略拦截
- `normalize_error`：已成功拿到 provider 响应，但 items_path 提取失败、字段缺失、字段类型不合法、协议/host/port 无法归一化
- `probe_error`：候选已成功标准化，但在 Level 1/Level 2 验证阶段失败，如 TCP/SOCKS/HTTP 握手失败、目标站探测失败、响应被截断
- `download_error`：候选通过或跳过验证后，在真实下载阶段由 yt-dlp / requests / aria2c / 代理隧道抛出的失败

建议额外保留 `security_reject` 作为内部统计分类，用于记录私网地址、非法协议、畸形字段等被安全层直接拒绝的项；该分类不计入 provider API 可用性，但计入 provider 数据质量。

---

## 14. 与现有路由器的集成方式

核心要求：**尽量不破坏现有 router 语义。**

## 14.1 当前现状

当前 `monitor/proxy_router.py` 中：

- `_resolve_list_api()` 是占位实现
- `_resolve_provider_proxy()` 只稳定返回单个代理 URL
- `_try_system_proxy()` 目前主要按 provider 选出一个 `proxy`

## 14.2 推荐改造方向

### 第一层：保留 `ProxyRouteResult`

保留现有：
- `proxy`
- `proxy_pool`
- `resolved_proxy_source`
- `provider_name`
- `provider_tier`
- `warnings`

只扩展必要元数据，不改其基本语义。

### 第二层：让 `list_api` 返回 `proxy_pool`

建议语义：

- `rotating_gateway` / `local_gateway` → 优先返回单个 `proxy`
- `list_api` / `public_feed` → 返回排序后的 `proxy_pool`

这样可以最大化复用现有下载器的失败切换能力。

### 14.3 模块布局

建议模块布局如下：

```text
monitor/
  proxy_router.py            # 继续负责 fixed/system/direct 三层路由，不直接理解 provider 差异
  provider_templates.py      # 模板型 provider 的请求构造、响应提取、字段映射
  provider_adapters/         # 专属 adapter 目录（按需）
    __init__.py
    geonode_adapter.py
  proxy_candidate_pool.py    # SQLite 候选池 + 内存热缓存 + TTL + 去重
  proxy_selector.py          # 场景过滤、评分、topN 选择
  proxy_validator.py         # Level 0/1/2 验证
  provider_health.py         # provider 级与 candidate 级健康状态聚合
  db.py                      # provider / candidate 持久化与 secret 加密
  scheduler.py               # 复用现有 APScheduler，新增 provider refresh/cleanup/reprobe 周期任务
```

其中：

- `provider_templates.py` 负责模板逻辑，不直接做路由
- `provider_adapters/` 只承载复杂 provider 的专属解析
- `proxy_candidate_pool.py` 与 `proxy_selector.py` 分离，前者管数据与缓存，后者管策略与排序
- `scheduler.py` 不新增第二套调度器，避免并存 scheduler 带来的状态分裂

### 14.4 与评分、pool fallback 的关系

评分不决定候选是否“允许进入 pool”，而是决定它们在 `proxy_pool` 中的顺序。真正决定“能不能进入 pool”的是硬过滤：

- 场景约束（cookies / auto_download / risk / billing_tier）
- TTL 是否有效
- Level 0/1 校验是否通过
- Level 2 是否通过或是否被允许以 `level2_skipped` 状态低优先进入末位

一旦候选进入 `proxy_pool`，下载器就会按顺序尝试。因此：

- **硬过滤** 决定资格
- **评分** 决定顺序
- **pool exhaustion** 体现低分候选作为后备线路的资格

这三者必须分开看待，避免把评分误解为单纯展示字段。

## 15. 对外 API 设计建议

## 15.1 现有接口保留

保留现有：

- `GET /api/dynamic-providers`
- `POST /api/dynamic-providers`
- `POST /api/dynamic-providers/{id}/update`
- `POST /api/dynamic-providers/{id}/health-check`
- `POST /api/dynamic-providers/{id}/cooldown/clear`
- `GET /api/routing-preview`

## 15.2 建议新增接口

### 1）Provider 候选预览

```text
GET /api/dynamic-providers/{id}/candidates/preview
```

返回：
- 最近拉取到的候选数
- 当前有效候选数
- top N 候选（掩码后）
- 失败分类统计

### 2）手动刷新 provider 候选

```text
POST /api/dynamic-providers/{id}/refresh
```

作用：
- 触发 provider API 拉取
- 标准化
- 轻量探测
- 更新候选池

### 3）Provider 模板校验

```text
POST /api/dynamic-providers/template/validate
```

作用：
- 在保存 provider 配置前，先验证模板能否正确提取字段
- 降低“配置保存成功但运行时报错”的概率

### 4）场景化选路预览增强

扩展 `GET /api/routing-preview` 的返回：

- `candidate_count`
- `candidate_source`（memory/db/fetch）
- `selector_reason`
- `filtered_out_counts`

---

## 16. 后台任务与生命周期

建议新增后台维护任务：

## 16.1 定时 refresh

按 provider 配置周期刷新候选池：

- 对 `list_api` provider 按 `refresh_interval_seconds` 定时拉取
- 刷新后写入 SQLite
- 热门 provider 更新内存热缓存
- 复用现有 `monitor/scheduler.py` 中的 APScheduler，不新增独立 scheduler
- 手动 refresh 与后台 refresh 共享同一 refresh service，并对同一 provider 使用单飞锁（single-flight lock）；若已有 refresh 正在进行，则后续 refresh 直接复用结果或快速返回“处理中”状态，避免并发写 SQLite

## 16.2 定时清理

定期清理：

- 过期候选
- 长期失败候选
- 长期未见候选
- 低分且无命中记录候选

## 16.3 定时重探测

对高优先级候选或即将过期候选做轻量重探测。

---

## 17. 可观测性与排障设计

生产系统必须能回答以下问题：

1. 为什么这个 provider 没被选中？
2. 为什么这个 candidate 被过滤了？
3. 为什么这次路由走了直连？
4. 为什么 `list_api` 拉取成功但下载仍失败？
5. 是 provider API 问题，还是 candidate 节点问题？

## 17.1 日志建议

至少记录：

- provider 拉取开始/结束
- 拉取耗时
- 原始 items 数量
- 标准化成功数/失败数
- 安全过滤丢弃数
- 轻量探测成功/失败数
- 场景过滤结果
- 最终 selected topN
- 下载阶段 candidate 命中与失败回写

日志中永远只输出：
- `masked_proxy_endpoint`
- provider 名称
- candidate_key

不要输出明文用户密码。

## 17.2 指标建议

建议至少聚合：

- provider refresh success rate
- provider refresh latency
- candidate normalization failure rate
- candidate probe success rate
- route hit by source (`account_static/system_paid/system_free/direct`)
- list_api candidate usage rate
- candidate download success rate
- `proxy_pool` fallback hit rate（进入第 2/3/... 个候选的比例，用于判断 top1 质量）

---

## 18. UI / 产品层建议

虽然本文件不实现前端，但生产方案必须对 UI 有明确要求。

## 18.1 Provider 配置页应分两层

### 基础层

- 名称
- 启用状态
- billing_tier
- priority
- supports_cookies
- supports_auto_download
- risk_level

### 高级层

- 模板型 / 专属型切换
- 请求配置
- 认证配置
- 分页配置
- 字段映射配置
- 默认筛选参数
- refresh_interval_seconds

## 18.2 候选池可见性

每个 provider 应能看到：

- 最近拉取时间
- 最近拉取成功/失败
- 当前可用候选数
- Top 候选预览
- 最近失败原因分布
- 是否处于 provider 冷却状态

---

## 19. 测试策略

要把这个方案做成生产可用，测试不能只测 happy path。

## 19.1 单元测试

覆盖：

- 字段映射
- 协议归一化
- host/port 校验
- 私网地址过滤
- score 计算
- 场景过滤
- cache key 生成

## 19.2 集成测试

覆盖：

- 模板型 provider 的完整 fetch → normalize → pool
- 专属 adapter provider 的完整链路
- provider refresh 后候选池落库
- routing-preview 在 list_api 场景下的返回
- `proxy_router` 对 `proxy_pool` 的消费

## 19.3 回归测试

必须保证不破坏现有：

- `account_static` 路由
- `system_only` / `account_only` / `direct_only`
- Cookie 场景风险限制
- auto download 对 free proxy 的限制

## 19.4 故障测试

模拟：

- provider API 500
- provider API 返回空数据
- provider API 字段漂移
- 单个 candidate 重复失败
- 缓存失效 + 实时补拉失败
- 全部候选不可用时的直连/失败兜底

---

## 20. 迁移与落地顺序建议

建议分 4 期落地，而不是一口气改完。

### Phase 1：基础平台层

- 新增 `dynamic_proxy_candidates` 表
- 新增 canonical model
- 新增模板执行器
- 新增 provider refresh 流程
- 先只支持模板型 `list_api`

### Phase 2：路由集成层

- `list_api` 输出 `proxy_pool`
- router 接 selector
- routing preview 增强
- 下载阶段失败回写 candidate 质量

### Phase 3：质量与观测层

- 分层验证
- score 模型
- provider/candidate 双层熔断
- 候选预览与排障 API

### Phase 4：复杂 provider 扩展层

- 支持 custom adapter
- 支持特殊分页/签名
- 支持更多 provider 模板

---

## 21. 对 Geonode 的适用性判断

Geonode 只是这个架构下的一家 provider，而不是架构中心。

在本方案下，Geonode 可以有两种接入方式：

1. **模板型接入**
   - 如果其 API 结构足够稳定、字段可通过映射完成提取
2. **专属 adapter 接入**
   - 如果其分页、字段选择或认证行为特殊

关键点在于：

- Geonode 进入系统后，最终仍要被标准化成 `CanonicalProxyCandidate`
- 它不会污染 router 语义
- 它也不会要求下载器认识 Geonode

这正是本方案的长期价值。

---

## 22. 最终结论

生产级 `list_api` 方案的正确方向不是“把某家 provider 的 JSON 直接塞给路由器”，而是建立一层 **统一代理候选平台**：

- 以 **Canonical Proxy Candidate** 为统一出口
- 以 **模板优先 + 专属 adapter 兜底** 为接入策略
- 以 **SQLite 持久候选池 + 内存热缓存** 为存储结构
- 以 **安全过滤 → 轻探测 → 场景化验证** 为质量门控
- 以 **provider 级冷却 + candidate 级降权** 为容错机制
- 以 **router 只消费 `proxy` / `proxy_pool`** 为边界约束

这套方案兼容当前项目结构，能逐步落地，也能支持未来多 provider 长期演进。
