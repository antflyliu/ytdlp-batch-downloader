-- ============================================================
-- YouTube Monitor 数据库 Schema
-- 文件: monitor/schema.sql
-- 说明: 与 yt_channel_fetch 的 videos.db 完全独立
--       仅记录监控发现的新视频事件，不干预下载数据
-- ============================================================

-- ── YouTube API Key 配置表 ───────────────────────────────
-- 存储多个 API Key，支持配额追踪和账户分配
CREATE TABLE IF NOT EXISTS api_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT, -- 内部主键，供账户关联与管理 UI 使用
    key_value       TEXT    NOT NULL UNIQUE,           -- 实际的 YouTube Data API Key（敏感值，唯一）
    name            TEXT    NOT NULL,                  -- 人类可读名称，如 "Key-1" / "主账号 Key"
    daily_quota     INTEGER NOT NULL DEFAULT 10000,    -- 该 Key 的单日配额上限（单位与 YouTube API 保持一致）
    quota_used      INTEGER NOT NULL DEFAULT 0,        -- 该 Key 在当前配额周期内已消耗的配额
    quota_reset_at  TEXT    NOT NULL,                  -- 当前配额周期的重置日期，格式 YYYY-MM-DD
    is_active       INTEGER NOT NULL DEFAULT 1,        -- 启用标记：0=禁用，1=启用
    created_at      TEXT    NOT NULL,                  -- 创建时间，ISO8601（本地时区）
    updated_at      TEXT    NOT NULL                   -- 最近更新时间，ISO8601（本地时区）
);

CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(is_active);

-- ── API 配额使用统计 ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_quota_usage (
    api_key_value   TEXT NOT NULL,             -- 对应 api_keys.key_value；按值聚合历史配额使用
    date_key        TEXT NOT NULL,             -- 统计日期，格式 YYYY-MM-DD
    api_calls       INTEGER DEFAULT 0,         -- 当日累计 API 调用次数 / 单位
    scans_done      INTEGER DEFAULT 0,         -- 当日已完成的扫描次数
    blocked_scans   INTEGER DEFAULT 0,         -- 因配额不足被阻止的扫描次数
    updated_at      TEXT NOT NULL,             -- 最近一次更新该统计行的时间
    PRIMARY KEY (api_key_value, date_key)
);

CREATE INDEX IF NOT EXISTS idx_quota_date ON api_quota_usage(date_key);

-- ── 频道元信息缓存 ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS channel_meta_cache (
    handle               TEXT PRIMARY KEY,     -- 用户输入的 handle / 频道 URL 归一化键
    channel_id           TEXT NOT NULL,        -- YouTube 频道 ID（UC...）
    channel_name         TEXT,                 -- 缓存时刻的频道显示名称
    uploads_playlist_id  TEXT,                 -- 该频道 uploads playlist ID（UU...）
    subscriber_count     TEXT,                 -- 抓取时的订阅数文本，主要用于展示
    video_count          TEXT,                 -- 抓取时的视频总数文本，主要用于展示
    description          TEXT,                 -- 频道简介快照
    cached_at            TEXT NOT NULL         -- 缓存写入时间，ISO8601
);

CREATE INDEX IF NOT EXISTS idx_channel_cache_channel_id ON channel_meta_cache(channel_id);

-- ── schema 迁移版本表 ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,              -- 迁移版本号，如 v7_dynamic_proxy
    applied_at  TEXT NOT NULL                  -- 迁移应用日期，YYYY-MM-DD
);

-- ── 兼容历史 Alembic 版本表 ───────────────────────────────
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,          -- 历史 Alembic 版本号（兼容旧版本或外部工具）
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- ── IP 代理池表 ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS proxy_pools (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,     -- 固定代理节点主键
    name        TEXT    NOT NULL,                      -- 显示名称，如 "香港节点-01"
    proxy_url   TEXT    NOT NULL,                      -- 原始代理 URL，如 http://user:pass@host:port
    enabled     INTEGER NOT NULL DEFAULT 1,            -- 节点是否启用：0=禁用，1=启用
    created_at  TEXT    NOT NULL,                      -- 创建时间，ISO8601
    updated_at  TEXT    NOT NULL                       -- 最近更新时间，ISO8601
);

CREATE INDEX IF NOT EXISTS idx_proxy_pools_enabled ON proxy_pools(enabled);

-- ── 监控账户配置表 ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitor_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,     -- 监控账户主键
    name            TEXT    NOT NULL,                      -- UI 展示名称，如 "综艺Show"
    channel_url     TEXT    NOT NULL,                      -- 用户录入的频道标识：@handle / UC... / 完整 URL
    api_key_id      INTEGER DEFAULT NULL,                  -- 绑定的 api_keys.id；存在时优先于 api_key_env
    api_key_env     TEXT    NOT NULL,                      -- 兼容旧数据的环境变量名，如 YOUTUBE_Data_API_V3
    proxy_pool_id   INTEGER DEFAULT NULL,                  -- 绑定的固定代理节点 id；仅 proxy_enabled=1 时生效
    proxy_enabled   INTEGER NOT NULL DEFAULT 0,            -- 固定代理开关：0=关闭，1=开启
    fetch_mode      TEXT    NOT NULL DEFAULT 'playlist',   -- 扫描模式：search / playlist
    fetch_limit     INTEGER NOT NULL DEFAULT 5,            -- 每次扫描最多抓取的视频条数
    scan_interval   INTEGER NOT NULL DEFAULT 5,            -- 定时扫描间隔（分钟）
    enabled         INTEGER NOT NULL DEFAULT 1,            -- 账户启用状态：0=禁用，1=启用
    notify_enabled  INTEGER NOT NULL DEFAULT 1,            -- 通知总开关：0=关闭，1=开启
    notify_platform TEXT    NOT NULL DEFAULT 'feishu',     -- 通知平台：feishu / dingtalk / wecom
    webhook_url     TEXT    DEFAULT NULL,                  -- 账户级 Webhook（优先级高于全局配置）
    dingtalk_sign_secret TEXT DEFAULT NULL,                -- 钉钉签名密钥；仅钉钉通知使用
    download_proxy_mode TEXT NOT NULL DEFAULT 'auto',      -- 下载路由策略：auto / account_only / system_only / direct_only
    feishu_message_mode TEXT NOT NULL DEFAULT 'card_json', -- 飞书消息模式：card_json / template
    feishu_template_id  TEXT DEFAULT NULL,                 -- 飞书常规通知模板 ID
    feishu_scan_template_id TEXT DEFAULT NULL,             -- 飞书扫描确认模板 ID
    created_at      TEXT    NOT NULL,                      -- 创建时间，ISO8601
    updated_at      TEXT    NOT NULL,                      -- 最近更新时间，ISO8601
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE SET NULL,      -- 删除 Key 后账户退回环境变量/默认 Key
    FOREIGN KEY (proxy_pool_id) REFERENCES proxy_pools(id) ON DELETE SET NULL -- 删除代理池后自动解绑
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_channel_url ON monitor_accounts(channel_url);

-- ── 扫描事件表 ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitor_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,    -- 扫描事件主键
    account_id      INTEGER NOT NULL,                     -- 来源账户 id
    account_name    TEXT    NOT NULL,                     -- 账户名称快照，便于历史查询
    scan_started_at TEXT    NOT NULL,                     -- 扫描开始时间，ISO8601
    scan_ended_at   TEXT    DEFAULT NULL,                 -- 扫描结束时间，ISO8601
    status          TEXT    NOT NULL DEFAULT 'running',   -- 事件状态：running / success / error / skipped
    total_videos    INTEGER NOT NULL DEFAULT 0,           -- 本次扫描从上游拿到的视频总数
    new_videos      INTEGER NOT NULL DEFAULT 0,           -- 本次扫描判定为新增的视频数
    error_message   TEXT    DEFAULT NULL,                 -- 扫描异常时的错误信息
    duration_ms     INTEGER DEFAULT NULL,                 -- 扫描耗时（毫秒）
    FOREIGN KEY (account_id) REFERENCES monitor_accounts(id) ON DELETE CASCADE -- 删除账户时清理其历史扫描事件
);

CREATE INDEX IF NOT EXISTS idx_events_account_id ON monitor_events(account_id);
CREATE INDEX IF NOT EXISTS idx_events_started ON monitor_events(scan_started_at DESC);

-- ── 监控视频详情表 ───────────────────────────────────────
-- 字段设计参考 videos 表，但加上监控特有的 source/status 标注
CREATE TABLE IF NOT EXISTS monitor_videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,     -- 监控视频记录主键
    video_id        TEXT    NOT NULL UNIQUE,               -- YouTube video_id（全局唯一）
    account_id      INTEGER NOT NULL,                      -- 归属监控账户
    event_id        INTEGER NOT NULL,                      -- 首次发现该视频的扫描事件 id
    channel_id      TEXT    DEFAULT NULL,                  -- 视频所属频道 ID（UC...）
    channel_handle  TEXT    DEFAULT NULL,                  -- 视频所属频道 handle（@...）
    title           TEXT    NOT NULL,                      -- 视频标题
    description     TEXT    DEFAULT NULL,                  -- 视频描述快照
    url             TEXT    NOT NULL,                      -- 视频完整访问 URL
    published_at    TEXT    NOT NULL,                      -- YouTube 原始发布时间，ISO8601
    upload_date     TEXT    DEFAULT NULL,                  -- 上传日期，YYYY-MM-DD；部分来源可能为空
    duration_sec    INTEGER DEFAULT NULL,                  -- 视频时长（秒）
    view_count      INTEGER DEFAULT NULL,                  -- 抓取时播放量
    like_count      INTEGER DEFAULT NULL,                  -- 抓取时点赞数
    comment_count   INTEGER DEFAULT NULL,                  -- 抓取时评论数
    thumbnail_url   TEXT    DEFAULT NULL,                  -- 缩略图 URL
    fetched_at      TEXT    NOT NULL,                      -- 首次入库时间，ISO8601
    notify_status   TEXT    NOT NULL DEFAULT 'pending',    -- 通知状态：pending / sent / failed / skipped
    notify_sent_at  TEXT    DEFAULT NULL,                  -- 最近一次通知成功时间
    notify_error    TEXT    DEFAULT NULL,                  -- 最近一次通知失败原因
    download_status TEXT    NOT NULL DEFAULT 'pending',    -- 下载状态：pending / downloading / downloaded / failed
    download_at     TEXT    DEFAULT NULL,                  -- 下载完成时间
    download_path   TEXT    DEFAULT NULL,                  -- 下载到本机后的文件路径
    download_error  TEXT    DEFAULT NULL,                  -- 下载失败原因
    created_at      TEXT    NOT NULL,                      -- 记录创建时间
    FOREIGN KEY (account_id) REFERENCES monitor_accounts(id) ON DELETE CASCADE, -- 删除账户时同步清理视频记录
    FOREIGN KEY (event_id) REFERENCES monitor_events(id) ON DELETE CASCADE       -- 删除扫描事件时同步清理视频记录
);

CREATE INDEX IF NOT EXISTS idx_monitor_videos_account_id ON monitor_videos(account_id);
CREATE INDEX IF NOT EXISTS idx_monitor_videos_event_id   ON monitor_videos(event_id);
CREATE INDEX IF NOT EXISTS idx_monitor_videos_published  ON monitor_videos(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_monitor_videos_notify     ON monitor_videos(notify_status);
CREATE INDEX IF NOT EXISTS idx_videos_account_published  ON monitor_videos(account_id, published_at DESC);

-- ── 应用状态表 ──────────────────────────────────────────────
-- 存储调度器状态和 REST API 认证令牌
CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,                    -- 状态键，如 api_token / webhook_enc_key
    value TEXT NOT NULL                        -- 对应状态值
);

-- ── Webhook 通知记录表 ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitor_notify_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,    -- 通知日志主键
    event_id        INTEGER NOT NULL,                     -- 对应扫描事件 id
    account_id      INTEGER NOT NULL,                     -- 对应监控账户 id
    account_name    TEXT    NOT NULL,                     -- 账户名称快照
    video_count     INTEGER NOT NULL,                     -- 本次通知涉及的视频数量
    platform        TEXT    NOT NULL,                     -- 平台：feishu / dingtalk / wecom
    webhook_url     TEXT    NOT NULL,                     -- 实际使用的 Webhook（可能已脱敏/加密后存储）
    http_status     INTEGER DEFAULT NULL,                 -- Webhook 响应 HTTP 状态码
    response_text   TEXT    DEFAULT NULL,                 -- Webhook 返回体摘要
    sent_at         TEXT    NOT NULL,                     -- 发送尝试时间
    error_message   TEXT    DEFAULT NULL,                 -- 失败原因；成功时通常为空
    FOREIGN KEY (event_id) REFERENCES monitor_events(id) ON DELETE CASCADE -- 删除事件时一并清理通知日志
);

CREATE INDEX IF NOT EXISTS idx_notify_logs_event_id ON monitor_notify_logs(event_id);
CREATE INDEX IF NOT EXISTS idx_notify_logs_sent_at  ON monitor_notify_logs(sent_at DESC);

-- ── 动态代理提供方表 ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dynamic_proxy_providers (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT, -- 提供方主键
    name                      TEXT    NOT NULL,                  -- 提供方显示名称
    enabled                   INTEGER NOT NULL DEFAULT 1,        -- 是否参与路由：0=禁用，1=启用
    billing_tier              TEXT    NOT NULL DEFAULT 'free',   -- 计费层级：free / paid
    adapter_type              TEXT    NOT NULL DEFAULT 'public_feed', -- 适配器类型：public_feed / list_api / rotating_gateway 等
    priority                  INTEGER NOT NULL DEFAULT 100,      -- 路由优先级，越小越优先
    supports_cookies          INTEGER NOT NULL DEFAULT 0,        -- 是否适合携带 Cookie 的下载场景
    supports_auto_download    INTEGER NOT NULL DEFAULT 1,        -- 是否允许用于自动下载
    supports_country_filter   INTEGER NOT NULL DEFAULT 0,        -- 是否支持国家/地区筛选
    supports_sticky_session   INTEGER NOT NULL DEFAULT 0,        -- 是否支持粘性会话
    risk_level                TEXT    NOT NULL DEFAULT 'medium', -- 风险等级：low / medium / high
    notes                     TEXT    DEFAULT NULL,              -- 管理备注
    config_json               TEXT    NOT NULL DEFAULT '{}',     -- 适配器配置 JSON（敏感字段可能加密）
    last_health_status        TEXT    DEFAULT NULL,              -- 最近健康状态：healthy / degraded / down / auth_error 等
    last_health_checked_at    TEXT    DEFAULT NULL,              -- 最近一次健康检查时间
    last_error_message        TEXT    DEFAULT NULL,              -- 最近一次错误摘要
    cooldown_until            TEXT    DEFAULT NULL,              -- 冷却截止时间，未到期前不参与路由
    created_at                TEXT    NOT NULL,                  -- 创建时间
    updated_at                TEXT    NOT NULL,                  -- 最近更新时间
    refresh_interval_minutes  INTEGER NOT NULL DEFAULT 0         -- 自动刷新候选节点的间隔（分钟）；0 表示不定时刷新
);

CREATE INDEX IF NOT EXISTS idx_dpp_enabled_priority ON dynamic_proxy_providers(enabled, priority);
CREATE INDEX IF NOT EXISTS idx_dpp_health ON dynamic_proxy_providers(last_health_status, cooldown_until);
CREATE INDEX IF NOT EXISTS idx_dynamic_proxy_enabled_priority ON dynamic_proxy_providers(enabled, priority);
CREATE INDEX IF NOT EXISTS idx_dynamic_proxy_health ON dynamic_proxy_providers(last_health_status, cooldown_until);

-- ── 动态代理候选节点表 ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS dynamic_proxy_candidates (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT, -- 候选节点主键
    candidate_key               TEXT    NOT NULL UNIQUE,           -- 候选唯一键（通常由 provider + endpoint 组合而成）
    provider_id                 INTEGER NOT NULL,                  -- 来源提供方 id
    protocol                    TEXT    NOT NULL,                  -- 协议：http / https / socks5 / socks4
    host                        TEXT    NOT NULL,                  -- 主机/IP
    port                        INTEGER NOT NULL,                  -- 端口
    username                    TEXT    DEFAULT NULL,              -- 用户名（如有鉴权）
    password_enc                TEXT    DEFAULT NULL,              -- 加密后的密码
    auth_type                   TEXT    NOT NULL DEFAULT 'none',   -- 鉴权类型：none / basic / token ...
    masked_proxy_endpoint       TEXT    NOT NULL,                  -- 脱敏后的 endpoint，用于日志/UI 展示
    country_code                TEXT    DEFAULT NULL,              -- 国家码，如 CN / US
    region                      TEXT    DEFAULT NULL,              -- 省/州/区域
    city                        TEXT    DEFAULT NULL,              -- 城市
    anonymity                   TEXT    DEFAULT NULL,              -- 匿名级别，如 elite / anonymous / transparent
    risk_level                  TEXT    NOT NULL DEFAULT 'medium', -- 风险等级
    supports_https              INTEGER NOT NULL DEFAULT 1,        -- 是否支持 HTTPS 请求
    supports_cookies            INTEGER NOT NULL DEFAULT 0,        -- 是否适合 Cookie 下载
    supports_auto_download      INTEGER NOT NULL DEFAULT 1,        -- 是否允许用于自动下载
    supports_sticky_session     INTEGER NOT NULL DEFAULT 0,        -- 是否支持粘性会话
    latency_ms                  INTEGER DEFAULT NULL,              -- 最近测得延迟（毫秒）
    last_probe_status           TEXT    NOT NULL DEFAULT 'unknown',-- 最近探测状态：healthy / degraded / down / unknown
    last_probe_at               TEXT    DEFAULT NULL,              -- 最近探测时间
    score                       REAL    NOT NULL DEFAULT 0.0,      -- 路由评分，越高越优先
    success_count               INTEGER NOT NULL DEFAULT 0,        -- 探测成功累计次数
    failure_count               INTEGER NOT NULL DEFAULT 0,        -- 探测失败累计次数
    consecutive_failures        INTEGER NOT NULL DEFAULT 0,        -- 连续失败次数
    last_success_at             TEXT    DEFAULT NULL,              -- 最近成功时间
    last_failure_at             TEXT    DEFAULT NULL,              -- 最近失败时间
    last_error_message          TEXT    DEFAULT NULL,              -- 最近失败摘要
    failure_category            TEXT    DEFAULT NULL,              -- 最近失败分类，如 timeout / auth / network
    provider_reference_id       TEXT    DEFAULT NULL,              -- 提供方侧原始节点 id / 引用 id
    ttl_expires_at              TEXT    DEFAULT NULL,              -- 候选过期时间；过期后应清理或刷新
    last_seen_at                TEXT    NOT NULL,                  -- 最近一次从提供方列表中看见该节点的时间
    created_at                  TEXT    NOT NULL,                  -- 首次入库时间
    updated_at                  TEXT    NOT NULL,                  -- 最近更新时间
    FOREIGN KEY (provider_id) REFERENCES dynamic_proxy_providers(id) ON DELETE CASCADE -- 删除提供方时级联删除候选
);

CREATE INDEX IF NOT EXISTS idx_candidates_provider_ttl ON dynamic_proxy_candidates(provider_id, ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_candidates_score        ON dynamic_proxy_candidates(score DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_probe        ON dynamic_proxy_candidates(last_probe_status, ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_candidates_ttl          ON dynamic_proxy_candidates(ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_candidates_key          ON dynamic_proxy_candidates(candidate_key);

-- ── 下载路由决策日志 ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS download_decision_logs (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT, -- 决策日志主键
    account_id             INTEGER,                          -- 关联账户 id；Web 批量下载可为空
    account_name           TEXT,                             -- 账户名称 / Web 批量下载伪名称快照
    video_count            INTEGER,                          -- 本次决策涉及的视频数
    is_auto_download       INTEGER DEFAULT 0,                -- 是否自动下载：0=手动，1=自动
    cookies_present        INTEGER DEFAULT 0,                -- 本次下载是否携带 Cookie
    resolved_proxy_source  TEXT,                             -- 最终命中的代理来源：direct / account_static / system_paid / ...
    resolved_provider_name TEXT,                             -- 命中的动态提供方名称（如有）
    resolved_provider_tier TEXT,                             -- 命中的提供方计费层级（如有）
    resolved_country       TEXT,                             -- 命中的国家/地区（如有）
    resolved_session_mode  TEXT,                             -- 命中的会话模式（如 sticky / rotate）
    fallback_depth         INTEGER DEFAULT 0,                -- 回退层级：0 表示首选命中，>0 表示经历回退
    masked_proxy_endpoint  TEXT,                             -- 脱敏后的代理 endpoint
    decision_reason        TEXT,                             -- 决策说明文本
    warnings               TEXT,                             -- 逗号拼接的警告摘要
    created_at             TEXT    NOT NULL                  -- 决策发生时间
);

CREATE INDEX IF NOT EXISTS idx_ddl_account ON download_decision_logs(account_id);
CREATE INDEX IF NOT EXISTS idx_ddl_created ON download_decision_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_download_decision_account ON download_decision_logs(account_id, created_at DESC);

-- ── 动态代理调度运行日志 ────────────────────────────────────
CREATE TABLE IF NOT EXISTS provider_scheduler_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 调度运行日志主键
    provider_id   INTEGER,                           -- 关联的提供方 id；全局 job 可为空
    provider_name TEXT,                              -- 提供方名称快照
    job_type      TEXT NOT NULL,                     -- 任务类型，如 refresh / cleanup / probe
    status        TEXT NOT NULL,                     -- 运行状态：running / success / error / skipped
    raw_count     INTEGER DEFAULT 0,                 -- 原始候选数量（如 refresh 拉取数量）
    valid_count   INTEGER DEFAULT 0,                 -- 过滤/验证后有效数量
    message       TEXT,                              -- 结果说明 / 错误摘要
    started_at    TEXT NOT NULL,                     -- 开始时间
    finished_at   TEXT,                              -- 结束时间
    duration_ms   INTEGER,                           -- 运行耗时（毫秒）
    FOREIGN KEY (provider_id) REFERENCES dynamic_proxy_providers(id) ON DELETE SET NULL -- 删除提供方后保留日志
);

CREATE INDEX IF NOT EXISTS idx_provider_scheduler_runs_started_at ON provider_scheduler_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_provider_scheduler_runs_provider_id ON provider_scheduler_runs(provider_id, started_at DESC);

-- ── Web 批量下载任务持久化 ─────────────────────────────────
CREATE TABLE IF NOT EXISTS web_batch_tasks (
    task_id           TEXT PRIMARY KEY,              -- Web 批量下载任务 id（同时作为外部 API 标识）
    source_name       TEXT,                          -- 任务来源文件名，如 urls.xlsx
    output_path       TEXT,                          -- 最终下载输出目录
    status            TEXT    NOT NULL,              -- 任务状态：running / cancelling / cancelled / done / error
    total             INTEGER NOT NULL DEFAULT 0,    -- 计划处理的视频总数
    completed         INTEGER NOT NULL DEFAULT 0,    -- 当前已完成处理的视频数（成功+失败）
    success           INTEGER NOT NULL DEFAULT 0,    -- 成功数
    failed            INTEGER NOT NULL DEFAULT 0,    -- 失败数
    current_video     TEXT,                          -- 当前进度文案 / 当前处理视频摘要
    error             TEXT,                          -- 任务级异常信息（若 status=error）
    cancel_requested  INTEGER NOT NULL DEFAULT 0,    -- 是否已请求取消：0=否，1=是
    cancel_message    TEXT,                          -- 取消中 / 已取消文案
    results_json      TEXT    NOT NULL DEFAULT '[]', -- 序列化后的结果列表 JSON（每项含 url/status/info）
    created_at        TEXT    NOT NULL,              -- 创建时间
    finished_at       TEXT,                          -- 结束时间；运行中为空
    updated_at        TEXT    NOT NULL               -- 最近一次状态刷新时间
);

CREATE INDEX IF NOT EXISTS idx_web_batch_tasks_created_at ON web_batch_tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_web_batch_tasks_status ON web_batch_tasks(status, created_at DESC);
