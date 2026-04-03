-- ============================================================
-- YouTube Monitor 数据库 Schema
-- 文件: monitor/schema.sql
-- 说明: 与 yt_channel_fetch 的 videos.db 完全独立
--       仅记录监控发现的新视频事件，不干预下载数据
-- ============================================================

-- ── 监控账户配置表 ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitor_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,          -- 显示名称，如"综艺Show"
    channel_url     TEXT    NOT NULL,          -- @C-HitShow / UCxxxx / https://...
    api_key_env     TEXT    NOT NULL,           -- 环境变量名，如 "YOUTUBE_Data_API_V3"
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
    updated_at      TEXT    NOT NULL
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
