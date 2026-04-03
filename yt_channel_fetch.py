#!/usr/bin/env python3
"""
YouTube 频道视频批量获取工具
导出频道视频链接列表到 CSV 或 SQLite

用法:
    python yt_channel_fetch.py -c "https://www.youtube.com/@channel" -o output.csv
    python yt_channel_fetch.py -c "https://www.youtube.com/@channel" -o output.db --format sqlite
"""

import pandas as pd
import argparse
import sys
import os
import sqlite3
import subprocess
import time
import logging_config

_log = logging_config.get_logger("yt_channel_fetch")
import threading
import concurrent.futures
import re
from datetime import datetime


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def parse_duration(duration_str):
    if not duration_str:
        return 0
    try:
        parts = duration_str.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return int(parts[0])
    except Exception:
        return 0


def parse_date(date_str):
    if not date_str:
        return None
    for fmt in ['%Y%m%d', '%Y-%m-%d', '%Y/%m/%d', '%d.%m.%Y']:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def parse_min_duration(duration_str):
    if not duration_str:
        return 0
    total = 0
    h = re.findall(r'(\d+)h', duration_str)
    m = re.findall(r'(\d+)m', duration_str)
    s = re.findall(r'(\d+)s', duration_str)
    if h: total += int(h[0]) * 3600
    if m: total += int(m[0]) * 60
    if s: total += int(s[0])
    return total


def _extract_channel_name(channel_url):
    """从频道 URL 中提取频道标识"""
    m = re.search(r'/@([\w]+)', channel_url)
    if m: return m.group(1)
    m = re.search(r'/channel/([\w-]+)', channel_url)
    if m: return m.group(1)
    m = re.search(r'/c/([\w]+)', channel_url)
    if m: return m.group(1)
    m = re.search(r'/user/([\w]+)', channel_url)
    if m: return m.group(1)
    return 'channel'


# ---------------------------------------------------------------------------
# SQLite 数据库操作
# ---------------------------------------------------------------------------

def init_db(db_path):
    """初始化 SQLite 数据库，创建表结构"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id        TEXT PRIMARY KEY,
            handle            TEXT,
            title             TEXT,
            description       TEXT,
            subscriber_count  INTEGER DEFAULT 0,
            playlist_id       TEXT,
            fetched_at        TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id              TEXT,          -- YouTube 视频ID（平台专用，非唯一）
            channel_id            TEXT,
            channel_handle        TEXT,
            title                 TEXT,
            description           TEXT,
            url                   TEXT UNIQUE NOT NULL,  -- 全平台唯一标识
            published_at          TEXT,
            upload_date           TEXT,
            fetched_at            TEXT,
            duration_sec          INTEGER DEFAULT 0,
            width                 INTEGER,
            height                INTEGER,
            resolution            TEXT,
            vcodec               TEXT,
            acodec               TEXT,
            filesize             INTEGER,
            view_count           INTEGER DEFAULT 0,
            like_count           INTEGER,
            dislike_count        INTEGER,
            average_rating       REAL,
            has_subtitle         INTEGER DEFAULT 0,
            subtitle_langs       TEXT,
            download_status      TEXT DEFAULT 'pending',
            download_path         TEXT,
            download_at          TEXT,
            download_error       TEXT,
            download_retries     INTEGER DEFAULT 0,
            subtitle_path         TEXT,
            subtitle_lang         TEXT,
            upload_date_fetched_at TEXT,
            data_freshness       TEXT DEFAULT 'partial',
            created_at            TEXT DEFAULT (datetime('now')),
            updated_at            TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS download_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id      TEXT NOT NULL,
            url           TEXT,
            started_at    TEXT DEFAULT (datetime('now')),
            completed_at  TEXT,
            duration_sec  INTEGER,
            file_size     INTEGER,
            file_path     TEXT,
            error_message TEXT,
            proxy_used    TEXT,
            success       INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_tasks (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id            TEXT,
            channel_url           TEXT NOT NULL,
            started_at            TEXT DEFAULT (datetime('now')),
            completed_at          TEXT,
            total_videos          INTEGER DEFAULT 0,
            upload_dates_filled   INTEGER DEFAULT 0,
            status                TEXT DEFAULT 'running',
            error_message         TEXT
        )
    """)
    for idx in [
        "CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(download_status)",
        "CREATE INDEX IF NOT EXISTS idx_videos_upload_date ON videos(upload_date)",
        "CREATE INDEX IF NOT EXISTS idx_videos_view_count ON videos(view_count DESC)",
        "CREATE INDEX IF NOT EXISTS idx_videos_duration ON videos(duration_sec)",
        "CREATE INDEX IF NOT EXISTS idx_videos_fetched_at ON videos(fetched_at)",
        "CREATE INDEX IF NOT EXISTS idx_videos_freshness ON videos(data_freshness)",
        "CREATE INDEX IF NOT EXISTS idx_history_video_id ON download_history(video_id)",
    ]:
        conn.execute(idx)
    conn.commit()
    _log.info(f"数据库初始化完成: {db_path}")
    return conn
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id        TEXT PRIMARY KEY,
            handle            TEXT,
            title             TEXT,
            description       TEXT,
            subscriber_count  INTEGER DEFAULT 0,
            playlist_id       TEXT,
            fetched_at        TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id              TEXT,          -- YouTube 视频ID（平台专用，非唯一）
            channel_id            TEXT,
            channel_handle        TEXT,
            title                 TEXT,
            description           TEXT,
            url                   TEXT UNIQUE NOT NULL,  -- 全平台唯一标识
            published_at          TEXT,
            upload_date           TEXT,
            fetched_at            TEXT,
            duration_sec          INTEGER DEFAULT 0,
            width                 INTEGER,
            height                INTEGER,
            resolution            TEXT,
            vcodec               TEXT,
            acodec               TEXT,
            filesize             INTEGER,
            view_count           INTEGER DEFAULT 0,
            like_count           INTEGER,
            dislike_count        INTEGER,
            average_rating       REAL,
            has_subtitle         INTEGER DEFAULT 0,
            subtitle_langs       TEXT,
            download_status      TEXT DEFAULT 'pending',
            download_path         TEXT,
            download_at          TEXT,
            download_error       TEXT,
            download_retries     INTEGER DEFAULT 0,
            subtitle_path        TEXT,
            subtitle_lang        TEXT,
            upload_date_fetched_at TEXT,
            data_freshness       TEXT DEFAULT 'partial',
            created_at            TEXT DEFAULT (datetime('now')),
            updated_at            TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS download_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id      TEXT NOT NULL,
            url           TEXT,
            started_at    TEXT DEFAULT (datetime('now')),
            completed_at  TEXT,
            duration_sec  INTEGER,
            file_size     INTEGER,
            file_path     TEXT,
            error_message TEXT,
            proxy_used    TEXT,
            success       INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_tasks (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id            TEXT,
            channel_url           TEXT NOT NULL,
            started_at            TEXT DEFAULT (datetime('now')),
            completed_at          TEXT,
            total_videos          INTEGER DEFAULT 0,
            upload_dates_filled   INTEGER DEFAULT 0,
            status                TEXT DEFAULT 'running',
            error_message         TEXT
        )
    """)
    for idx in [
        "CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(download_status)",
        "CREATE INDEX IF NOT EXISTS idx_videos_upload_date ON videos(upload_date)",
        "CREATE INDEX IF NOT EXISTS idx_videos_view_count ON videos(view_count DESC)",
        "CREATE INDEX IF NOT EXISTS idx_videos_duration ON videos(duration_sec)",
        "CREATE INDEX IF NOT EXISTS idx_videos_fetched_at ON videos(fetched_at)",
        "CREATE INDEX IF NOT EXISTS idx_videos_freshness ON videos(data_freshness)",
        "CREATE INDEX IF NOT EXISTS idx_history_video_id ON download_history(video_id)",
    ]:
        conn.execute(idx)
    conn.commit()
    return conn


def save_videos_to_sqlite(videos, channel_url, db_path, channel_handle=''):
    """
    将视频数据写入统一 SQLite 数据库。
    新视频 INSERT；已存在的视频（同一 video_id）仅更新 metadata，不覆盖 download_status。
    返回 task_id
    """
    conn = init_db(db_path)
    now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    conn.execute(
        "INSERT INTO fetch_tasks (channel_url, status, started_at) VALUES (?, 'running', ?)",
        (channel_url, now)
    )
    task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    inserted = 0
    updated = 0
    for v in videos:
        url      = v.get('url', '') or v.get('URL', '')
        video_id = v.get('视频ID', '')  # YouTube 专用，保留
        title    = v.get('标题', '')
        duration = v.get('时长(秒)', 0)
        views    = v.get('播放量', 0)

        if not url:
            continue

        conn.execute(
            """INSERT OR IGNORE INTO videos
            (video_id, channel_id, channel_handle, title, url,
             published_at, upload_date, fetched_at, duration_sec,
             view_count, data_freshness, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (video_id, channel_handle, channel_handle, title, url,
             '', '', now, duration, views, 'partial', now, now)
        )
        if conn.total_changes > 0:
            inserted += 1
        else:
            conn.execute(
                """UPDATE videos SET
                    channel_id=?, channel_handle=?,
                    title=?, fetched_at=?, duration_sec=?, view_count=?,
                    data_freshness='partial', updated_at=?
                WHERE url=?""",
                (channel_handle, channel_handle, title,
                 now, duration, views, now, url)
            )
            updated += 1

    conn.execute(
        "UPDATE fetch_tasks SET total_videos=? WHERE id=?",
        (inserted, task_id)
    )
    conn.commit()
    conn.close()
    _log.info(f"SQLite写入: 频道={channel_url} 新增={inserted} 更新={updated} DB={db_path}")
    print(f"已写入 {inserted} 个（新增），更新 {updated} 个（已存在）到: {db_path}")
    return task_id

def update_upload_dates_in_db(db_path, urls=None, progress_callback=None):
    """
    Phase2: 从数据库获取 upload_date。

    参数:
        db_path:             SQLite 数据库路径
        urls:               要更新的视频 URL 列表（None = 所有 upload_date 为空的视频）
        progress_callback:   进度回调 (done, total) -> None
    返回: 成功更新的视频数量
    """

    conn = sqlite3.connect(db_path)

    if urls is not None:
        if not urls:
            print("没有指定要补全的视频")
            conn.close()
            return 0
        placeholders = ",".join("?" * len(urls))
        rows = conn.execute(
            f"SELECT id, url FROM videos WHERE url IN ({placeholders}) "
            f"AND (upload_date IS NULL OR upload_date='')",
            urls
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, url FROM videos WHERE upload_date IS NULL OR upload_date=''"
        ).fetchall()

    if not rows:
        conn.close()
        return 0

    total = len(rows)
    upload_dates = {}
    lock = threading.Lock()
    done = [0]
    failed = []   # (video_url, reason) for diagnostics
    workers = min(5, total)

    def _fetch_one(row_id, video_url):
        """获取单个视频的 upload_date。video_url 支持任意平台 URL。"""
        # 从 URL 提取 YouTube 视频 ID（仅 YouTube 平台）
        vid = None
        if 'youtube.com' in video_url or 'youtu.be' in video_url:
            m = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', video_url)
            if not m:
                m = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', video_url)
            if m:
                vid = m.group(1)

        if not vid:
            with lock:
                done[0] += 1
            return

        for attempt in range(4):   # 最多 4 次尝试（含 1 次初始 + 3 次退避重试）
            try:
                r = subprocess.run(
                    ['yt-dlp', '--no-warnings', '--print', '%(upload_date)s',
                     f'https://www.youtube.com/watch?v={vid}'],
                    capture_output=True, text=True, timeout=45,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                date_str = r.stdout.strip()
                stderr_str = r.stderr.strip()

                # YouTube 限速 / 不可用时 yt-dlp 输出 warning 或 "false"
                if date_str in ('NA', 'None', '', 'false') or not date_str:
                    reason = 'no_upload_date'
                elif len(date_str) == 8 and date_str.isdigit():
                    # 正常：8位数字如 20180202 → 转为 YYYY-MM-DD
                    date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                    with lock:
                        upload_dates[video_url] = date_str
                    with lock:
                        done[0] += 1
                    if progress_callback and done[0] % 10 == 0:
                        progress_callback(done[0], total)
                    return
                else:
                    # 意外输出（非标准日期格式）
                    reason = f'unexpected_output:{date_str[:30]}'

                # 非最终重试：检测到问题，等待后重试
                if attempt < 3:
                    wait = (attempt + 1) * 8   # 8s / 16s / 24s 退避
                    # 429 = Too Many Requests 的典型特征
                    if '429' in stderr_str or 'rate' in stderr_str.lower():
                        wait = (attempt + 1) * 15
                    time.sleep(wait)
                    continue

                # 4 次都失败
                with lock:
                    failed.append((video_url, reason or 'timeout'))

            except subprocess.TimeoutExpired:
                if attempt < 3:
                    wait = (attempt + 1) * 12
                    time.sleep(wait)
                    continue
                with lock:
                    failed.append((video_url, 'timeout'))
            except Exception as e:
                if attempt < 3:
                    time.sleep((attempt + 1) * 8)
                    continue
                with lock:
                    failed.append((video_url, f'error:{e}'))

        with lock:
            done[0] += 1
        if progress_callback and done[0] % 10 == 0:
            progress_callback(done[0], total)

    print(f"Phase2: 正在获取 {total} 个视频的上传日期（{workers} 并行线程）...")
    _log.info(f"Phase2开始: DB={db_path} 总数={total} 并行={workers}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda r: _fetch_one(*r), rows))

    now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    for video_url, date_str in upload_dates.items():
        conn.execute(
            "UPDATE videos SET upload_date=?, upload_date_fetched_at=?, "
            "data_freshness='full', updated_at=? WHERE url=?",
            (date_str, now, now, video_url)
        )

    conn.execute(
        "UPDATE fetch_tasks SET upload_dates_filled=?, status='completed', completed_at=? "
        "WHERE id=(SELECT id FROM fetch_tasks ORDER BY id DESC LIMIT 1)",
        (len(upload_dates), now)
    )
    conn.commit()
    conn.close()

    filled = len(upload_dates)
    print(f"Phase2完成: 已填充 {filled}/{total} 个上传日期")
    _log.info(f"Phase2完成: DB={db_path} 成功={filled}/{total} 失败={len(failed)}")
    if failed:
        print(f"  失败 {len(failed)} 个（原因: timeout/无日期/网络错误）:")
        for url, reason in failed[:5]:
            print(f"    {url[:60]} → {reason}")
        _log.warning(f"Phase2失败列表({len(failed)}): " + "; ".join(f"{u[:40]}→{r}" for u, r in failed[:10]))
        if len(failed) > 5:
            print(f"    ... 还有 {len(failed)-5} 个")

    if progress_callback:
        progress_callback(total, total)
    return filled

def get_urls_from_sqlite(db_path, limit=None):
    """从 SQLite 读取视频 URL 列表"""
    conn = sqlite3.connect(db_path)
    if limit:
        rows = conn.execute(
            "SELECT url FROM videos ORDER BY upload_date DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT url FROM videos ORDER BY upload_date DESC"
        ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_video_count(db_path):
    """从 SQLite 读取视频总数"""
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT COUNT(*) FROM videos").fetchone()
    conn.close()
    return row[0] if row else 0


def get_upload_date_count(db_path):
    """从 SQLite 读取已有 upload_date 的视频数量"""
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT COUNT(*) FROM videos WHERE upload_date IS NOT NULL AND upload_date!=''"
    ).fetchone()
    conn.close()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# 核心抓取函数
# ---------------------------------------------------------------------------

def fetch_channel_videos(channel_url, max_videos=None, save_format='csv', save_dir=None,
                          background_update=True, progress_callback=None):
    """
    获取频道视频，两阶段执行。

    小频道（<=50个视频）：yt-dlp 全量 extractor 一次拉取，包含 upload_date。
    大频道（>50个视频）：--flat-playlist 快速获取视频列表，并行补全 upload_date。

    参数:
        channel_url:        频道 URL
        max_videos:         最多获取数量（None=全部）
        save_format:        'csv' 或 'sqlite'
        save_dir:           保存目录（默认当前目录）
        background_update:   Phase2 是否后台运行（True=立即返回）
        progress_callback:   进度回调 (done, total) -> None

    返回:
        (videos, storage_path, upload_date_count)
        videos:         视频列表 dict
        storage_path:   CSV 或 SQLite 文件路径
        upload_date_count: Phase1 中已有的 upload_date 数量
    """

    SMALL_CHANNEL_THRESHOLD = 50

    if save_dir is None:
        save_dir = os.getcwd()

    print(f"正在获取频道视频列表: {channel_url}")

    # 规范化 URL
    fetch_url = channel_url
    if '@' in channel_url and '/videos' not in channel_url and '/shorts' not in channel_url:
        fetch_url = channel_url.rstrip('/') + '/videos'

    channel_name = _extract_channel_name(channel_url)
    sep = '>>>'
    print_fmt = f"%(title)s{sep}%(id)s{sep}%(duration)s{sep}%(view_count)s"

    # Step 1: 快速扫描获取全部视频 ID（flat-playlist，无 upload_date）
    cmd_flat = [
        'yt-dlp', '--flat-playlist', '--no-warnings',
        '--playlist-reverse',
        '--print', print_fmt, fetch_url,
    ]
    if max_videos:
        cmd_flat.extend(['--playlist-end', str(max_videos)])

    try:
        result = subprocess.run(
            cmd_flat, capture_output=True, text=True,
            encoding='utf-8', stdin=subprocess.DEVNULL,
            timeout=600, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0 and not result.stdout.strip():
            print(f"错误：yt-dlp 返回码 {result.returncode}")
            if result.stderr:
                print(f"  STDERR: {result.stderr.strip()}")
            return [], None, 0
    except subprocess.TimeoutExpired:
        print("错误：获取频道视频超时（600秒）")
        return [], None, 0
    except FileNotFoundError:
        print("错误：找不到 yt-dlp，请确保已安装并在 PATH 中")
        return [], None, 0
    except Exception as e:
        print(f"错误：{e}")
        return [], None, 0

    # 解析 flat-playlist 输出
    videos = []
    video_ids = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(sep)
        if len(parts) < 4:
            continue
        title, video_id, duration_raw, view_raw = parts[0], parts[1], parts[2], parts[3]
        try:
            duration_sec = int(float(duration_raw)) if duration_raw not in ('', 'NA', 'None') else 0
        except (ValueError, TypeError):
            duration_sec = 0
        try:
            view_count = int(view_raw) if view_raw not in ('', 'NA', 'None') else 0
        except (ValueError, TypeError):
            view_count = 0

        videos.append({
            '标题': title or 'Unknown',
            'URL': f"https://www.youtube.com/watch?v={video_id}",
            '视频ID': video_id,
            '上传日期': '',
            '时长(秒)': duration_sec,
            '播放量': view_count,
        })
        video_ids.append(video_id)

    if not videos:
        print("未获取到任何视频，请检查频道 URL 是否正确")
        _log.warning(f"频道视频获取为空: {channel_url}")
        return [], None, 0

    video_count = len(videos)
    print(f"扫描完成：发现 {video_count} 个视频")

    # ---------- 分叉：小频道全量拉取，大频道并行补全 ----------
    upload_date_count = 0
    if video_count <= SMALL_CHANNEL_THRESHOLD:
        # 小频道：全量 extractor 一次拉取（包含 upload_date）
        print(f"小频道（{video_count}个），使用全量 extractor...")
        sep2 = '>>>'
        full_fmt = f"%(title)s{sep2}%(id)s{sep2}%(duration)s{sep2}%(view_count)s{sep2}%(upload_date)s"
        cmd_full = [
            'yt-dlp', '--no-warnings',
            '--playlist-reverse',
            '--print', full_fmt, fetch_url,
        ]
        if max_videos:
            cmd_full.extend(['--playlist-end', str(max_videos)])

        try:
            result2 = subprocess.run(
                cmd_full, capture_output=True, text=True,
                encoding='utf-8', stdin=subprocess.DEVNULL,
                timeout=600, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result2.returncode == 0 and result2.stdout.strip():
                # 重解析，用 full_fmt 替换 videos 列表
                new_videos = []
                for line in result2.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(sep2)
                    if len(parts) < 5:
                        continue
                    title, vid, dur_raw, view_raw, date_raw = (parts[0], parts[1], parts[2], parts[3], parts[4])
                    try:
                        dur_sec = int(float(dur_raw)) if dur_raw not in ('', 'NA', 'None') else 0
                    except (ValueError, TypeError):
                        dur_sec = 0
                    try:
                        vcnt = int(view_raw) if view_raw not in ('', 'NA', 'None') else 0
                    except (ValueError, TypeError):
                        vcnt = 0
                    # 格式化日期 YYYYMMDD → YYYY-MM-DD
                    upload_date = ''
                    if date_raw and len(date_raw) == 8 and date_raw.isdigit():
                        upload_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
                        upload_date_count += 1

                    new_videos.append({
                        '标题': title or 'Unknown',
                        'URL': f"https://www.youtube.com/watch?v={vid}",
                        '视频ID': vid,
                        '上传日期': upload_date,
                        '时长(秒)': dur_sec,
                        '播放量': vcnt,
                    })
                if new_videos:
                    videos = new_videos
                    video_ids = [v['视频ID'] for v in videos]
        except Exception as e:
            print(f"  全量 extractor 失败，继续使用 flat 数据: {e}")

    print(f"Phase1完成：{len(videos)} 个视频（已含 {upload_date_count} 个上传日期）")
    _log.info(f"Phase1完成: 频道={channel_url} 视频数={len(videos)} 上传日期={upload_date_count}")

    # ---------- 保存（Phase1 后立即）----------
    if save_format == 'sqlite':
        db_path = os.path.join(save_dir, "ytdl_videos.db")
        save_videos_to_sqlite(videos, channel_url, db_path, channel_name)
        storage_path = db_path
    else:
        # CSV 模式：小频道已有 upload_date（full extractor），大频道才并行补全
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(save_dir, f"{channel_name}_videos_{ts}.csv")
        csv_upload_date_count = 0
        if upload_date_count == 0 and videos:
            print(f"正在获取 {len(videos)} 个视频的上传日期...")
            upload_dates = fetch_upload_dates_for_videos(videos, progress_callback)
            for v in videos:
                date = upload_dates.get(v.get('URL', ''), '')
                v['上传日期'] = date
                if date:
                    csv_upload_date_count += 1
        upload_date_count = upload_date_count or csv_upload_date_count
        export_to_csv(videos, csv_path)
        storage_path = csv_path

    # ---------- Phase 2（仅 SQLite + background）----------
    if save_format == 'sqlite' and background_update and video_ids:
        def bg_worker():
            update_upload_dates_in_db(storage_path, progress_callback)
        t = threading.Thread(target=bg_worker, daemon=True)
        t.start()
    elif save_format == 'sqlite' and not background_update and video_ids:
        update_upload_dates_in_db(storage_path, progress_callback)

    return videos, storage_path, upload_date_count


# ---------------------------------------------------------------------------
# 批量获取视频上传日期（供 CSV 模式使用）
# ---------------------------------------------------------------------------

def fetch_upload_dates_for_videos(videos, progress_callback=None):
    """
    并行获取视频列表的上传日期，返回 {url: 'YYYY-MM-DD'} 字典。
    仅处理 YouTube 视频，跳过其他平台 URL。
    """
    # 提取 YouTube 视频 ID 和 URL 映射
    tasks = []
    for v in videos:
        url = v.get('URL', '')
        vid = None
        if 'youtube.com' in url or 'youtu.be' in url:
            m = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', url)
            if not m:
                m = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', url)
            if m:
                vid = m.group(1)
        if vid:
            tasks.append((vid, url))

    if not tasks:
        return {}

    results = {}
    lock = threading.Lock()

    def _fetch_one(vid, url):
        for attempt in range(4):
            try:
                r = subprocess.run(
                    ['yt-dlp', '--no-warnings', '--print', '%(upload_date)s',
                     f'https://www.youtube.com/watch?v={vid}'],
                    capture_output=True, text=True, timeout=45,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                date_str = r.stdout.strip()
                if date_str and len(date_str) == 8 and date_str.isdigit():
                    date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                    with lock:
                        results[url] = date_str
                    return
                if attempt < 3:
                    time.sleep((attempt + 1) * 8)
            except Exception:
                if attempt < 3:
                    time.sleep((attempt + 1) * 8)
        with lock:
            results[url] = ''

    workers = min(5, len(tasks))
    total = len(tasks)
    done = [0]

    def _wrapped(vid, url):
        _fetch_one(vid, url)
        done[0] += 1
        if progress_callback and done[0] % 10 == 0:
            progress_callback(done[0], total)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda r: _wrapped(*r), tasks))

    return results


# ---------------------------------------------------------------------------
# CSV 导出
# ---------------------------------------------------------------------------

def export_to_csv(videos, output_path):
    """导出到 CSV"""
    if not videos:
        print("没有视频可导出")
        return False
    df = pd.DataFrame(videos)
    columns = ['标题', 'URL', '上传日期', '时长(秒)', '播放量']
    df = df[[col for col in columns if col in df.columns]]
    if '上传日期' in df.columns:
        df = df.sort_values('上传日期', ascending=False)
    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    _log.info(f"CSV导出: 路径={output_path} 记录数={len(df)}")
    print(f"已导出 {len(df)} 个视频到: {output_path}")
    return True


# ---------------------------------------------------------------------------
# 过滤函数
# ---------------------------------------------------------------------------

def filter_videos(videos, after_date=None, before_date=None,
                   min_duration=None, max_duration=None,
                   min_views=None, max_views=None):
    """过滤视频列表"""
    filtered = []
    for video in videos:
        if after_date or before_date:
            upload_date_str = video.get('上传日期', '')
            if upload_date_str:
                try:
                    upload_date = datetime.strptime(upload_date_str, '%Y-%m-%d')
                    if after_date and upload_date < after_date:
                        continue
                    if before_date and upload_date > before_date:
                        continue
                except ValueError:
                    pass
        duration = video.get('时长(秒)', 0)
        if min_duration and duration < min_duration:
            continue
        if max_duration and duration > max_duration:
            continue
        views = video.get('播放量', 0)
        if min_views and views < min_views:
            continue
        if max_views and views > max_views:
            continue
        filtered.append(video)
    return filtered


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='YouTube 频道视频批量获取工具')
    parser.add_argument('-c', '--channel', required=True, help='频道URL')
    parser.add_argument('-o', '--output', default='channel_videos.csv',
                        help='输出文件 (.csv 或 .db)')
    parser.add_argument('--format', dest='fmt', default='csv',
                        choices=['csv', 'sqlite'], help='存储格式')
    parser.add_argument('--max', type=int, help='最多获取视频数量')
    parser.add_argument('--after', help='起始日期')
    parser.add_argument('--before', help='结束日期')
    parser.add_argument('--min-duration', help='最短时长 (如: 5m, 1h)')
    parser.add_argument('--max-duration', help='最长时长 (如: 30m, 2h)')
    parser.add_argument('--min-views', type=int, help='最小播放量')
    parser.add_argument('--max-views', type=int, help='最大播放量')
    args = parser.parse_args()

    output_path = os.path.abspath(args.output)
    save_dir = os.path.dirname(output_path) or os.getcwd()

    # 自动检测格式
    fmt = args.fmt
    if output_path.endswith('.db') or output_path.endswith('.sqlite'):
        fmt = 'sqlite'

    videos, storage_path, _ = fetch_channel_videos(
        args.channel, max_videos=args.max,
        save_format=fmt, save_dir=save_dir,
        background_update=False,
    )

    if not videos:
        sys.exit(1)

    # CLI 模式直接打印统计
    print(f"\n统计信息:")
    print(f"  - 视频总数: {len(videos)}")
    df = pd.DataFrame(videos)
    if '播放量' in df.columns and df['播放量'].sum() > 0:
        print(f"  - 总播放量: {df['播放量'].sum():,}")
    if '时长(秒)' in df.columns:
        print(f"  - 总时长: {df['时长(秒)'].sum() / 3600:.1f} 小时")
    print(f"\n文件已保存: {storage_path}")
    print(f"存储格式: {fmt.upper()}")
    if fmt == 'sqlite':
        print(f"  提示: Phase2 上传日期获取已在后台运行，稍后查看数据库")
    else:
        print(f"  提示: CSV 模式不包含上传日期（可改用 --format sqlite 获取）")


if __name__ == '__main__':
    main()
