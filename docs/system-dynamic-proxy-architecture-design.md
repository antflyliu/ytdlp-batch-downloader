# 系统默认动态代理架构设计稿

> 版本: v1
> 日期: 2026-04-06
> 目标: 为当前项目设计一套可替换供应商、支持免费与付费并存、兼容现有固定代理逻辑的系统默认动态代理方案

---

## 一、背景与目标

当前项目已经具备两类与下载相关的能力：

| 能力 | 当前状态 |
|---|---|
| 账户固定代理 | 已支持，账户可绑定一个代理节点并启用 |
| 下载器代理轮换 | 已支持，`batch_download()` 可接收 `proxy_pool` 并在失败时轮换 |

当前项目还缺少以下能力：

| 缺口 | 说明 |
|---|---|
| 系统默认动态代理 | 当账户未绑定固定代理或固定代理不可用时，没有统一回退方案 |
| 多供应商抽象 | 代理能力被限定为“单个 URL”，无法自然接入动态供应商 |
| 风险分级 | 免费公共代理、付费动态代理、本地网关没有被区别对待 |
| 下载路由策略 | 手动下载、自动下载、带 Cookie 下载没有不同的网络策略 |

本设计稿的目标不是围绕某一家服务商落方案，而是建立一个长期可扩展的代理能力架构。

---

## 二、设计原则

| 原则 | 解释 |
|---|---|
| 兼容现有逻辑 | 不打碎当前“账户固定代理 + 下载器轮换”能力 |
| 供应商可替换 | 不能将 Proxifly、Webshare、Oxylabs、Bright Data 等写死到核心流程 |
| 风险分级 | 免费代理、付费代理、本地代理必须按风险和可靠性分层 |
| 安全优先 | 带 Cookie 的下载默认不能走免费公共代理 |
| 行为可解释 | 每次下载都能说明“为什么选这条线路” |
| 不静默改行为 | 历史账户不能因为新功能上线而被无提示改成走动态代理 |

---

## 三、能力分层

建议将下载网络能力拆成三层：

| 层级 | 作用 | 当前状态 | 后续动作 |
|---|---|---|---|
| 账户固定代理 | 用户手工绑定的固定代理节点 | 已有 | 保留并改名为“固定代理” |
| 系统默认动态代理 | 固定代理不可用时的统一回退 | 缺失 | 新增 |
| 直连 | 最后兜底 | 已隐式存在 | 明确纳入路由策略 |

建议的统一优先级：

1. 用户本次下载显式指定的线路
2. 账户固定代理
3. 系统默认动态代理
4. 直连

---

## 四、供应商模型

建议新增“动态代理提供方”抽象，并支持四类适配器：

| 适配器类型 | 说明 | 典型来源 | 适合场景 | 不适合场景 |
|---|---|---|---|---|
| `public_feed` | 公共代理清单，系统拉取后本地筛选与验证 | Proxifly Free Proxy List | 手动、低价值、无 Cookie 下载 | 自动下载、Cookie 下载、强稳定性要求 |
| `list_api` | 供应商 API 返回一批代理地址 | Webshare 列表/API | 可批量筛选和缓存的中间方案 | 长时稳定会话、高等级抗封 |
| `rotating_gateway` | 单入口动态代理网关，供应商在后端轮换 | Oxylabs、Bright Data、Decodo、Webshare Backconnect | 自动下载、Cookie 下载、生产主线路 | 强成本敏感场景 |
| `local_gateway` | 本地启动的动态代理入口 | 本地代理客户端、自建网关 | 高级用户、本地控制 | 零运维用户 |

设计判断：

| 结论 | 说明 |
|---|---|
| 生产主线路应优先支持 `rotating_gateway` | 稳定性最好，最适合自动下载和 Cookie 下载 |
| `list_api` 适合作为次优先级 | 便于控制成本，也便于本地缓存与验证 |
| `public_feed` 只能作为低信任末级回退 | 不能作为系统默认主线路 |
| `local_gateway` 必须支持 | 与“代理未启动”这一需求直接相关 |

---

## 五、推荐产品模型

建议将现有“代理池”重新定义为“固定代理”，并新增两个产品概念：

| 概念 | 作用 |
|---|---|
| 固定代理 | 当前已有的账户绑定代理，代表单个固定出口或静态节点 |
| 动态代理提供方 | 系统级可切换供应商能力，管理免费、付费、本地动态代理 |
| 下载网络策略 | 统一定义何时用固定代理、何时回退动态代理、何时允许直连 |

命名建议：

| 当前名称 | 建议名称 | 原因 |
|---|---|---|
| 代理池 | 固定代理 | 后续同时存在动态代理时，“代理池”概念会混淆 |
| 启用代理下载 | 启用账户固定代理 | 避免误认为这是系统动态代理总开关 |

---

## 六、配置与字段设计

### 6.1 全局配置

建议在全局设置中新增以下字段：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `system_dynamic_proxy_enabled` | bool | `false` | 是否启用系统默认动态代理 |
| `apply_dynamic_proxy_to_new_accounts` | bool | `true` | 新账户默认继承系统动态代理 |
| `apply_dynamic_proxy_to_existing_accounts` | bool | `false` | 是否对历史账户启用系统动态代理回退 |
| `manual_download_route_policy` | enum | `balanced` | 手动下载网络策略 |
| `auto_download_route_policy` | enum | `strict` | 自动下载网络策略 |
| `allow_free_proxy` | bool | `true` | 是否允许免费动态代理参与手动下载 |
| `allow_free_proxy_for_auto_download` | bool | `false` | 自动下载是否允许免费代理 |
| `allow_free_proxy_with_cookies` | bool | `false` | 带 Cookie 下载是否允许免费代理 |
| `manual_direct_fallback` | bool | `true` | 手动下载是否允许直连兜底 |
| `auto_direct_fallback` | bool | `false` | 自动下载是否允许直连兜底 |
| `default_proxy_country_codes` | array[str] | `[]` | 国家偏好 |
| `default_proxy_protocol_order` | array[str] | `["http","https","socks5"]` | 协议优先级 |
| `default_session_mode` | enum | `sticky` | 默认会话模式 |
| `default_sticky_minutes` | int | `10` | 默认粘性会话时长 |
| `candidate_prefetch_count` | int | `5` | 动态代理一次预取数量 |
| `candidate_validate_count` | int | `3` | 一次实际验证的候选数量 |
| `validated_pool_ttl_seconds` | int | `300` | 已验证代理缓存时长 |
| `provider_cooldown_seconds` | int | `600` | 提供方失败后的冷却时间 |
| `proxy_probe_timeout_seconds` | int | `8` | 单次代理探测超时 |
| `mask_proxy_in_logs` | bool | `true` | 日志中是否掩码代理出口 |

### 6.2 动态代理提供方

建议新增“动态代理提供方”配置对象，公共字段如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 主键 |
| `name` | string | 显示名称 |
| `enabled` | bool | 是否启用 |
| `billing_tier` | enum | `free` / `paid` |
| `adapter_type` | enum | `public_feed` / `list_api` / `rotating_gateway` / `local_gateway` |
| `priority` | int | 优先级，数字越小越优先 |
| `supports_cookies` | bool | 是否允许 Cookie 下载 |
| `supports_auto_download` | bool | 是否允许自动下载 |
| `supports_country_filter` | bool | 是否支持国家筛选 |
| `supports_sticky_session` | bool | 是否支持粘性会话 |
| `risk_level` | enum | `low` / `medium` / `high` |
| `notes` | string | 备注 |
| `last_health_status` | enum | `healthy` / `degraded` / `down` / `auth_error` / `not_started` |
| `last_health_checked_at` | datetime | 最近健康检查时间 |
| `last_error_message` | string | 最近错误摘要 |
| `cooldown_until` | datetime | 冷却截止时间 |

### 6.3 适配器专属字段

`public_feed`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `feed_urls` | array[str] | 代理源地址，可多个 |
| `response_format` | enum | `json` / `txt` / `csv` |
| `country_codes` | array[str] | 国家筛选 |
| `protocols` | array[str] | 协议筛选 |
| `https_required` | bool | 是否必须支持 HTTPS |
| `anonymity_allowlist` | array[str] | 推荐仅允许 `anonymous` 与 `elite` |
| `min_score` | int | 最低评分阈值 |
| `fetch_limit` | int | 每次拉取上限 |

`list_api`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `api_base_url` | string | API 基地址 |
| `auth_type` | enum | `bearer` / `api_key` / `basic` |
| `auth_secret` | secret | 密钥或令牌，必须加密存储 |
| `list_endpoint` | string | 拉取代理列表接口 |
| `download_endpoint` | string | 下载代理列表地址，可选 |
| `query_defaults` | json | 默认筛选参数 |
| `refresh_interval_seconds` | int | 刷新频率 |

`rotating_gateway`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `gateway_host` | string | 网关主机 |
| `gateway_port` | int | 网关端口 |
| `protocol` | enum | `http` / `https` / `socks5` |
| `auth_type` | enum | `basic` / `whitelist_ip` |
| `username` | string | 用户名或前缀 |
| `password` | secret | 密码，必须加密存储 |
| `country_mode` | enum | `none` / `username_param` / `endpoint_param` |
| `session_mode` | enum | `random` / `sticky` |
| `sticky_max_minutes` | int | 最大粘性时长 |

`local_gateway`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `local_proxy_url` | string | 本地代理入口 |
| `healthcheck_url` | string | 健康检查地址 |
| `process_name` | string | 可选，用于进程探测 |
| `startup_hint` | string | 启动提示文案 |
| `auto_detect_running` | bool | 是否自动检测运行状态 |

### 6.4 账户字段

建议新增账户级字段：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `download_proxy_mode` | enum | `auto` | `auto` / `account_only` / `system_only` / `direct_only` |

保留并重新解释现有字段：

| 字段 | 解释 |
|---|---|
| `proxy_pool_id` | 账户固定代理节点 ID |
| `proxy_enabled` | 是否启用账户固定代理 |

### 6.5 下载记录补充字段

建议在下载任务或下载日志中补充以下字段：

| 字段 | 说明 |
|---|---|
| `resolved_proxy_source` | `account_static` / `system_paid` / `system_free` / `direct` |
| `resolved_provider_name` | 实际命中的提供方名称 |
| `resolved_provider_tier` | `free` / `paid` |
| `resolved_country` | 实际国家 |
| `resolved_session_mode` | `sticky` / `rotating` |
| `fallback_depth` | 命中的是第几层回退 |
| `masked_proxy_endpoint` | 掩码后的代理出口 |
| `decision_reason` | 本次线路选择原因 |

---

## 七、统一回退规则

### 7.1 统一原则

所有下载入口都应走同一套代理解析逻辑：

- Web 手动批量下载
- 监控后的自动下载
- 后续可能新增的 CLI 账户下载

### 7.2 手动下载规则

当账户 `download_proxy_mode=auto` 时：

1. 如果用户本次明确指定“直连”，则直接直连
2. 如果账户启用了固定代理，则优先尝试账户固定代理
3. 固定代理不存在、被禁用、为空、未启动、探测失败时，转系统默认动态代理
4. 系统默认动态代理优先尝试付费提供方
5. 如果允许免费代理，且本次不带 Cookie，则再尝试免费提供方
6. 若仍失败，且允许手动直连，则直连
7. 若不允许直连，则直接返回失败

### 7.3 自动下载规则

当账户 `download_proxy_mode=auto` 时：

1. 先尝试账户固定代理
2. 再尝试系统付费动态代理
3. 默认不尝试免费公共代理
4. 默认不允许自动直连
5. 所有可用线路失败时，进入待重试或失败队列

### 7.4 带 Cookie 下载规则

只要存在 `cookies_file`：

| 规则 | 说明 |
|---|---|
| 跳过免费公共代理 | 默认禁止免费代理参与 |
| 跳过高风险提供方 | `risk_level=high` 的线路不参与 |
| 只允许可信线路 | 账户固定代理、支持 Cookie 的付费动态代理、或直连 |

### 7.5 提供方内部切换规则

| 类型 | 内部重试方式 |
|---|---|
| `public_feed` | 同一批次先在候选代理中切换，再切换提供方 |
| `list_api` | 同一批次先在已验证列表中切换，再切换提供方 |
| `rotating_gateway` | 同一提供方先换 session，再切换提供方 |
| `local_gateway` | 未启动直接跳过，不做高频重试 |

---

## 八、界面设计与文案建议

### 8.1 顶部导航

建议新增两个入口：

- 固定代理
- 动态代理

并将现有“代理池”改名为“固定代理”。

### 8.2 全局设置新增区块

建议新增四个区块：

- 系统默认动态代理
- 动态代理提供方
- 下载网络策略
- 风险控制

建议文案：

| 控件 | 文案 |
|---|---|
| 开关 | 启用系统默认动态代理 |
| 说明 | 当账户固定代理不可用时，系统自动尝试这里配置的动态代理线路。 |
| 开关 | 新账户默认继承系统动态代理 |
| 说明 | 新建账户时，如果没有绑定固定代理，将自动按系统策略选择动态代理。 |
| 开关 | 对现有账户统一启用系统回退 |
| 说明 | 开启后，历史账户在固定代理不可用时也会自动尝试系统动态代理。此项会改变现有行为。 |

### 8.3 动态代理提供方列表

表格列建议：

- 名称
- 类型
- 收费
- 适用场景
- 状态
- 最近检查
- 优先级
- 操作

状态文案建议：

| 状态 | 文案 |
|---|---|
| `healthy` | 可用 |
| `degraded` | 降级 |
| `auth_error` | 认证失败 |
| `down` | 不可用 |
| `not_started` | 未启动 |
| `cooldown` | 冷却中 |

标签文案建议：

- 免费
- 付费
- 公共清单
- 动态网关
- 本地网关
- 仅无 Cookie
- 自动下载可用

### 8.4 账户编辑弹窗

建议新增区块：下载网络策略

选项文案：

| 值 | 文案 | 说明 |
|---|---|---|
| `auto` | 自动（推荐） | 优先使用账户固定代理，不可用时回退到系统动态代理 |
| `account_only` | 仅账户固定代理 | 只使用账户绑定的固定代理，不做系统回退 |
| `system_only` | 仅系统动态代理 | 忽略账户固定代理，始终使用系统动态代理 |
| `direct_only` | 始终直连 | 本账户下载不使用任何代理 |

原有文案建议：

| 当前文案 | 建议文案 |
|---|---|
| 启用代理下载（防止下载时 IP 被限流） | 启用账户固定代理 |

辅助说明建议：

- 未选择固定代理时，可自动继承系统默认动态代理

### 8.5 下载任务提示

下载开始后应向用户明确展示：

| 提示项 | 示例 |
|---|---|
| 本次线路 | 系统付费动态代理 |
| 提供方 | Webshare Residential |
| 地区 | US |
| 会话 | Sticky 10 分钟 |

---

## 九、异常处理设计

| 场景 | 用户提示 | 系统行为 |
|---|---|---|
| 固定代理未配置 | 未找到账户固定代理，已尝试系统默认动态代理。 | 进入系统动态代理流程 |
| 固定代理被禁用 | 账户固定代理已禁用，已尝试系统默认动态代理。 | 跳过固定代理 |
| 本地网关未启动 | 本地动态代理未启动。 | 标记 `not_started` 并跳过 |
| 提供方认证失败 | 动态代理认证失败，请检查账号或密钥。 | 标记 `auth_error` 并暂停使用该提供方 |
| 提供方无可用代理 | 动态代理未返回可用节点。 | 切换下一个提供方 |
| 免费代理验证失败 | 免费代理不可用，已切换下一条线路。 | 丢弃当前候选并继续回退 |
| 带 Cookie 下载命中免费代理 | 当前下载带 Cookie，已按安全策略跳过免费代理。 | 不使用免费代理 |
| 下载中途 429 或限流 | 当前代理可能被限流，正在切换线路。 | 同提供方先换 IP 或 session，再换提供方 |
| 所有提供方均不可用 | 未找到可用代理线路。 | 手动下载按策略决定是否直连；自动下载进入待重试 |
| 自动下载未找到安全线路 | 自动下载未执行，等待下一次重试。 | 不允许静默直连 |

---

## 十、默认风险控制建议

建议默认值如下：

| 项目 | 推荐默认值 |
|---|---|
| 新账户默认继承系统动态代理 | 开 |
| 历史账户默认跟随系统动态代理 | 关 |
| 免费代理参与手动下载 | 开 |
| 免费代理参与自动下载 | 关 |
| 免费代理参与 Cookie 下载 | 关 |
| 手动下载允许直连兜底 | 开 |
| 自动下载允许直连兜底 | 关 |
| 付费动态代理默认会话模式 | Sticky 10 分钟 |
| 免费动态代理默认会话模式 | Rotating |
| 验证通过缓存 TTL | 300 秒 |
| 提供方失败冷却 | 600 秒 |

---

## 十一、设计取舍总结

### 11.1 推荐方案

| 层级 | 推荐角色 |
|---|---|
| 主线路 | `rotating_gateway` 付费提供方 |
| 次线路 | `list_api` 付费或低成本提供方 |
| 末级回退 | `public_feed` 免费代理 |
| 高风险场景 | 禁止免费代理参与 |

### 11.2 不推荐方案

| 不推荐做法 | 原因 |
|---|---|
| 将 Proxifly 免费清单直接作为系统默认主线路 | 稳定性和安全边界不足 |
| 将动态代理混入现有固定代理池 | 概念混乱，后续难维护 |
| 无提示地改变所有历史账户行为 | 会带来不可控的行为变化 |
| 自动下载失败后静默直连 | 可能暴露本机出口，风险过高 |

### 11.3 第一阶段建议

如果第一阶段只做最小可行版本，建议：

1. 保留现有固定代理逻辑
2. 新增动态代理提供方
3. 第一批只支持三类适配器：
   - `public_feed`
   - `rotating_gateway`
   - `local_gateway`
4. 默认策略：
   - 手动下载：固定代理 -> 付费动态代理 -> 免费动态代理 -> 直连
   - 自动下载：固定代理 -> 付费动态代理 -> 待重试

---

## 十二、外部参考

- Proxifly Free Proxy List README
- Proxifly SDK / API README
- Webshare Proxy Server API
- Webshare Proxy List API / Download API
- Webshare 自动替换文档
- Oxylabs Session Control / Protocols
- Bright Data Proxy Rotation Control / Residential Configuration
- Decodo Sticky Session 文档

