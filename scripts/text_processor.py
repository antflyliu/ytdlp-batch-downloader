#!/usr/bin/env python3
"""
scripts/text_processor.py — SRT 字幕解析与分块

功能:
  - 解析 SRT 文件 → List[dict]（含 start/end/text）
  - 按时间/字数智能分块
  - 文本清理（去除时间标记、多余空白等）
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SRTEntry:
    """单条 SRT 字幕条目"""
    index: int       # 字幕序号
    start: float     # 开始时间（秒）
    end: float       # 结束时间（秒）
    text: str        # 字幕文本
    chunk_index: int = 0  # 所属块索引

    def duration(self) -> float:
        return self.end - self.start

    def to_srt_line(self) -> str:
        """转为 SRT 格式字符串"""
        return (
            f"{self.index}\n"
            f"{_fmt_srt_time(self.start)} --> {_fmt_srt_time(self.end)}\n"
            f"{self.text}\n"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_srt_time(seconds: float) -> str:
    """秒 → SRT 时间格式 00:00:00,000"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _clean_text(text: str) -> str:
    """清理字幕文本"""
    text = text.strip()
    # 去除行内多余空格（保留句子结构）
    text = re.sub(r"[ \t]+", " ", text)
    # 去除可能的 HTML 标签残留
    text = re.sub(r"<[^>]+>", "", text)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# SRT 解析
# ─────────────────────────────────────────────────────────────────────────────

def parse_srt(srt_path: str | Path) -> List[SRTEntry]:
    """
    解析 SRT 文件。

    Args:
        srt_path: .srt 文件路径

    Returns:
        SRTEntry 列表（按时间顺序）
    """
    srt_path = Path(srt_path)
    entries: List[SRTEntry] = []

    content = srt_path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        # 第1行：序号
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        # 第2行：时间轴
        time_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            lines[1].strip(),
        )
        if not time_match:
            continue

        def parse_ts(ts: str) -> float:
            # 将逗号/句号替换为冒号，然后从右向左分割
            ts = ts.replace(",", ":")
            # 从右向左：最后一个冒号前是秒，前面的冒号依次是分、时
            parts = ts.split(":")
            ms = 0
            if len(parts) == 4:
                h, m, s, ms_str = parts
                ms = int(ms_str) if ms_str else 0
            elif len(parts) == 3:
                h, m, s_ms = parts
                s, ms_str = s_ms[:2], s_ms[2:]
                ms = int(ms_str) if ms_str else 0
            else:
                # fallback: 假设是 HH:MM:SS.mmm
                return float(ts.replace(",", "."))
            s = int(s) if s else 0
            return int(h) * 3600 + int(m) * 60 + s + ms / 1000

        start = parse_ts(time_match.group(1))
        end = parse_ts(time_match.group(2))

        # 第3行+：字幕文本
        text = "\n".join(lines[2:])
        text = _clean_text(text)

        if text:
            entries.append(SRTEntry(index=index, start=start, end=end, text=text))

    logger.info(f"SRT 解析完成: {srt_path.name}, {len(entries)} 条字幕")
    return entries


def parse_vtt(vtt_path: str | Path) -> List[SRTEntry]:
    """
    解析 WebVTT (.vtt) 文件。

    Args:
        vtt_path: .vtt 文件路径

    Returns:
        SRTEntry 列表（按时间顺序）
    """
    vtt_path = Path(vtt_path)
    entries: List[SRTEntry] = []

    content = vtt_path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", content.strip())

    index = 0
    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue

        # 找时间轴行（跳过 WEBVTT 头和各种 cue 设置行）
        time_line_idx = None
        for i, line in enumerate(lines):
            if "-->" in line:
                time_line_idx = i
                break
        if time_line_idx is None:
            continue

        time_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            lines[time_line_idx].strip(),
        )
        if not time_match:
            continue

        def parse_ts(ts: str) -> float:
            ts = ts.replace(",", ".")
            parts = ts.split(":")
            if len(parts) == 3:
                h, m, s_ms = parts
                s, ms_str = s_ms.split(".")
                return int(h) * 3600 + int(m) * 60 + float(s) + int(ms_str) / 1000
            return 0.0

        start = parse_ts(time_match.group(1))
        end = parse_ts(time_match.group(2))

        # VTT cue 文本在时间轴行之后
        text_lines = []
        for line in lines[time_line_idx + 1:]:
            # 跳过 VTT tags 和空行
            if line.startswith("WEBVTT") or line.startswith("NOTE") or not line.strip():
                continue
            # 去掉 inline tags 如 <c>, <b>, <i> 等
            cleaned = re.sub(r"<[^>]+>", "", line)
            text_lines.append(cleaned)

        text = _clean_text(" ".join(text_lines))
        if text:
            index += 1
            entries.append(SRTEntry(index=index, start=start, end=end, text=text))

    logger.info(f"VTT 解析完成: {vtt_path.name}, {len(entries)} 条字幕")
    return entries


def parse_subtitles(sub_path: str | Path) -> List[SRTEntry]:
    """
    自动检测并解析字幕文件（支持 .srt 和 .vtt）。

    Args:
        sub_path: 字幕文件路径

    Returns:
        SRTEntry 列表（按时间顺序）
    """
    p = Path(sub_path)
    if not p.exists():
        raise FileNotFoundError(f"字幕文件不存在: {sub_path}")

    # 按扩展名路由，走各自解析器
    ext = p.suffix.lower()
    if ext == ".srt":
        return parse_srt(p)
    elif ext == ".vtt":
        return parse_vtt(p)
    else:
        raise ValueError(f"不支持的字幕格式: {ext}，仅支持 .srt 和 .vtt")


def save_srt(entries: List[SRTEntry], output_path: str | Path) -> Path:
    """将 SRTEntry 列表保存为 .srt 文件"""
    output_path = Path(output_path)
    lines: list[str] = []
    for i, entry in enumerate(entries, 1):
        entry.index = i  # 重写序号
        lines.append(entry.to_srt_line())
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"SRT 已保存: {output_path}")
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# 分块策略
# ─────────────────────────────────────────────────────────────────────────────

def chunk_srt_data(
    entries: List[SRTEntry],
    interval_minutes: float = 30,
    max_chars_per_chunk: int = 4000,
) -> List[dict]:
    """
    按时间窗口将 SRT 条目分块。

    每块包含:
      - chunk_index: 块编号
      - start_time / end_time: 块的时间范围（秒）
      - text: 拼接后的纯文本
      - srt_entries: 该块包含的原始 SRT 条目

    Args:
        entries:     parse_srt() 返回的条目列表
        interval_minutes: 每块最大时长（分钟）
        max_chars_per_chunk: 每块最大字符数（防止 LLM 输入超限）

    Returns:
        chunk 列表
    """
    if not entries:
        return []

    chunks: list[dict] = []
    current_chunk_texts: list[str] = []
    current_chunk_entries: list[SRTEntry] = []
    chunk_start_time = entries[0].start
    chunk_start_index = entries[0].index
    current_start_time = entries[0].start

    def finish_chunk(idx: int):
        if not current_chunk_entries:
            return
        chunk_text = " ".join(current_chunk_texts)
        chunks.append({
            "chunk_index": idx,
            "start_time": chunk_start_time,
            "end_time": current_chunk_entries[-1].end,
            "text": chunk_text,
            "srt_entries": [asdict(e) for e in current_chunk_entries],
        })

    for entry in entries:
        entry_end_minutes = (entry.end - chunk_start_time) / 60.0
        entry_chars = len(" ".join(current_chunk_texts) + " " + entry.text)

        # 超时或超字符 → 切块
        if (entry_end_minutes >= interval_minutes or entry_chars >= max_chars_per_chunk) and current_chunk_entries:
            finish_chunk(len(chunks))
            current_chunk_texts = []
            current_chunk_entries = []
            chunk_start_time = entry.start

        entry.chunk_index = len(chunks)
        current_chunk_texts.append(entry.text)
        current_chunk_entries.append(entry)

    # 最后一块
    finish_chunk(len(chunks))

    logger.info(f"分块完成: {len(chunks)} 个块, 时长 ~{interval_minutes}min/块")
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# 文本提取
# ─────────────────────────────────────────────────────────────────────────────

def extract_text_from_entries(entries: List[SRTEntry]) -> str:
    """将 SRT 条目列表合并为纯文本"""
    return " ".join(e.text for e in entries)


def extract_text_by_time_range(
    entries: List[SRTEntry],
    start: float,
    end: float,
) -> str:
    """提取指定时间范围内重叠的字幕条目"""
    relevant = [
        e for e in entries
        if e.start < end and e.end > start  # 时间重叠
    ]
    return " ".join(e.text for e in relevant)


# ─────────────────────────────────────────────────────────────────────────────
# 调试/导出
# ─────────────────────────────────────────────────────────────────────────────

def save_chunks(chunks: List[dict], output_dir: str | Path) -> dict:
    """将分块结果保存到文件"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks_file = output_dir / "chunks.json"
    chunks_file.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    # 每块单独保存为 .txt（便于人工检查）
    texts_dir = output_dir / "chunk_texts"
    texts_dir.mkdir(exist_ok=True)
    for chunk in chunks:
        txt_file = texts_dir / f"chunk_{chunk['chunk_index']:03d}.txt"
        txt_file.write_text(chunk["text"], encoding="utf-8")

    logger.info(f"分块已保存: {chunks_file} + {texts_dir}/")
    return {"chunks_file": str(chunks_file), "texts_dir": str(texts_dir)}
