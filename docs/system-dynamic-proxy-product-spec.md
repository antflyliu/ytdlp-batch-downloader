# 系统默认动态代理产品规格

> 版本: v1
> 日期: 2026-04-06
> 状态: 可进入开发拆解
> 范围: 仅定义字段、接口、页面、迁移、验收和测试要求，不包含代码实现

---

## 一、需求摘要

目标行为如下：

| 场景 | 目标行为 |
|---|---|
| 添加账户时未选择固定代理 | 下载时可按系统默认动态代理回退 |
| 账户固定代理为空 | 下载时可按系统默认动态代理回退 |
| 账户固定代理未启动或不可用 | 下载时可按系统默认动态代理回退 |
| 手动下载 | 支持固定代理、动态代理、直连三层路由 |
| 自动下载 | 支持固定代理与可信动态代理，不允许免费代理默认参与 |

本规格面向当前项目，不改变既有功能的核心原则如下：

- 保留现有账户固定代理能力
- 保留现有下载器 `proxy_pool` 轮换能力
- 不无提示改变历史账户行为
- 不让免费代理默认参与 Cookie 下载

---

## 二、范围定义

### 2.1 本期范围

- 新增系统默认动态代理能力
- 新增动态代理提供方管理
- 新增下载路由策略
- 打通手动下载与自动下载的统一代理解析链路
- 在 UI 中新增配置和状态展示
- 增加下载日志中的线路决策可见性

### 2.2 本期不做

- 不做供应商自动计费管理
- 不做代理使用费用统计
- 不做浏览器代理或 API 请求代理统一路由
- 不做多租户隔离
- 不做动态代理市场比价

---

## 三、现状基线

当前项目已有的关键基线：

| 能力 | 文件 | 现状 |
|---|---|---|
| 全局配置 | `monitor/db.py` | 支持 `download_cookies_file`、`download_output_path`、`default_api_key_id` 等字段 |
| 账户固定代理 | `monitor/db.py` | 账户依赖 `proxy_pool_id + proxy_enabled` 获取固定代理 |
| Web 手动批量下载 | `monitor_server.py` | 下载前会解析账户固定代理并传给下载器 |
| 自动下载 | `monitor/scheduler.py` | 自动下载前也会解析账户固定代理 |
| 下载器轮换 | `Youtube_Downloader.py` | `batch_download()` 支持 `proxy` 与 `proxy_pool` |
| Web 配置页 | `monitor_web/index.html` | 已有全局设置、账户弹窗、固定代理管理界面 |

结论：

- 动态代理最适合接入在“下载前线路解析层”
- 不应直接改造下载器主逻辑为“懂供应商”
- 下载器继续只接收最终代理或最终代理列表

---

## 四、数据模型规格

### 4.1 全局配置新增字段

建议在现有 `config.json` 中新增：

| 字段 | 类型 | 必填 | 默认值 |
|---|---|---|---|
| `system_dynamic_proxy_enabled` | bool | 是 | `false` |
| `apply_dynamic_proxy_to_new_accounts` | bool | 是 | `true` |
| `apply_dynamic_proxy_to_existing_accounts` | bool | 是 | `false` |
| `manual_download_route_policy` | string | 是 | `"balanced"` |
| `auto_download_route_policy` | string | 是 | `"strict"` |
| `allow_free_proxy` | bool | 是 | `true` |
| `allow_free_proxy_for_auto_download` | bool | 是 | `false` |
| `allow_free_proxy_with_cookies` | bool | 是 | `false` |
| `manual_direct_fallback` | bool | 是 | `true` |
| `auto_direct_fallback` | bool | 是 | `false` |
| `default_proxy_country_codes` | array[string] | 否 | `[]` |
| `default_proxy_protocol_order` | array[string] | 是 | `["http","https","socks5"]` |
| `default_session_mode` | string | 是 | `"sticky"` |
| `default_sticky_minutes` | int | 是 | `10` |
| `candidate_prefetch_count` | int | 是 | `5` |
| `candidate_validate_count` | int | 是 | `3` |
| `validated_pool_ttl_seconds` | int | 是 | `300` |
| `provider_cooldown_seconds` | int | 是 | `600` |
| `proxy_probe_timeout_seconds` | int | 是 | `8` |
| `mask_proxy_in_logs` | bool | 是 | `true` |

字段约束：

| 字段 | 约束 |
|---|---|
| `manual_download_route_policy` | `balanced` / `aggressive` / `direct_first` |
| `auto_download_route_policy` | `strict` / `balanced` |
| `default_session_mode` | `sticky` / `rotating` |
| `candidate_prefetch_count` | 1-20 |
| `candidate_validate_count` | 1-10 且不大于 `candidate_prefetch_count` |

### 4.2 新增表：`dynamic_proxy_providers`

建议新增表结构字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | INTEGER PK | 是 | 主键 |
| `name` | TEXT | 是 | 显示名称 |
| `enabled` | INTEGER | 是 | 0=禁用 1=启用 |
| `billing_tier` | TEXT | 是 | `free` / `paid` |
| `adapter_type` | TEXT | 是 | `public_feed` / `list_api` / `rotating_gateway` / `local_gateway` |
| `priority` | INTEGER | 是 | 数字越小越优先 |
| `supports_cookies` | INTEGER | 是 | 0/1 |
| `supports_auto_download` | INTEGER | 是 | 0/1 |
| `supports_country_filter` | INTEGER | 是 | 0/1 |
| `supports_sticky_session` | INTEGER | 是 | 0/1 |
| `risk_level` | TEXT | 是 | `low` / `medium` / `high` |
| `notes` | TEXT | 否 | 备注 |
| `config_json` | TEXT | 是 | 供应商配置 JSON |
| `last_health_status` | TEXT | 否 | 最近健康状态 |
| `last_health_checked_at` | TEXT | 否 | 最近检查时间 |
| `last_error_message` | TEXT | 否 | 最近错误摘要 |
| `cooldown_until` | TEXT | 否 | 冷却截止时间 |
| `created_at` | TEXT | 是 | 创建时间 |
| `updated_at` | TEXT | 是 | 更新时间 |

索引建议：

- `idx_dynamic_proxy_enabled_priority` on `(enabled, priority)`
- `idx_dynamic_proxy_health` on `(last_health_status, cooldown_until)`

### 4.3 账户表新增字段

建议为 `monitor_accounts` 新增：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `download_proxy_mode` | TEXT | 是 | `auto` | `auto` / `account_only` / `system_only` / `direct_only` |

迁移默认值：

- 所有历史账户默认 `download_proxy_mode='auto'`
- 但系统是否实际对历史账户启用动态回退，仍受全局 `apply_dynamic_proxy_to_existing_accounts` 控制

### 4.4 下载日志补充字段

建议在下载任务记录或视频下载状态记录中新增：

| 字段 | 说明 |
|---|---|
| `resolved_proxy_source` | 线路来源 |
| `resolved_provider_name` | 提供方名称 |
| `resolved_provider_tier` | 免费或付费 |
| `resolved_country` | 国家 |
| `resolved_session_mode` | 会话模式 |
| `fallback_depth` | 命中第几层回退 |
| `masked_proxy_endpoint` | 掩码代理地址 |
| `decision_reason` | 决策原因 |

如果本期不改已有主业务表，可先新增独立下载决策日志表。

---

## 五、接口规格

### 5.1 配置接口

复用现有：

- `GET /api/config`
- `POST /api/config`

要求：

- `GET /api/config` 返回新增字段
- `POST /api/config` 支持保存新增字段
- 配置项缺失时按默认值补齐
- 对旧配置文件兼容读取

### 5.2 动态代理提供方接口

新增：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/dynamic-providers` | 列出动态代理提供方 |
| `POST` | `/api/dynamic-providers` | 新增提供方 |
| `POST` | `/api/dynamic-providers/{id}/update` | 更新提供方 |
| `DELETE` | `/api/dynamic-providers/{id}` | 删除提供方 |
| `POST` | `/api/dynamic-providers/{id}/health-check` | 立即检查健康状态 |
| `POST` | `/api/dynamic-providers/{id}/cooldown/clear` | 清除冷却 |

返回字段要求：

| 字段 | 说明 |
|---|---|
| `masked_preview` | 掩码后的出口预览 |
| `status_text` | 可读状态文案 |
| `last_error_message` | 最近失败原因摘要 |
| `capabilities` | 支持能力标签 |

### 5.3 下载决策预览接口

建议新增：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/download-routing/preview` | 输入账户、cookies、模式等信息，返回本次将如何选择线路 |

用途：

- 账户编辑弹窗中实时预览
- 下载前展示“本次线路”
- 测试与排障

返回示例字段：

| 字段 | 说明 |
|---|---|
| `resolved_source` | 预计命中的线路来源 |
| `provider_name` | 预计命中的提供方 |
| `reason` | 命中原因 |
| `warnings` | 风险提示 |
| `fallback_chain` | 预计回退链路 |

### 5.4 手动下载接口改造

当前接口继续复用：

- `POST /api/accounts/{id}/videos/batch-download`

新增要求：

| 项目 | 要求 |
|---|---|
| 线路解析 | 改为统一走下载路由解析层 |
| 响应字段 | 返回 `resolved_proxy_source`、`resolved_provider_name` 等信息 |
| 错误信息 | 当所有线路都不可用时，返回结构化失败原因 |

### 5.5 自动下载流程改造

不新增对外接口，但内部调度流程要求：

- 自动下载必须走统一下载路由解析层
- 默认不允许免费公共代理参与
- 默认不允许静默直连
- 找不到可用线路时，将失败写入日志并标记待重试

---

## 六、路由决策规格

### 6.1 输入参数

下载路由解析层输入至少包括：

| 参数 | 说明 |
|---|---|
| `account` | 当前账户 |
| `download_proxy_mode` | 账户下载模式 |
| `is_auto_download` | 是否自动下载 |
| `cookies_file_present` | 是否带 Cookie |
| `user_forced_direct` | 用户是否显式选择直连 |
| `global_config` | 全局配置 |

### 6.2 输出结构

统一输出：

| 字段 | 说明 |
|---|---|
| `resolved_mode` | 最终模式 |
| `proxy` | 单个代理出口，若适用 |
| `proxy_pool` | 一组候选代理，若适用 |
| `provider_name` | 提供方 |
| `provider_tier` | 付费或免费 |
| `resolved_proxy_source` | 固定、系统付费、系统免费、直连 |
| `reason` | 命中原因 |
| `warnings` | 风险提示 |

### 6.3 决策规则

`download_proxy_mode=auto`：

1. 用户显式指定直连 -> 直连
2. 账户固定代理可用 -> 用固定代理
3. 固定代理不可用 -> 尝试系统动态代理
4. 系统动态代理优先选付费提供方
5. 若允许免费代理且当前无 Cookie，则尝试免费提供方
6. 若仍失败且允许直连，则直连
7. 否则失败

`download_proxy_mode=account_only`：

1. 固定代理可用 -> 用固定代理
2. 否则直接失败

`download_proxy_mode=system_only`：

1. 直接走系统动态代理
2. 是否允许直连由全局策略决定

`download_proxy_mode=direct_only`：

1. 永远直连

### 6.4 特殊约束

| 约束 | 规则 |
|---|---|
| 自动下载 + 免费代理 | 默认禁止 |
| Cookie 下载 + 免费代理 | 默认禁止 |
| 高风险提供方 + Cookie 下载 | 禁止 |
| 提供方处于冷却期 | 跳过 |
| 本地网关未启动 | 跳过并记录 `not_started` |

---

## 七、页面与交互规格

### 7.1 导航与命名

本期命名调整：

| 旧名称 | 新名称 |
|---|---|
| 代理池 | 固定代理 |
| 启用代理下载 | 启用账户固定代理 |

新增入口：

- 动态代理

### 7.2 全局设置页

新增四个区块：

1. 系统默认动态代理
2. 动态代理提供方
3. 下载网络策略
4. 风险控制

表单项必须与第四章字段一一对应。

文案要求：

| 控件 | 文案 |
|---|---|
| 开关 | 启用系统默认动态代理 |
| 说明 | 当账户固定代理不可用时，系统自动尝试这里配置的动态代理线路。 |
| 开关 | 新账户默认继承系统动态代理 |
| 开关 | 对现有账户统一启用系统回退 |
| 开关 | 带 Cookie 下载禁止免费代理 |

### 7.3 动态代理页面

列表列要求：

- 名称
- 类型
- 收费
- 支持场景
- 状态
- 最近检查
- 优先级
- 操作

操作要求：

- 新增
- 编辑
- 启用/禁用
- 立即检测
- 清除冷却
- 删除

### 7.4 账户编辑弹窗

新增区块：下载网络策略

必有控件：

- 下载模式选择器
- 固定代理开关
- 固定代理选择器
- 线路预览按钮

下载模式文案：

| 值 | 文案 |
|---|---|
| `auto` | 自动（推荐） |
| `account_only` | 仅账户固定代理 |
| `system_only` | 仅系统动态代理 |
| `direct_only` | 始终直连 |

### 7.5 下载开始提示

手动下载开始时，前端必须显示：

- 本次线路
- 提供方
- 国家
- 是否粘性会话
- 风险提示

自动下载无需弹窗，但日志中必须记录同等信息。

---

## 八、日志与可观测性规格

必须记录以下事件：

| 事件 | 最少字段 |
|---|---|
| 固定代理命中 | 账户 ID、来源、掩码代理、原因 |
| 固定代理失败 | 账户 ID、失败阶段、错误摘要 |
| 动态提供方命中 | 提供方、收费层级、国家、会话模式 |
| 动态提供方失败 | 提供方、失败类型、冷却截止时间 |
| 免费代理被安全策略跳过 | 原因 |
| 自动下载未找到安全线路 | 账户、视频数、原因 |
| 最终直连 | 原因、是否手动触发 |

日志要求：

- 不记录明文密钥
- 不记录明文用户名密码组合
- 代理地址必须掩码输出

---

## 九、迁移策略

### 9.1 配置迁移

- 旧 `config.json` 无新字段时，读取后自动补默认值
- 保存配置时写回完整字段集

### 9.2 数据库迁移

新增迁移步骤：

1. 创建 `dynamic_proxy_providers`
2. 为 `monitor_accounts` 添加 `download_proxy_mode`
3. 如采用独立下载决策日志表，则一并创建

### 9.3 历史账户行为

历史账户迁移规则：

| 条件 | 行为 |
|---|---|
| 未开启 `apply_dynamic_proxy_to_existing_accounts` | 保持原行为，不自动使用系统动态代理 |
| 开启该开关 | 历史账户在固定代理不可用时可回退系统动态代理 |

### 9.4 文案迁移

- 旧“代理池”文案统一替换为“固定代理”
- 需要在 UI 中明确区分“账户固定代理”和“系统动态代理”

---

## 十、测试要求

### 10.1 单元测试

至少覆盖：

| 场景 | 要求 |
|---|---|
| `auto` 模式命中固定代理 | 返回固定代理 |
| 固定代理不可用回退付费动态代理 | 返回付费动态代理 |
| 手动下载无 Cookie 回退免费代理 | 允许命中免费代理 |
| 自动下载禁止免费代理 | 不命中免费代理 |
| 带 Cookie 下载跳过免费代理 | 不命中免费代理 |
| `account_only` 无固定代理 | 返回失败 |
| `system_only` 仅系统动态代理 | 不读固定代理 |
| `direct_only` | 永远直连 |
| 提供方冷却期 | 被跳过 |
| 本地网关未启动 | 被跳过并返回原因 |

### 10.2 集成测试

至少覆盖：

| 场景 | 要求 |
|---|---|
| `GET /api/config` 返回新增字段 | 结构完整 |
| `POST /api/config` 可保存新增字段 | 读取回写一致 |
| 动态代理提供方 CRUD | 全流程可用 |
| 手动批量下载接口返回线路决策结果 | 字段完整 |
| 自动下载失败进入待重试 | 不静默直连 |

### 10.3 UI 测试

至少覆盖：

| 场景 | 要求 |
|---|---|
| 全局设置可编辑动态代理开关 | 页面显示正确 |
| 账户弹窗可切换下载模式 | 文案正确 |
| 线路预览展示正确 | 能看到命中原因 |
| 固定代理与动态代理文案分离 | 不混淆 |

---

## 十一、验收标准

本功能完成必须满足以下条件：

| 编号 | 验收标准 |
|---|---|
| AC-1 | 新账户未选择固定代理时，手动下载可按系统策略命中动态代理 |
| AC-2 | 固定代理禁用、为空或不可用时，手动下载可自动回退 |
| AC-3 | 自动下载默认只尝试固定代理与可信付费动态代理 |
| AC-4 | 带 Cookie 下载默认不会走免费公共代理 |
| AC-5 | UI 中可明确区分固定代理与动态代理 |
| AC-6 | 每次下载都能看到或追踪到实际线路来源 |
| AC-7 | 历史账户在未开启迁移开关前，不改变原有行为 |
| AC-8 | 所有密钥与敏感凭据均不以明文暴露在日志与列表中 |

---

## 十二、开发拆解建议

建议按以下顺序拆开发任务：

1. 配置字段与数据库迁移
2. 动态代理提供方 CRUD
3. 下载路由解析层
4. 手动下载接入统一路由
5. 自动下载接入统一路由
6. UI 页面与文案调整
7. 日志与观测字段补齐
8. 测试补齐

拆分原则：

- 先打基础数据结构
- 再做路由解析
- 最后接入 UI 和下载流程

---

## 十三、建议文件清单

本规格对应的主要改动面如下：

| 类别 | 文件或模块 |
|---|---|
| 配置与迁移 | `monitor/db.py`、`monitor/schema.sql` |
| 下载路由 | 新增代理解析模块 |
| 手动下载接入 | `monitor_server.py` |
| 自动下载接入 | `monitor/scheduler.py` |
| Web UI | `monitor_web/index.html` |
| Tk UI | `monitor_ui.py` |
| 测试 | `tests/` 下新增路由与配置相关测试 |

