-- 频道元信息缓存（handle → channel_id/uploads_playlist_id）
-- 永久缓存，只在用户手动刷新或频道变更时失效
CREATE TABLE IF NOT EXISTS channel_meta_cache (
    handle             TEXT PRIMARY KEY,          -- 用户输入的 @xxx 或原始 URL（去@后存储）
    channel_id         TEXT NOT NULL,            -- UC-xxxx（永久标识）
    channel_name       TEXT,                     -- 频道名称（实时性低，仅展示用）
    uploads_playlist_id TEXT,                    -- UU-xxxx（永久标识）
    subscriber_count   TEXT,                     -- 订阅数（仅展示用）
    video_count        TEXT,                     -- 视频数（仅展示用）
    description        TEXT,                     -- 频道描述
    cached_at          TEXT NOT NULL             -- ISO8601 缓存时间
);

CREATE INDEX IF NOT EXISTS idx_channel_cache_channel_id ON channel_meta_cache(channel_id);

-- YouTube 频道视频数据库 schema
-- SQLite 兼容

CREATE TABLE IF NOT EXISTS channels (
    channel_id        TEXT PRIMARY KEY,   -- YouTube channel ID (UCxxxx)
    handle            TEXT,               -- @username
    title             TEXT,
    custom_url        TEXT,               -- /c/xxx 或 /user/xxx
    description       TEXT,
    subscriber_count  INTEGER DEFAULT 0,
    playlist_id       TEXT,               -- 上传视频列表的 playlist ID
    fetched_at        TEXT                -- ISO8601 抓取时间
);

CREATE TABLE IF NOT EXISTS videos (
    -- 主键
    id                INTEGER PRIMARY KEY AUTOINCREMENT,

    -- YouTube 固有字段
    video_id          TEXT UNIQUE NOT NULL,
    channel_id        TEXT,
    channel_handle    TEXT,

    -- 基础信息
    title             TEXT,
    description       TEXT,
    url               TEXT,              -- https://www.youtube.com/watch?v=xxx

    -- 时间相关
    published_at      TEXT,               -- ISO8601 原始发布时间
    upload_date       TEXT,               -- YYYY-MM-DD 从 yt-dlp upload_date 填充
    fetched_at        TEXT,               -- ISO8601 首次入库时间

    -- 视频属性
    duration_sec      INTEGER DEFAULT 0,
    width             INTEGER,
    height            INTEGER,
    fps               REAL,
    vcodec            TEXT,              -- 视频编码
    acodec            TEXT,              -- 音频编码
    filesize          INTEGER,            -- 字节
    resolution        TEXT,               -- e.g. "1920x1080"

    -- 热度数据
    view_count        INTEGER DEFAULT 0,
    like_count        INTEGER,
    dislike_count     INTEGER,
    average_rating    REAL,

    -- 字幕/语言
    has_subtitle      INTEGER DEFAULT 0,  -- 0/1
    subtitle_langs    TEXT,               -- 逗号分隔语言码

    -- 下载状态
    download_status   TEXT DEFAULT 'pending',  -- pending|downloading|completed|failed|skipped
    download_path     TEXT,               -- 本地文件路径
    download_at       TEXT,               -- ISO8601 下载完成时间
    download_error    TEXT,               -- 失败原因
    download_retries  INTEGER DEFAULT 0,

    -- 字幕文件
    subtitle_path     TEXT,
    subtitle_lang      TEXT,

    -- 数据质量标记
    upload_date_fetched_at TEXT,          -- upload_date 从 yt-dlp 抓回的时间
    data_freshness    TEXT DEFAULT 'partial',  -- partial(无upload_date)|full

    -- 时间戳
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now')),

    -- 外键
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_videos_channel_id   ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_status       ON videos(download_status);
CREATE INDEX IF NOT EXISTS idx_videos_upload_date  ON videos(upload_date);
CREATE INDEX IF NOT EXISTS idx_videos_view_count   ON videos(view_count DESC);
CREATE INDEX IF NOT EXISTS idx_videos_duration     ON videos(duration_sec);
CREATE INDEX IF NOT EXISTS idx_videos_fetched_at   ON videos(fetched_at);
CREATE INDEX IF NOT EXISTS idx_videos_data_freshness ON videos(data_freshness);

-- 视频去重（同一 video_id 不重复入库）
-- UNIQUE(video_id) 已在上表定义

-- 下载历史（每次下载尝试记录一条）
CREATE TABLE IF NOT EXISTS download_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id          TEXT NOT NULL,
    url               TEXT,
    started_at        TEXT DEFAULT (datetime('now')),
    completed_at      TEXT,
    duration_sec      INTEGER,
    file_size         INTEGER,
    file_path         TEXT,
    error_message     TEXT,
    proxy_used        TEXT,
    success           INTEGER DEFAULT 0,  -- 0/1
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE INDEX IF NOT EXISTS idx_history_video_id ON download_history(video_id);

-- 频道视频批量任务记录
CREATE TABLE IF NOT EXISTS fetch_tasks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id        TEXT,
    channel_url       TEXT NOT NULL,
    started_at        TEXT DEFAULT (datetime('now')),
    completed_at      TEXT,
    total_videos      INTEGER DEFAULT 0,
    upload_dates_filled INTEGER DEFAULT 0,
    status            TEXT DEFAULT 'running',  -- running|completed|failed
    error_message     TEXT
);
