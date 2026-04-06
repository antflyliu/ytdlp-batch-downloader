"""
monitor 子系统多数据库兼容基础冒烟测试。

使用内存 SQLite 数据库，不依赖外部服务。
验证 database.py / db.py / cache.py / quota.py 核心 CRUD 逻辑。
"""
import os
import sys
import pytest

# 确保项目根目录在 sys.path 中
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 强制使用内存 SQLite（必须在 import monitor 之前设置）
os.environ["MONITOR_DATABASE_URL"] = "sqlite://"


@pytest.fixture(autouse=True)
def _reset_engine():
    """每个测试用例重置 Engine 单例 + 重建表。"""
    from monitor.database import reset_engine, create_all_tables

    reset_engine()
    create_all_tables()
    yield
    reset_engine()


# ── database.py 基础 ────────────────────────────────────────────

class TestDatabase:
    def test_engine_dialect(self):
        from monitor.database import get_dialect_name
        assert get_dialect_name() == "sqlite"

    def test_create_all_tables(self):
        from sqlalchemy import inspect
        from monitor.database import get_engine
        insp = inspect(get_engine())
        tables = set(insp.get_table_names())
        expected = {
            "api_keys", "monitor_accounts", "monitor_events",
            "monitor_videos", "app_state", "monitor_notify_logs",
            "channel_meta_cache", "api_quota_usage", "schema_migrations",
        }
        assert expected.issubset(tables)


# ── db.py CRUD ───────────────────────────────────────────────────

class TestApiKeys:
    def test_add_and_get(self):
        from monitor.db import add_api_key, get_api_key, get_api_key_by_value
        kid = add_api_key("AIza_test_key_1", "TestKey1", daily_quota=5000)
        assert kid >= 1
        rec = get_api_key(kid)
        assert rec is not None
        assert rec["name"] == "TestKey1"
        assert rec["daily_quota"] == 5000
        rec2 = get_api_key_by_value("AIza_test_key_1")
        assert rec2["id"] == kid

    def test_update(self):
        from monitor.db import add_api_key, update_api_key, get_api_key
        kid = add_api_key("AIza_update", "OldName")
        update_api_key(kid, name="NewName", daily_quota=2000, is_active=False)
        rec = get_api_key(kid)
        assert rec["name"] == "NewName"
        assert rec["daily_quota"] == 2000
        assert rec["is_active"] == 0

    def test_delete(self):
        from monitor.db import add_api_key, delete_api_key, get_api_key
        kid = add_api_key("AIza_delete", "Del")
        delete_api_key(kid)
        assert get_api_key(kid) is None

    def test_list(self):
        from monitor.db import add_api_key, list_api_keys
        add_api_key("AIza_list_1", "K1")
        add_api_key("AIza_list_2", "K2")
        keys = list_api_keys()
        assert len(keys) >= 2


class TestAccounts:
    def test_add_and_get(self):
        from monitor.db import add_api_key, add_account, get_account
        kid = add_api_key("AIza_acc", "AccKey")
        aid = add_account(
            name="TestChannel",
            channel_url="@TestChannel",
            api_key_env="YOUTUBE_KEY",
            api_key_id=kid,
        )
        assert aid >= 1
        acc = get_account(aid)
        assert acc["name"] == "TestChannel"
        assert acc["api_key_id"] == kid

    def test_update(self):
        from monitor.db import add_account, update_account, get_account
        aid = add_account(
            name="Before", channel_url="@Before", api_key_env="K",
        )
        update_account(aid, name="After", webhook_url="https://example.com/hook")
        acc = get_account(aid)
        assert acc["name"] == "After"

    def test_list_enabled_only(self):
        from monitor.db import add_account, list_accounts, update_account
        a1 = add_account(name="E1", channel_url="@e1", api_key_env="K")
        a2 = add_account(name="E2", channel_url="@e2", api_key_env="K")
        update_account(a2, enabled=False)
        enabled = list_accounts(enabled_only=True)
        all_accs = list_accounts()
        assert len(enabled) == 1
        assert len(all_accs) == 2

    def test_delete(self):
        from monitor.db import add_account, delete_account, get_account
        aid = add_account(name="Del", channel_url="@del", api_key_env="K")
        delete_account(aid)
        assert get_account(aid) is None


class TestEvents:
    def test_create_and_finish(self):
        from monitor.db import (
            add_account, create_event, finish_event, get_recent_events,
        )
        aid = add_account(name="Ev", channel_url="@ev", api_key_env="K")
        eid = create_event(aid, "Ev")
        assert eid >= 1
        finish_event(eid, "success", total_videos=10, new_videos=3, duration_ms=500)
        events = get_recent_events(limit=5)
        assert len(events) >= 1
        ev = events[0]
        assert ev["status"] == "success"
        assert ev["new_videos"] == 3


class TestVideos:
    def test_insert_and_query(self):
        from monitor.db import (
            add_account, create_event, insert_videos,
            get_account_videos, get_new_video_ids,
        )
        aid = add_account(name="V", channel_url="@v", api_key_env="K")
        eid = create_event(aid, "V")
        videos = [
            {"video_id": "vid001", "title": "T1", "url": "https://y.be/vid001",
             "published_at": "2024-01-01T00:00:00Z"},
            {"video_id": "vid002", "title": "T2", "url": "https://y.be/vid002",
             "published_at": "2024-01-02T00:00:00Z"},
        ]
        inserted = insert_videos(videos, aid, eid)
        assert inserted == 2

        # 重复插入被忽略
        dup = insert_videos(videos, aid, eid)
        assert dup == 0

        # 查询
        result, total = get_account_videos(aid, page=1, page_size=10)
        assert total == 2
        assert len(result) == 2

        # 新 ID 检测
        new_ids = get_new_video_ids(
            [{"video_id": "vid001"}, {"video_id": "vid003"}]
        )
        assert new_ids == {"vid003"}

    def test_search(self):
        from monitor.db import (
            add_account, create_event, insert_videos, get_account_videos,
        )
        aid = add_account(name="S", channel_url="@s", api_key_env="K")
        eid = create_event(aid, "S")
        insert_videos([
            {"video_id": "s1", "title": "Python Tutorial",
             "url": "https://y.be/s1", "published_at": "2024-06-01"},
            {"video_id": "s2", "title": "Rust Guide",
             "url": "https://y.be/s2", "published_at": "2024-06-02"},
        ], aid, eid)
        result, total = get_account_videos(aid, title_kw="Python")
        assert total == 1
        assert result[0]["title"] == "Python Tutorial"

    def test_download_status(self):
        from monitor.db import (
            add_account, create_event, insert_videos,
            update_videos_download_status, get_videos_by_ids,
        )
        aid = add_account(name="DL", channel_url="@dl", api_key_env="K")
        eid = create_event(aid, "DL")
        insert_videos([
            {"video_id": "dl1", "title": "DL1",
             "url": "https://y.be/dl1", "published_at": "2024-01-01"},
        ], aid, eid)
        vids = get_videos_by_ids([1])
        assert len(vids) == 1
        updated = update_videos_download_status(
            [1], "downloaded", download_path="/tmp/dl1.mp4",
        )
        assert updated == 1

    def test_notify_sent(self):
        from monitor.db import (
            add_account, create_event, insert_videos,
            mark_notify_sent, get_pending_notify_videos,
        )
        aid = add_account(name="N", channel_url="@n", api_key_env="K")
        eid = create_event(aid, "N")
        insert_videos([
            {"video_id": "n1", "title": "N1",
             "url": "https://y.be/n1", "published_at": "2024-01-01"},
        ], aid, eid)
        pending = get_pending_notify_videos(eid)
        assert len(pending) == 1
        mark_notify_sent(["n1"])
        pending2 = get_pending_notify_videos(eid)
        assert len(pending2) == 0


class TestAppState:
    def test_scheduler_state(self):
        from monitor.db import get_scheduler_state, set_scheduler_state
        state = get_scheduler_state()
        assert state["running"] is False
        set_scheduler_state({"running": True, "started_at": "2024-01-01T00:00:00"})
        state2 = get_scheduler_state()
        assert state2["running"] is True

    def test_api_token(self):
        from monitor.db import get_api_token, set_api_token
        token = get_api_token()
        assert len(token) == 40
        set_api_token("custom_token_123")
        assert get_api_token() == "custom_token_123"


class TestAccountStats:
    def test_stats(self):
        from monitor.db import (
            add_account, create_event, finish_event, get_account_stats,
        )
        aid = add_account(name="St", channel_url="@st", api_key_env="K")
        eid = create_event(aid, "St")
        finish_event(eid, "success", total_videos=5, new_videos=2)
        stats = get_account_stats()
        assert len(stats) >= 1
        st = next(s for s in stats if s["id"] == aid)
        assert st["total_scans"] == 1
        assert st["total_new_videos"] == 2


# ── cache.py ─────────────────────────────────────────────────────

class TestCache:
    def test_save_and_get(self):
        from monitor.cache import save_channel_meta, get_channel_meta
        save_channel_meta("MrBeast", "UCxxxxxxx", channel_name="MrBeast")
        meta = get_channel_meta("@MrBeast")
        assert meta is not None
        assert meta["channel_id"] == "UCxxxxxxx"

    def test_delete(self):
        from monitor.cache import save_channel_meta, delete_channel_meta, get_channel_meta
        save_channel_meta("DelTest", "UCdel")
        assert delete_channel_meta("DelTest") is True
        assert get_channel_meta("DelTest") is None

    def test_list_and_clear(self):
        from monitor.cache import save_channel_meta, list_all_cache, clear_all_cache
        save_channel_meta("A", "UC_A")
        save_channel_meta("B", "UC_B")
        assert len(list_all_cache()) >= 2
        cleared = clear_all_cache()
        assert cleared >= 2
        assert len(list_all_cache()) == 0


# ── quota.py ─────────────────────────────────────────────────────

class TestQuota:
    def test_incr_and_get(self):
        from monitor.quota import incr, get_usage
        incr("AIza_q", calls=5, scans=1)
        usage = get_usage("AIza_q")
        assert usage["api_calls"] == 5
        assert usage["scans_done"] == 1

        # 第二次增量
        incr("AIza_q", calls=3, scans=1)
        usage2 = get_usage("AIza_q")
        assert usage2["api_calls"] == 8
        assert usage2["scans_done"] == 2

    def test_incr_blocked(self):
        from monitor.quota import incr_blocked, get_usage
        incr_blocked("AIza_b")
        usage = get_usage("AIza_b")
        assert usage["blocked_scans"] == 1

    def test_check_budget(self):
        from monitor.quota import incr, check_budget
        incr("AIza_budget", calls=100)
        allowed, usage = check_budget("AIza_budget", budget=200)
        assert allowed is True
        incr("AIza_budget", calls=150)
        allowed2, _ = check_budget("AIza_budget", budget=200)
        assert allowed2 is False

    def test_get_all_usage(self):
        from monitor.quota import incr, get_all_usage
        incr("key_all_1", calls=10)
        incr("key_all_2", calls=20)
        all_usage = get_all_usage()
        assert len(all_usage) >= 2
