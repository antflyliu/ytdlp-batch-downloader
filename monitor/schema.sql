-- ============================================================
-- YouTube Monitor 数据库 Schema
-- 文件: monitor/schema.sql
-- 说明: 与 yt_channel_fetch 的 videos.db 完全独立
--       仅记录监控发现的新视频事件，不干预下载数据
-- ============================================================

-- ── YouTube API Key 配置表 ───────────────────────────────
-- 存储多个 API Key，支持配额追踪和账户分配
CREATE TABLE IF NOT EXISTS api_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key_value       TEXT    NOT NULL UNIQUE,   -- 实际的 API Key 值（敏感）
    name            TEXT    NOT NULL,          -- 显示名称，如 "Key-1"
    daily_quota     INTEGER NOT NULL DEFAULT 10000,  -- 该 Key 的每日配额上限
    quota_used      INTEGER NOT NULL DEFAULT 0, -- 今日已用配额单位数
    quota_reset_at  TEXT    NOT NULL,          -- 配额重置日期 (YYYY-MM-DD)
    is_active       INTEGER NOT NULL DEFAULT 1, -- 0=禁用 1=启用
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(is_active);

-- ── IP 代理池表 ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS proxy_pools (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,          -- 显示名称，如"代理池-1"
    proxy_url   TEXT    NOT NULL,          -- 代理地址，如 http://user:pass@host:port
    enabled     INTEGER NOT NULL DEFAULT 1, -- 0=禁用 1=启用
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proxy_pools_enabled ON proxy_pools(enabled);

-- ── 监控账户配置表 ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitor_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,          -- 显示名称，如"综艺Show"
    channel_url     TEXT    NOT NULL,          -- @C-HitShow / UCxxxx / https://...
    api_key_id      INTEGER DEFAULT NULL,       -- 关联 api_keys.id（优先级高于 api_key_env）
    api_key_env     TEXT    NOT NULL,           -- 兼容旧数据：环境变量名，如 "YOUTUBE_Data_API_V3"
    proxy_pool_id   INTEGER DEFAULT NULL,       -- 关联 proxy_pools.id（启用时使用）
    proxy_enabled   INTEGER NOT NULL DEFAULT 0, -- 0=不使用代理 1=使用代理
    fetch_mode      TEXT    NOT NULL DEFAULT 'playlist',  -- 'search' | 'playlist'
    fetch_limit     INTEGER NOT NULL DEFAULT 5, -- 每次扫描获取的视频条数
    scan_interval   INTEGER NOT NULL DEFAULT 5, -- 扫描间隔（分钟）
    enabled         INTEGER NOT NULL DEFAULT 1, -- 0=禁用 1=启用
    notify_enabled  INTEGER NOT NULL DEFAULT 1, -- 0=不通知 1=通知
    notify_platform TEXT    NOT NULL DEFAULT 'feishu',  -- feishu | dingtalk | wecom
    webhook_url     TEXT    DEFAULT NULL,       -- 各平台 Webhook URL（优先级最高）
    feishu_message_mode TEXT NOT NULL DEFAULT 'card_json',  -- card_json | template
    feishu_template_id  TEXT DEFAULT NULL,  -- 飞书卡片模板ID（template模式用）
    feishu_scan_template_id TEXT DEFAULT NULL,  -- 扫描确认模板ID（template模式用）
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE SET NULL,
    FOREIGN KEY (proxy_pool_id) REFERENCES proxy_pools(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_channel_url ON monitor_accounts(channel_url);

-- ── 扫描事件表 ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitor_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL,
    account_name    TEXT    NOT NULL,           -- 反规范化，便于查询
    scan_started_at TEXT    NOT NULL,           -- ISO8601 扫描开始时间
    scan_ended_at   TEXT    DEFAULT NULL,       -- ISO8601 扫描结束时间
    status          TEXT    NOT NULL DEFAULT 'running',  -- running|success|error|skipped
    total_videos    INTEGER NOT NULL DEFAULT 0, -- API 返回的视频总数
    new_videos      INTEGER NOT NULL DEFAULT 0, -- 新增视频数（不在 monitor_videos 表中）
    error_message   TEXT    DEFAULT NULL,
    duration_ms     INTEGER DEFAULT NULL,       -- 扫描耗时（毫秒）
    FOREIGN KEY (account_id) REFERENCES monitor_accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_account_id ON monitor_events(account_id);
CREATE INDEX IF NOT EXISTS idx_events_started ON monitor_events(scan_started_at DESC);

-- ── 监控视频详情表 ───────────────────────────────────────
-- 字段设计参考 videos 表，但加上监控特有的 source/status 标注
CREATE TABLE IF NOT EXISTS monitor_videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        TEXT    NOT NULL UNIQUE,    -- YouTube video ID (11位)
    account_id      INTEGER NOT NULL,
    event_id        INTEGER NOT NULL,            -- 关联的 monitor_events.id
    channel_id      TEXT    DEFAULT NULL,        -- YouTube 频道 ID
    channel_handle  TEXT    DEFAULT NULL,       -- @username
    title           TEXT    NOT NULL,
    description     TEXT    DEFAULT NULL,
    url             TEXT    NOT NULL,
    published_at    TEXT    NOT NULL,           -- ISO8601 原始发布时间
    upload_date     TEXT    DEFAULT NULL,       -- YYYY-MM-DD 格式
    duration_sec    INTEGER DEFAULT NULL,
    view_count      INTEGER DEFAULT NULL,
    like_count      INTEGER DEFAULT NULL,
    comment_count   INTEGER DEFAULT NULL,
    thumbnail_url   TEXT    DEFAULT NULL,
    fetched_at      TEXT    NOT NULL,           -- 首次入库时间
    notify_status   TEXT    NOT NULL DEFAULT 'pending',  -- pending|sent|failed|skipped
    notify_sent_at  TEXT    DEFAULT NULL,       -- 飞书通知发送时间
    notify_error    TEXT    DEFAULT NULL,       -- 通知失败原因
    download_status TEXT    NOT NULL DEFAULT 'pending',    -- pending|downloaded|failed
    download_at     TEXT    DEFAULT NULL,        -- 下载完成时间
    download_path   TEXT    DEFAULT NULL,       -- 本地文件路径
    download_error  TEXT    DEFAULT NULL,        -- 下载失败原因
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (account_id) REFERENCES monitor_accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (event_id) REFERENCES monitor_events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_monitor_videos_account_id ON monitor_videos(account_id);
CREATE INDEX IF NOT EXISTS idx_monitor_videos_event_id   ON monitor_videos(event_id);
CREATE INDEX IF NOT EXISTS idx_monitor_videos_published  ON monitor_videos(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_monitor_videos_notify     ON monitor_videos(notify_status);

-- ── 应用状态表 ──────────────────────────────────────────────
-- 存储调度器状态和 REST API 认证令牌
CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ── Webhook 通知记录表 ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitor_notify_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL,
    account_id      INTEGER NOT NULL,
    account_name    TEXT    NOT NULL,
    video_count     INTEGER NOT NULL,
    platform        TEXT    NOT NULL,          -- feishu | dingtalk | wecom
    webhook_url     TEXT    NOT NULL,          -- 实际使用的 Webhook URL
    http_status     INTEGER DEFAULT NULL,
    response_text   TEXT    DEFAULT NULL,
    sent_at         TEXT    NOT NULL,
    error_message   TEXT    DEFAULT NULL,
    FOREIGN KEY (event_id) REFERENCES monitor_events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notify_logs_event_id ON monitor_notify_logs(event_id);
CREATE INDEX IF NOT EXISTS idx_notify_logs_sent_at  ON monitor_notify_logs(sent_at DESC);

-- ── 动态代理候选节点表 ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS dynamic_proxy_candidates (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_key               TEXT    NOT NULL UNIQUE,
    provider_id                 INTEGER NOT NULL,
    protocol                    TEXT    NOT NULL,
    host                        TEXT    NOT NULL,
    port                        INTEGER NOT NULL,
    username                    TEXT    DEFAULT NULL,
    password_enc                TEXT    DEFAULT NULL,
    auth_type                   TEXT    NOT NULL DEFAULT 'none',
    masked_proxy_endpoint       TEXT    NOT NULL,
    country_code                TEXT    DEFAULT NULL,
    region                      TEXT    DEFAULT NULL,
    city                        TEXT    DEFAULT NULL,
    anonymity                   TEXT    DEFAULT NULL,
    risk_level                  TEXT    NOT NULL DEFAULT 'medium',
    supports_https              INTEGER NOT NULL DEFAULT 1,
    supports_cookies            INTEGER NOT NULL DEFAULT 0,
    supports_auto_download      INTEGER NOT NULL DEFAULT 1,
    supports_sticky_session     INTEGER NOT NULL DEFAULT 0,
    latency_ms                  INTEGER DEFAULT NULL,
    last_probe_status           TEXT    NOT NULL DEFAULT 'unknown',
    last_probe_at               TEXT    DEFAULT NULL,
    score                       REAL    NOT NULL DEFAULT 0.0,
    success_count               INTEGER NOT NULL DEFAULT 0,
    failure_count               INTEGER NOT NULL DEFAULT 0,
    consecutive_failures        INTEGER NOT NULL DEFAULT 0,
    last_success_at             TEXT    DEFAULT NULL,
    last_failure_at             TEXT    DEFAULT NULL,
    last_error_message          TEXT    DEFAULT NULL,
    failure_category            TEXT    DEFAULT NULL,
    provider_reference_id       TEXT    DEFAULT NULL,
    ttl_expires_at              TEXT    DEFAULT NULL,
    last_seen_at                TEXT    NOT NULL,
    created_at                  TEXT    NOT NULL,
    updated_at                  TEXT    NOT NULL,
    FOREIGN KEY (provider_id) REFERENCES dynamic_proxy_providers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_candidates_provider_ttl ON dynamic_proxy_candidates(provider_id, ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_candidates_score        ON dynamic_proxy_candidates(score DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_probe        ON dynamic_proxy_candidates(last_probe_status, ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_candidates_ttl          ON dynamic_proxy_candidates(ttl_expires_at);
CREATE INDEX IF NOT EXISTS idx_candidates_key          ON dynamic_proxy_candidates(candidate_key);
