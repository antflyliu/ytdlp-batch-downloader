"""
tests/test_video_processor.py — video_processor 单元测试
mock subprocess.run，不调用真实 ffmpeg。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


def _mock_ffmpeg_success(*args, **kwargs):
    """模拟 ffmpeg 成功返回"""
    m = MagicMock()
    m.returncode = 0
    m.stderr = ""
    return m


def _mock_ffmpeg_fail(rc=1, stderr="error"):
    m = MagicMock()
    m.returncode = rc
    m.stderr = stderr
    return m


class TestVideoProcessorInit:
    def test_creates_dirs(self, tmp_path):
        from scripts.video_processor import VideoProcessor
        clips = tmp_path / "clips"
        colls = tmp_path / "colls"
        vp = VideoProcessor(clips_dir=clips, collections_dir=colls)
        assert clips.exists()
        assert colls.exists()

    def test_output_dir_from_string(self, tmp_path):
        from scripts.video_processor import VideoProcessor
        vp = VideoProcessor(str(tmp_path / "clips"), str(tmp_path / "colls"))
        assert vp.clips_dir.name == "clips"
        assert vp.collections_dir.name == "colls"


class TestExtractClip:
    @patch("subprocess.run")
    def test_extract_clip_success(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_success()

        video = tmp_path / "input.mp4"
        video.write_text("fake video content")

        clips_dir = tmp_path / "clips"
        from scripts.video_processor import VideoProcessor
        vp = VideoProcessor(clips_dir=clips_dir, collections_dir=tmp_path / "colls")

        result = vp.extract_clip(
            input_video=video,
            clip_id=1,
            title="测试片段",
            start_time=10.0,
            end_time=20.0,
        )

        assert result is not None
        assert result.name == "clip_0001_测试片段.mp4"
        mock_run.assert_called_once()
        # 验证时间参数
        cmd = mock_run.call_args[0][0]
        assert "-ss" in cmd
        assert "00:00:10.000" in cmd

    @patch("subprocess.run")
    def test_extract_clip_zero_duration(self, mock_run, tmp_path):
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        result = vp.extract_clip(video, clip_id=1, title="bad", start_time=10.0, end_time=10.0)
        assert result is None
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_extract_clip_ffmpeg_fails(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_fail(1, "unknown error")
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        result = vp.extract_clip(video, clip_id=1, title="fail", start_time=0.0, end_time=5.0)
        assert result is None

    @patch("subprocess.run")
    def test_extract_clip_custom_output_name(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_success()
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        result = vp.extract_clip(
            video, clip_id=1, title="test",
            start_time=0.0, end_time=5.0,
            output_name="my_custom_clip",
        )
        assert result.name == "my_custom_clip.mp4"


class TestBatchExtract:
    @patch("subprocess.run")
    def test_batch_extract_all_success(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_success()
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        clips_data = [
            {"id": 1, "title": "clip1", "start_time": 0.0, "end_time": 5.0},
            {"id": 2, "title": "clip2", "start_time": 5.0, "end_time": 10.0},
        ]
        results = vp.batch_extract_clips(video, clips_data)
        assert len(results) == 2
        assert all(r["clip_path"] is not None for r in results)

    @patch("subprocess.run")
    def test_batch_extract_partial_failure(self, mock_run, tmp_path):
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        def side_effect(*args, **kwargs):
            m = MagicMock()
            m.returncode = 0 if "0001" in str(args) else 1
            m.stderr = ""
            return m

        mock_run.side_effect = side_effect

        clips_data = [
            {"id": 1, "title": "good", "start_time": 0.0, "end_time": 5.0},
            {"id": 2, "title": "bad", "start_time": 5.0, "end_time": 10.0},
        ]
        results = vp.batch_extract_clips(video, clips_data)
        assert results[0]["clip_path"] is not None
        assert results[1]["clip_path"] is None


class TestCreateCollection:
    @patch("subprocess.run")
    def test_create_collection_success(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_success()
        from scripts.video_processor import VideoProcessor
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        # 创建假的片段文件
        clip1 = clips_dir / "clip1.mp4"
        clip2 = clips_dir / "clip2.mp4"
        clip1.write_text("fake")
        clip2.write_text("fake")

        vp = VideoProcessor(clips_dir=clips_dir, collections_dir=tmp_path / "colls")
        result = vp.create_collection(
            collection_id=1,
            title="合集标题",
            clip_paths=[str(clip1), str(clip2)],
        )
        assert result is not None
        assert "collection_0001_合集标题.mp4" == result.name
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_create_collection_no_valid_clips(self, mock_run, tmp_path):
        from scripts.video_processor import VideoProcessor
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")
        result = vp.create_collection(
            collection_id=1,
            title="empty",
            clip_paths=["nonexistent1.mp4", "nonexistent2.mp4"],
        )
        assert result is None
        mock_run.assert_not_called()


class TestFormatTime:
    def test_fmt_ts_basic(self):
        from scripts.video_processor import _fmt_ts
        assert _fmt_ts(0.0) == "00:00:00.000"
        assert _fmt_ts(65.5) == "00:01:05.500"
        assert _fmt_ts(3661.123) == "01:01:01.123"


class TestExtractThumbnail:
    @patch("subprocess.run")
    def test_extract_thumbnail_success(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_success()
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        result = vp.extract_thumbnail(video, clip_id=5, timestamp=12.5)

        assert result is not None
        assert result.name == "clip_0005_thumb.jpg"
        cmd = mock_run.call_args[0][0]
        assert "-frames:v" in cmd and "1" in cmd

    @patch("subprocess.run")
    def test_extract_thumbnail_custom_name(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_success()
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        result = vp.extract_thumbnail(video, clip_id=1, timestamp=5.0, output_name="my_thumb")
        assert result.name == "my_thumb.jpg"

    @patch("subprocess.run")
    def test_extract_thumbnail_failure(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_fail(1, "frame not found")
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        result = vp.extract_thumbnail(video, clip_id=1, timestamp=0.0)
        assert result is None


class TestDetectAspectRatio:
    @patch("subprocess.run")
    def test_detect_16x9(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1920,1080\n")
        from scripts.video_processor import VideoProcessor
        vp = VideoProcessor("clips", "colls")
        result = vp.detect_aspect_ratio("dummy.mp4")
        assert result == "16:9"

    @patch("subprocess.run")
    def test_detect_9x16(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1080,1920\n")
        from scripts.video_processor import VideoProcessor
        vp = VideoProcessor("clips", "colls")
        result = vp.detect_aspect_ratio("dummy.mp4")
        assert result == "9:16"

    @patch("subprocess.run")
    def test_detect_4x3(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1024,768\n")
        from scripts.video_processor import VideoProcessor
        vp = VideoProcessor("clips", "colls")
        result = vp.detect_aspect_ratio("dummy.mp4")
        assert result == "4:3"

    @patch("subprocess.run")
    def test_detect_other(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1920,960\n")  # ratio=2.0, not near any standard
        from scripts.video_processor import VideoProcessor
        vp = VideoProcessor("clips", "colls")
        result = vp.detect_aspect_ratio("dummy.mp4")
        assert result == "other"

    @patch("subprocess.run")
    def test_detect_probe_fails(self, mock_run):
        mock_run.side_effect = Exception("ffprobe not found")
        from scripts.video_processor import VideoProcessor
        vp = VideoProcessor("clips", "colls")
        result = vp.detect_aspect_ratio("dummy.mp4")
        assert result is None


class TestEnsureAspectRatio:
    @patch("subprocess.run")
    def test_already_target_ratio_copies(self, mock_run, tmp_path):
        # ffprobe 返回已是目标比例 → 直接 copy
        mock_run.return_value = MagicMock(returncode=0, stdout="1920,1080\n")
        from scripts.video_processor import VideoProcessor
        import shutil
        video = tmp_path / "input.mp4"
        video.write_text("video content")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")
        out = tmp_path / "out.mp4"

        result = vp.ensure_aspect_ratio(video, "16:9", out)
        assert result is not None
        # 不调用 ffmpeg，直接复制
        assert mock_run.call_count == 1  # ffprobe only

    @patch("subprocess.run")
    def test_9x16_adapts_with_scale_and_pad(self, mock_run, tmp_path):
        # First call: detect_aspect_ratio (16:9 → needs adaptation)
        # Second call: ffmpeg scale+pad
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="1920,1080\n"),  # detect → 16:9
            _mock_ffmpeg_success(),                          # ffmpeg succeeds
        ]
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")
        out = tmp_path / "out.mkv"

        result = vp.ensure_aspect_ratio(video, "9:16", out)
        assert result is not None
        # Check the ffmpeg call (second invocation) — vf is the item after -vf
        cmd = mock_run.call_args_list[1][0][0]
        vf_idx = cmd.index("-vf") + 1
        vf = cmd[vf_idx]
        assert "scale=1080:-1" in vf
        assert "pad=1080:1920" in vf

    @patch("subprocess.run")
    def test_unsupported_ratio_returns_none(self, mock_run, tmp_path):
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")
        out = tmp_path / "out.mp4"

        result = vp.ensure_aspect_ratio(video, "21:9", out)
        assert result is None


class TestEmbedSubtitlesSoft:
    def test_subtitle_file_not_found(self, tmp_path):
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")
        out = tmp_path / "out.mkv"

        result = vp.embed_subtitles_soft(video, tmp_path / "nonexistent.vtt", out)
        assert result is None

    @patch("subprocess.run")
    def test_embed_vtt_success(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_success()
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        sub = tmp_path / "sub.vtt"
        out = tmp_path / "out.mkv"
        video.write_text("fake")
        sub.write_text("WEBVTT")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        result = vp.embed_subtitles_soft(video, sub, out)
        assert result is not None
        cmd = mock_run.call_args[0][0]
        assert "-c:s" in cmd and "copy" in cmd

    @patch("subprocess.run")
    def test_embed_ass_success(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_success()
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        sub = tmp_path / "sub.ass"
        out = tmp_path / "out.mkv"
        video.write_text("fake")
        sub.write_text("[Script Info]")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        result = vp.embed_subtitles_soft(video, sub, out)
        assert result is not None

    @patch("subprocess.run")
    def test_embed_failure(self, mock_run, tmp_path):
        mock_run.return_value = _mock_ffmpeg_fail(1, "invalid subtitle")
        from scripts.video_processor import VideoProcessor
        video = tmp_path / "input.mp4"
        sub = tmp_path / "sub.vtt"
        out = tmp_path / "out.mkv"
        video.write_text("fake")
        sub.write_text("WEBVTT")
        vp = VideoProcessor(tmp_path / "clips", tmp_path / "colls")

        result = vp.embed_subtitles_soft(video, sub, out)
        assert result is None


class TestProbeDuration:
    @patch("subprocess.run")
    def test_probe_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="123.456\n")
        from scripts.video_processor import _probe_duration
        result = _probe_duration("dummy.mp4")
        assert result == 123.456

    @patch("subprocess.run")
    def test_probe_failure(self, mock_run):
        mock_run.side_effect = Exception("ffprobe not found")
        from scripts.video_processor import _probe_duration
        result = _probe_duration("dummy.mp4")
        assert result is None
