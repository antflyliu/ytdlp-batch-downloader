"""
将 monitor_videos.download_path 解析为实际视频文件路径。

历史问题：自动/批量下载曾把「输出目录」而非「具体 mp4 路径」写入 download_path，
导致 splitext(download_path) + .srt 变成「目录名.srt」（例如 videos.srt）。
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_downloaded_video_path(video: dict) -> str | None:
    """
    从视频记录解析已下载视频文件的绝对路径。

    - 若 download_path 指向现有文件，直接返回。
    - 若指向目录（历史遗留），在目录内查找 .mp4（优先按标题匹配，否则取最新修改的一个）。
    """
    raw = (video.get("download_path") or "").strip()
    if not raw:
        return None
    if not os.path.exists(raw):
        return None
    if os.path.isfile(raw):
        return os.path.normpath(raw)
    if os.path.isdir(raw):
        title = (video.get("title") or "").strip()
        base = Path(raw)
        mp4s = sorted(base.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not mp4s:
            return None
        if len(mp4s) == 1:
            return str(mp4s[0].resolve())
        tl = title.lower()
        for p in mp4s:
            stem_l = p.stem.lower()
            if tl and (stem_l in tl or tl in stem_l):
                return str(p.resolve())
        return str(mp4s[0].resolve())
    return None
