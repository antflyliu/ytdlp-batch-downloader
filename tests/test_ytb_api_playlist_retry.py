"""
TDD: 测试 playlist 模式在 uploads_playlist_id 获取失败时的行为

核心行为：
  1. _get_uploads_playlist_id() 失败时指数退避重试（最多 3 次）
  2. _get_channel_videos_by_playlist() 在 uploads_playlist_id 失败时返回空列表
  3. 不触发 search.list（避免 100 units 高额 quota）
"""

from unittest.mock import MagicMock


class TestPlaylistFallbackNoSearchList:
    """playlist 模式获取 uploads_playlist_id 失败时，不触发 search.list."""

    def test_returns_empty_when_uploads_id_missing(self):
        from ytb_api import YouTubeDataCollector
        collector = YouTubeDataCollector(
            api_key="test_key",
            save_path="/tmp",
            max_limit=5,
            fetch_mode="playlist",
            view_threshold=0,
        )
        collector._get_uploads_playlist_id = MagicMock(return_value=None)
        result = collector._get_channel_videos_by_playlist("UCtest123")
        assert result == []
        collector._get_uploads_playlist_id.assert_called_once_with("UCtest123")

    def test_uploads_id_exception_returns_empty(self):
        from ytb_api import YouTubeDataCollector
        collector = YouTubeDataCollector(
            api_key="test_key",
            save_path="/tmp",
            max_limit=5,
            fetch_mode="playlist",
            view_threshold=0,
        )
        collector._get_uploads_playlist_id = MagicMock(
            side_effect=Exception("Network error")
        )
        result = collector._get_channel_videos_by_playlist("UCtest123")
        assert result == []


class TestUploadsPlaylistIdRetry:
    def _mock_channels(self, collector, side_effect):
        """list/tuple 用 side_effect 迭代；单个 dict 响应用 return_value（dict 可迭代键，勿当 side_effect）。"""
        collector.youtube = MagicMock()
        exe = collector.youtube.channels.return_value.list.return_value.execute
        if isinstance(side_effect, (list, tuple)):
            exe.side_effect = side_effect
        else:
            exe.return_value = side_effect

    def test_retries_up_to_max_attempts(self):
        from ytb_api import YouTubeDataCollector
        collector = YouTubeDataCollector(
            api_key="test_key", save_path="/tmp",
            max_limit=5, fetch_mode="playlist", view_threshold=0,
        )
        self._mock_channels(collector, [Exception("e") for e in range(1, 4)])
        result = collector._get_uploads_playlist_id("UCtest123")
        assert result is None
        assert collector.youtube.channels.return_value.list.call_count == 3

    def test_succeeds_on_third_attempt(self):
        from ytb_api import YouTubeDataCollector
        collector = YouTubeDataCollector(
            api_key="test_key", save_path="/tmp",
            max_limit=5, fetch_mode="playlist", view_threshold=0,
        )
        inner = {"relatedPlaylists": {"uploads": "UUsuccess"}}
        middle = {"contentDetails": inner}
        outer = {"items": [middle]}
        self._mock_channels(
            collector,
            [Exception("fail_1"), Exception("fail_2"), outer],
        )
        result = collector._get_uploads_playlist_id("UCtest123")
        assert result == "UUsuccess"
        assert collector.youtube.channels.return_value.list.call_count == 3


    def test_no_search_list_quota_on_failure(self):
        from ytb_api import YouTubeDataCollector
        collector = YouTubeDataCollector(
            api_key="test_key", save_path="/tmp",
            max_limit=5, fetch_mode="playlist", view_threshold=0,
        )
        self._mock_channels(collector, [Exception("e") for e in range(1, 4)])
        incr_calls = []
        collector._incr_quota = lambda c=1: incr_calls.append(c)
        result = collector._get_channel_videos_by_playlist("UCtest")
        assert result == []
        assert 100 not in incr_calls, f"不应有100 units，实际: {incr_calls}"
