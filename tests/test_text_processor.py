"""
tests/test_text_processor.py — text_processor 单元测试
不依赖真实文件/网络，mock SRT 内容。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from scripts.text_processor import (
    SRTEntry,
    parse_srt,
    save_srt,
    chunk_srt_data,
    extract_text_from_entries,
    extract_text_by_time_range,
    save_chunks,
)


# ── 测试 SRT 内容 ────────────────────────────────────────────────────────────

SAMPLE_SRT = """1
00:00:00,000 --> 00:00:05,000
这是第一条字幕

2
00:00:05,100 --> 00:00:10,200
这是第二条字幕内容

3
00:00:10,300 --> 00:00:15,400
第三条字幕在这里

4
00:00:15,500 --> 00:00:20,600
第四条内容测试分块

5
00:00:20,700 --> 00:00:25,800
第五条非常长的字幕用来测试字符数限制这是一个很长的句子
"""

LONG_SRT = "\n\n".join(
    f"""{i}
{i:02d}:{i:02d}:00,000 --> {i:02d}:{i:02d}:30,000
这是第{i}条字幕内容用于测试分块逻辑"""
    for i in range(1, 11)
)


class TestSRTEntry:
    def test_duration(self):
        e = SRTEntry(index=1, start=0.0, end=10.5, text="test")
        assert e.duration() == 10.5

    def test_to_srt_line(self):
        e = SRTEntry(index=3, start=10.5, end=15.3, text="hello world")
        lines = e.to_srt_line()
        assert "3\n" in lines
        assert "00:00:10,500 --> 00:00:15,300" in lines
        assert "hello world" in lines


class TestParseSRT:
    def test_parse_basic(self, tmp_path):
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(SAMPLE_SRT, encoding="utf-8")

        entries = parse_srt(srt_file)

        assert len(entries) == 5
        assert entries[0].text == "这是第一条字幕"
        assert entries[0].start == 0.0
        assert entries[0].end == 5.0
        assert entries[4].text == "第五条非常长的字幕用来测试字符数限制这是一个很长的句子"

    def test_parse_empty_file(self, tmp_path):
        srt_file = tmp_path / "empty.srt"
        srt_file.write_text("", encoding="utf-8")
        entries = parse_srt(srt_file)
        assert entries == []

    def test_parse_preserves_order(self, tmp_path):
        srt_file = tmp_path / "order.srt"
        srt_file.write_text(SAMPLE_SRT, encoding="utf-8")
        entries = parse_srt(srt_file)
        starts = [e.start for e in entries]
        assert starts == sorted(starts)


class TestSaveSRT:
    def test_save_and_reload(self, tmp_path):
        original = [
            SRTEntry(index=1, start=0.0, end=5.0, text="hello"),
            SRTEntry(index=2, start=5.0, end=10.0, text="world"),
        ]
        out_path = tmp_path / "out.srt"
        save_srt(original, out_path)

        entries = parse_srt(out_path)
        assert len(entries) == 2
        assert entries[0].text == "hello"
        assert entries[1].text == "world"


class TestChunkSRTData:
    def test_chunk_by_minutes(self, tmp_path):
        srt_file = tmp_path / "long.srt"
        srt_file.write_text(LONG_SRT, encoding="utf-8")

        entries = parse_srt(srt_file)
        # LONG_SRT 条目间隔 61 分钟 >> 0.5 分钟阈值，每条独立成块
        chunks = chunk_srt_data(entries, interval_minutes=0.5, max_chars_per_chunk=99999)
        assert len(chunks) == 10
        for chunk in chunks:
            assert "chunk_index" in chunk
            assert "text" in chunk
            assert "srt_entries" in chunk
            assert len(chunk["srt_entries"]) == 1  # 每块只有1条字幕

    def test_chunk_large_threshold(self, tmp_path):
        """使用大阈值让多条字幕进入同一块"""
        srt_file = tmp_path / "long.srt"
        srt_file.write_text(LONG_SRT, encoding="utf-8")
        entries = parse_srt(srt_file)
        # LONG_SRT 条目间隔 ~61分钟，用 120min 阈值让相邻条目进入同一块
        chunks = chunk_srt_data(entries, interval_minutes=120, max_chars_per_chunk=99999)
        # 10 条字幕，每 61min，120min 阈值下至少 2 条/块
        assert len(chunks) <= 5
        assert len(chunks) >= 2

    def test_chunk_by_chars(self, tmp_path):
        srt_file = tmp_path / "chars.srt"
        srt_file.write_text(SAMPLE_SRT, encoding="utf-8")

        entries = parse_srt(srt_file)
        # 设置一个极小的字符限制
        chunks = chunk_srt_data(entries, interval_minutes=999, max_chars_per_chunk=10)

        # 应该按字符数切分出多块
        assert len(chunks) >= 2

    def test_empty_entries(self):
        chunks = chunk_srt_data([], interval_minutes=30, max_chars_per_chunk=4000)
        assert chunks == []


class TestExtractText:
    def test_extract_all(self, tmp_path):
        srt_file = tmp_path / "extract.srt"
        srt_file.write_text(SAMPLE_SRT, encoding="utf-8")
        entries = parse_srt(srt_file)

        text = extract_text_from_entries(entries)
        assert "第一条" in text
        assert "第五条" in text

    def test_extract_by_time_range(self, tmp_path):
        srt_file = tmp_path / "range.srt"
        srt_file.write_text(SAMPLE_SRT, encoding="utf-8")
        entries = parse_srt(srt_file)

        # 提取 5s ~ 15s 的内容
        text = extract_text_by_time_range(entries, 5.0, 15.0)
        assert "第二" in text
        assert "第三" in text
        assert "第一" not in text  # 第一条在0-5s


class TestSaveChunks:
    def test_save_chunks(self, tmp_path):
        srt_file = tmp_path / "save_chunks.srt"
        srt_file.write_text(LONG_SRT, encoding="utf-8")
        entries = parse_srt(srt_file)
        chunks = chunk_srt_data(entries, interval_minutes=0.5, max_chars_per_chunk=99999)

        result = save_chunks(chunks, tmp_path / "output")
        assert Path(result["chunks_file"]).exists()
        assert (tmp_path / "output" / "chunk_texts").is_dir()

        loaded = json.loads(Path(result["chunks_file"]).read_text(encoding="utf-8"))
        assert len(loaded) == len(chunks)
