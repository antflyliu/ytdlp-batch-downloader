#!/usr/bin/env python3
"""
scripts/video_processor.py — 视频切片与合集生成

功能:
  - 批量从完整视频中提取多个片段
  - 将多个片段拼接为合集视频
  - 视频编码/转码封装
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _run_ffmpeg(cmd: List[str], timeout: int = 600) -> bool:
    """执行 ffmpeg 命令，失败打印 stderr"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg 失败 (rc={result.returncode}): {result.stderr[-500:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg 超时 (> {timeout}s)")
        return False
    except Exception as e:
        logger.error(f"ffmpeg 执行异常: {e}")
        return False


def _fmt_ts(seconds: float) -> str:
    """秒 → HH:MM:SS.mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _probe_duration(video_path: str | Path) -> Optional[float]:
    """用 ffprobe 探测视频时长（秒）"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 核心处理器
# ─────────────────────────────────────────────────────────────────────────────

class VideoProcessor:
    """
    视频切片与合集处理器。

    Args:
        clips_dir:       切片视频输出目录
        collections_dir:  合集视频输出目录
    """

    def __init__(
        self,
        clips_dir: str | Path,
        collections_dir: str | Path,
    ):
        self.clips_dir = Path(clips_dir)
        self.collections_dir = Path(collections_dir)
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.collections_dir.mkdir(parents=True, exist_ok=True)

    # ── 单片段提取 ───────────────────────────────────────────────────────────

    def extract_clip(
        self,
        input_video: str | Path,
        clip_id: int,
        title: str,
        start_time: float,
        end_time: float,
        output_name: str | None = None,
    ) -> Optional[Path]:
        """
        从视频中提取单个片段。

        Args:
            input_video:  输入视频路径
            clip_id:     片段编号（用于生成文件名）
            title:       片段标题（用于文件名）
            start_time:  开始时间（秒）
            end_time:    结束时间（秒）
            output_name: 自定义输出文件名（不含扩展名）

        Returns:
            成功返回输出文件 Path，失败返回 None
        """
        safe_title = re.sub(r"[^\w\u4e00-\u9fff\-_]", "_", title)[:40]
        output_name = output_name or f"clip_{clip_id:04d}_{safe_title}"
        output_path = self.clips_dir / f"{output_name}.mp4"

        duration = end_time - start_time
        if duration <= 0:
            logger.warning(f"片段 {clip_id} 时长 <= 0，跳过")
            return None

        cmd = [
            "ffmpeg", "-y",
            "-ss", _fmt_ts(start_time),
            "-i", str(input_video),
            "-t", _fmt_ts(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-avoid_negative_ts", "make_zero",
            str(output_path),
        ]

        logger.info(f"提取片段 {clip_id}: {title[:30]}... [{_fmt_ts(start_time)} → {_fmt_ts(end_time)}]")
        if _run_ffmpeg(cmd):
            logger.info(f"  → {output_path}")
            return output_path
        return None

    # ── 批量提取 ────────────────────────────────────────────────────────────

    def batch_extract_clips(
        self,
        input_video: str | Path,
        clips_data: List[dict],
    ) -> List[dict]:
        """
        批量提取多个片段。

        Args:
            input_video: 输入视频路径
            clips_data: List[{
                "id": int,
                "title": str,
                "start_time": float,
                "end_time": float,
                "output_name": str | None,  # 可选
              }]

        Returns:
            List[dict]: 成功提取的片段（含 "clip_path" 字段）
        """
        results: List[dict] = []
        for clip in clips_data:
            path = self.extract_clip(
                input_video=input_video,
                clip_id=clip["id"],
                title=clip.get("title", f"clip_{clip['id']}"),
                start_time=clip["start_time"],
                end_time=clip["end_time"],
                output_name=clip.get("output_name"),
            )
            if path:
                results.append({**clip, "clip_path": str(path)})
            else:
                results.append({**clip, "clip_path": None})
        return results

    # ── 合集拼接 ────────────────────────────────────────────────────────────

    def create_collection(
        self,
        collection_id: int,
        title: str,
        clip_paths: List[str],
        output_name: str | None = None,
    ) -> Optional[Path]:
        """
        将多个片段拼接为一个合集视频。

        Args:
            collection_id: 合集编号
            title:         合集标题（用于文件名）
            clip_paths:    片段文件路径列表（必须已存在）
            output_name:   自定义输出文件名

        Returns:
            成功返回输出文件 Path，失败返回 None
        """
        valid_paths = [Path(p) for p in clip_paths if Path(p).exists()]
        if not valid_paths:
            logger.error(f"合集 {collection_id} 无有效片段")
            return None

        safe_title = re.sub(r"[^\w\u4e00-\u9fff\-_]", "_", title)[:40]
        output_name = output_name or f"collection_{collection_id:04d}_{safe_title}"
        output_path = self.collections_dir / f"{output_name}.mp4"

        # 生成临时 concat 文件
        concat_file = self.collections_dir / f"concat_{collection_id}.txt"
        concat_file.write_text(
            "\n".join(f"file '{p.resolve()}'" for p in valid_paths),
            encoding="utf-8",
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        logger.info(f"生成合集 {collection_id}: {title[:30]}... ({len(valid_paths)} 个片段)")
        if _run_ffmpeg(cmd):
            # 清理临时文件
            concat_file.unlink(missing_ok=True)
            logger.info(f"  → {output_path}")
            return output_path
        concat_file.unlink(missing_ok=True)
        return None

    def create_collections_from_metadata(
        self,
        collections_data: List[dict],
    ) -> List[dict]:
        """
        从合集元数据批量生成合集视频。

        Args:
            collections_data: List[{
                "id": int,
                "title": str,
                "clip_ids": list[int],
                "clip_paths": list[str],
              }]

        Returns:
            List[dict]: 成功生成的合集（含 "collection_path" 字段）
        """
        results: List[dict] = []
        for coll in collections_data:
            path = self.create_collection(
                collection_id=coll["id"],
                title=coll.get("title", f"合集_{coll['id']}"),
                clip_paths=coll.get("clip_paths", []),
                output_name=coll.get("output_name"),
            )
            results.append({
                **coll,
                "collection_path": str(path) if path else None,
            })
        return results

    # ── 视频信息探测 ─────────────────────────────────────────────────────────

    def probe_video(self, video_path: str | Path) -> Optional[dict]:
        """返回视频元信息（时长、分辨率、编码等）"""
        duration = _probe_duration(video_path)
        if duration is None:
            return None
        return {
            "path": str(video_path),
            "duration": duration,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 便捷入口
# ─────────────────────────────────────────────────────────────────────────────

def batch_extract_clips(
    input_video: str | Path,
    clips_data: List[dict],
    clips_dir: str | Path,
) -> List[dict]:
    """快捷函数：从 metadata dir 创建 VideoProcessor 并批量提取"""
    clips_dir = Path(clips_dir)
    clips_dir.mkdir(parents=True, exist_ok=True)
    vp = VideoProcessor(clips_dir=clips_dir, collections_dir=clips_dir / "collections")
    return vp.batch_extract_clips(input_video, clips_data)
