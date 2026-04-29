import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))

import monitor.db as monitor_db
from monitor.fetcher import YouTubeFetcher, parse_youtube_duration
from ytb_api import YouTubeDataCollector


class _FakeRequest:
    def __init__(self, items):
        self._items = items

    def execute(self):
        return {"items": self._items}


class _FakeVideosResource:
    def __init__(self, items):
        self.items = items
        self.last_kwargs = None

    def list(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeRequest(self.items)


class _FakeYouTubeService:
    def __init__(self, items):
        self._videos = _FakeVideosResource(items)

    def videos(self):
        return self._videos


class _FakeCollector:
    def __init__(self, *args, **kwargs):
        pass

    def probe_uploads_playlist_id(self, channel_id):
        """与 get_channel_meta mock 中的 uploads_playlist_id 一致，避免走不一致刷新分支。"""
        return "UU1234567890"

    def get_channel_videos(self, channel_id):
        return [
            {
                "id": "vid12345678A",
                "snippet": {
                    "title": "Duration Test Video",
                    "description": "desc",
                    "publishedAt": "2026-04-03T00:00:00Z",
                    "thumbnails": {
                        "high": {"url": "https://example.com/thumb.jpg"},
                    },
                },
                "statistics": {
                    "viewCount": "123",
                    "likeCount": "4",
                    "commentCount": "5",
                },
                "contentDetails": {
                    "duration": "PT1H2M3S",
                },
            }
        ]


class MonitorDurationPersistenceTests(unittest.TestCase):
    def test_parse_youtube_duration(self):
        self.assertEqual(parse_youtube_duration("PT1H2M3S"), 3723)
        self.assertEqual(parse_youtube_duration("PT59S"), 59)
        self.assertIsNone(parse_youtube_duration(None))
        self.assertIsNone(parse_youtube_duration("not-a-duration"))

    def test_get_videos_details_requests_content_details(self):
        fake_service = _FakeYouTubeService(
            [{"id": "vid12345678A", "contentDetails": {"duration": "PT42S"}}]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("ytb_api.build", return_value=fake_service):
                collector = YouTubeDataCollector(api_key="dummy", save_path=tmpdir)
            collector._incr_quota = lambda calls=1: None

            items = collector.get_videos_details(["vid12345678A"])

        self.assertEqual(items[0]["contentDetails"]["duration"], "PT42S")
        self.assertEqual(
            fake_service.videos().last_kwargs["part"],
            "snippet,statistics,contentDetails",
        )

    def test_fetcher_duration_sec_is_persisted_to_monitor_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db_path = os.path.join(tmpdir, "monitor.db")

            _conn = __import__("monitor.db.connection", fromlist=["_DB_PATH"])
            with patch.object(monitor_db, "_DATA_DIR", tmpdir), patch.object(
                monitor_db, "_DB_PATH", temp_db_path
            ), patch.object(_conn, "_DATA_DIR", tmpdir), patch.object(
                _conn, "_DB_PATH", temp_db_path
            ):
                monitor_db.init_db()
                account_id = monitor_db.add_account(
                    name="Duration Test",
                    channel_url="@duration-test",
                    api_key_env="YOUTUBE_Data_API_V3",
                )
                event_id = monitor_db.create_event(account_id, "Duration Test")

                with patch(
                    "monitor.fetcher.channel_cache.get_channel_meta",
                    return_value={
                        "channel_id": "UC1234567890",
                        "channel_name": "Duration Test",
                        "uploads_playlist_id": "UU1234567890",
                        "subscriber_count": "1",
                        "video_count": "1",
                        "description": "desc",
                        # TTL 未过期 + 健康检查间隔内（避免走 get_channel_data）
                        "cached_at": "2026-04-10T00:00:00+00:00",
                        "health_checked_at": "2026-04-14T00:00:00+00:00",
                    },
                ), patch("monitor.fetcher.YouTubeDataCollector", _FakeCollector):
                    videos, _ = YouTubeFetcher(
                        api_key="dummy",
                        fetch_mode="playlist",
                        fetch_limit=5,
                    ).fetch("@duration-test")

                self.assertEqual(videos[0]["duration_sec"], 3723)

                inserted = monitor_db.insert_videos(videos, account_id, event_id)
                self.assertEqual(inserted, 1)

                with monitor_db.get_connection() as conn:
                    duration_sec = conn.execute(
                        "SELECT duration_sec FROM monitor_videos WHERE video_id=?",
                        (videos[0]["video_id"],),
                    ).fetchone()[0]

                self.assertEqual(duration_sec, 3723)


if __name__ == "__main__":
    unittest.main()
