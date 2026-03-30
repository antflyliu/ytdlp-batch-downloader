#!/usr/bin/env python3
"""
YouTube 频道视频批量获取工具
导出频道视频链接列表到 Excel

用法:
    python yt_channel_fetch.py -c "https://www.youtube.com/@channel" -o output.xlsx
    python yt_channel_fetch.py -c "https://www.youtube.com/@channel" -o output.xlsx --max 100
    python yt_channel_fetch.py -c "https://www.youtube.com/@channel" -o output.xlsx --after 2024-01-01 --before 2024-12-31
    python yt_channel_fetch.py -c "https://www.youtube.com/@channel" -o output.xlsx --min-duration 5m --max-views 100000
"""

import yt_dlp
import pandas as pd
import argparse
import sys
import os
from datetime import datetime


def parse_duration(duration_str):
    """解析时长字符串为秒数"""
    if not duration_str:
        return 0
    try:
        # yt-dlp 返回格式: HH:MM:SS 或 MM:SS
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
    """解析日期字符串"""
    if not date_str:
        return None
    formats = ['%Y%m%d', '%Y-%m-%d', '%Y/%m/%d', '%d.%m.%Y']
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def parse_min_duration(duration_str):
    """解析最小时长限制"""
    if not duration_str:
        return 0
    # 支持格式: 30s, 5m, 1h, 1h30m
    total_seconds = 0
    import re
    hours = re.findall(r'(\d+)h', duration_str)
    minutes = re.findall(r'(\d+)m', duration_str)
    seconds = re.findall(r'(\d+)s', duration_str)
    if hours:
        total_seconds += int(hours[0]) * 3600
    if minutes:
        total_seconds += int(minutes[0]) * 60
    if seconds:
        total_seconds += int(seconds[0])
    return total_seconds


def fetch_channel_videos(channel_url, max_videos=None):
    """获取频道视频信息"""
    print(f"正在获取频道视频列表: {channel_url}")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,  # 获取完整信息
        'ignoreerrors': True,
        'skip_download': True,
    }

    videos = []

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 获取频道信息
            channel_info = ydl.extract_info(channel_url, download=False)

            if not channel_info:
                print("错误：无法获取频道信息")
                return []

            # 处理不同格式的返回
            if 'entries' in channel_info:
                entries = channel_info['entries']
            elif 'videos' in channel_info:
                entries = channel_info['videos']
            else:
                # 可能是单一视频或其他格式
                entries = [channel_info]

            for entry in entries:
                if entry is None:
                    continue

                video_id = entry.get('id', '')
                if not video_id:
                    continue

                # 构建完整URL
                if video_id.startswith('http'):
                    video_url = video_id
                else:
                    video_url = f"https://www.youtube.com/watch?v={video_id}"

                title = entry.get('title', 'Unknown')
                upload_date = entry.get('upload_date', '')
                if upload_date and len(upload_date) == 8:
                    upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

                duration_sec = entry.get('duration', 0) or 0
                view_count = entry.get('view_count', 0) or 0

                videos.append({
                    '标题': title,
                    'URL': video_url,
                    '视频ID': video_id,
                    '上传日期': upload_date,
                    '时长(秒)': duration_sec,
                    '播放量': view_count,
                })

                if max_videos and len(videos) >= max_videos:
                    break

    except Exception as e:
        print(f"错误: {e}")
        return []

    return videos


def filter_videos(videos, after_date=None, before_date=None,
                   min_duration=None, max_duration=None,
                   min_views=None, max_views=None):
    """过滤视频列表"""
    filtered = []

    for video in videos:
        # 日期过滤
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

        # 时长过滤
        duration = video.get('时长(秒)', 0)
        if min_duration and duration < min_duration:
            continue
        if max_duration and duration > max_duration:
            continue

        # 播放量过滤
        views = video.get('播放量', 0)
        if min_views and views < min_views:
            continue
        if max_views and views > max_views:
            continue

        filtered.append(video)

    return filtered


def export_to_excel(videos, output_path):
    """导出到 Excel"""
    if not videos:
        print("没有视频可导出")
        return False

    df = pd.DataFrame(videos)

    # 只保留需要的列
    columns = ['标题', 'URL', '上传日期', '时长(秒)', '播放量']
    df = df[[col for col in columns if col in df.columns]]

    # 按上传日期降序排列
    if '上传日期' in df.columns:
        df = df.sort_values('上传日期', ascending=False)

    df.to_excel(output_path, index=False, engine='openpyxl')
    print(f"已导出 {len(df)} 个视频到: {output_path}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='YouTube 频道视频批量获取工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('-c', '--channel', required=True,
                        help='频道URL (@handle 或完整URL)')
    parser.add_argument('-o', '--output', default='channel_videos.xlsx',
                        help='输出Excel文件 (默认: channel_videos.xlsx)')

    # 过滤参数
    parser.add_argument('--max', type=int,
                        help='最多获取视频数量')
    parser.add_argument('--after',
                        help='起始日期 (格式: 2024-01-01 或 20240101)')
    parser.add_argument('--before',
                        help='结束日期 (格式: 2024-12-31 或 20241231)')
    parser.add_argument('--min-duration',
                        help='最短时长 (如: 5m, 1h, 30s)')
    parser.add_argument('--max-duration',
                        help='最长时长 (如: 30m, 2h)')
    parser.add_argument('--min-views', type=int,
                        help='最小播放量')
    parser.add_argument('--max-views', type=int,
                        help='最大播放量')

    # 附加选项
    parser.add_argument('--no-download', action='store_true',
                        help='仅获取列表，不下载')

    args = parser.parse_args()

    # 解析日期
    after_date = parse_date(args.after)
    before_date = parse_date(args.before)

    # 解析时长
    min_duration = parse_min_duration(args.min_duration)
    max_duration = parse_min_duration(args.max_duration)

    # 获取视频列表
    videos = fetch_channel_videos(args.channel, args.max)

    if not videos:
        print("未获取到任何视频")
        sys.exit(1)

    print(f"获取到 {len(videos)} 个视频")

    # 过滤
    original_count = len(videos)
    videos = filter_videos(
        videos,
        after_date=after_date,
        before_date=before_date,
        min_duration=min_duration,
        max_duration=max_duration,
        min_views=args.min_views,
        max_views=args.max_views
    )

    if original_count != len(videos):
        print(f"过滤后剩余 {len(videos)} 个视频")

    # 导出
    output_path = os.path.abspath(args.output)
    export_to_excel(videos, output_path)

    # 统计信息
    if videos:
        df = pd.DataFrame(videos)
        print(f"\n统计信息:")
        print(f"  - 视频总数: {len(videos)}")
        if '播放量' in df.columns and df['播放量'].sum() > 0:
            print(f"  - 总播放量: {df['播放量'].sum():,}")
        if '时长(秒)' in df.columns:
            total_minutes = df['时长(秒)'].sum() / 60
            print(f"  - 总时长: {total_minutes:.1f} 分钟")

    print(f"\n文件已保存: {output_path}")
    print("可用 Excel 打开查看视频列表，然后用 Youtube_Downloader.py 批量下载")


if __name__ == '__main__':
    main()
