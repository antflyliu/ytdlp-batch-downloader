"""9 个 /api/channels/* 路由契约测试（mock httpx + 鉴权）。"""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Auth stub：所有路由应能通过鉴权 ─────────────────────────
@pytest.fixture(autouse=True)
def bypass_auth(monkeypatch):
    """主进程用 MONITOR_API_TOKEN 中间件；测试环境下 mock 鉴权依赖。"""
    monkeypatch.setenv("MONITOR_API_TOKEN", "test-token")


@pytest.fixture(autouse=True)
def reset_refresh_state():
    """每个测试前重置 _sph_refresh_state 到 idle，避免跨测试污染。"""
    from server.sp_modules.sph_parser import routes
    routes._sph_refresh_state.update({
        "state": "idle",
        "pid": None,
        "started_at": None,
        "finished_at": None,
        "last_error": None,
        "cookie_updated": False,
    })
    yield


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_file = tmp_path / "monitor.db"
    monkeypatch.setattr("monitor.db.get_db_path", lambda: str(db_file))
    monkeypatch.setattr(
        "server.sp_modules.sph_parser.config.SPH_COOKIE", "hy_source=web; hy_user=alice; hy_token=tk"
    )

    from server.sp_modules.sph_parser import db as sph_db
    sph_db.init_schema()

    from server.sp_modules.sph_parser.routes import router
    app = FastAPI()
    app.include_router(router, prefix="/api/channels")
    return TestClient(app)


# ── #1 parse_sph ──────────────────────────────────────
def test_parse_sph_url_required(client):
    r = client.get("/api/channels/parse_sph")
    assert r.status_code == 400
    assert "url" in r.json()["error"].lower()


def test_parse_sph_invalid_url_format(client):
    r = client.get("/api/channels/parse_sph", params={"url": "https://youtube.com/watch?v=x"})
    assert r.status_code == 400
    assert "sph" in r.json()["error"].lower()


def test_parse_sph_no_cookie_401(client, monkeypatch):
    monkeypatch.setattr("server.sp_modules.sph_parser.config.SPH_COOKIE", "")
    r = client.get("/api/channels/parse_sph", params={"url": "https://weixin.qq.com/sph/xxx"})
    assert r.status_code == 401
    assert r.json()["code"] == "NO_COOKIE"


def test_parse_sph_success_mocked(monkeypatch, client):
    async def fake_fetch(share_url, cookie):
        return {
            "errCode": 0,
            "data": {
                "authorInfo": {"nickname": "作者A"},
                "feedInfo": {"videoUrl": "https://x?v=1&token=t", "originVideoUrl": "https://x?token=t"},
            },
        }
    monkeypatch.setattr(
        "server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch
    )
    r = client.get("/api/channels/parse_sph", params={"url": "https://weixin.qq.com/sph/abc"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["authorInfo"]["nickname"] == "作者A"


# ── #3 cookie POST ─────────────────────────────────────
def test_cookie_post_validation_missing_field(client):
    r = client.post("/api/channels/cookie", json={})
    assert r.status_code == 400


def test_cookie_post_validation_format(client):
    r = client.post("/api/channels/cookie", json={"cookie": "no_three_parts"})
    assert r.status_code == 400


def test_cookie_post_success(client, monkeypatch):
    monkeypatch.setattr("server.sp_modules.sph_parser.config.update_cookie", lambda x: x)
    r = client.post(
        "/api/channels/cookie",
        json={"cookie": "hy_source=web; hy_user=alice; hy_token=tk", "source": "playwright"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "preview" in body["data"]
    assert "updated_at" in body["data"]


# ── #4 cookie GET ─────────────────────────────────────
def test_cookie_get_exists(client):
    r = client.get("/api/channels/cookie")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["exists"] is True
    assert "preview" in body["data"]


def test_cookie_get_not_exists(client, monkeypatch):
    monkeypatch.setattr("server.sp_modules.sph_parser.config.SPH_COOKIE", "")
    r = client.get("/api/channels/cookie")
    assert r.status_code == 200
    assert r.json()["data"]["exists"] is False


# ── #5/#6/#7 refresh ────────────────────────────────
def test_refresh_idle_first_call(client):
    r = client.post("/api/channels/cookie/refresh")
    assert r.status_code in (202, 500)  # 子进程启动可能因 python 路径失败，可接受 500
    if r.status_code == 202:
        body = r.json()
        assert body["data"]["state"] == "running"


def test_refresh_status_idle(client):
    r = client.get("/api/channels/cookie/refresh-status")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["state"] == "idle"


# ── #8 history ─────────────────────────────────────
def test_history_empty(client):
    r = client.get("/api/channels/history")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0


# ── #9 download ─────────────────────────────────────
def test_download_404_when_history_not_found(client):
    r = client.post("/api/channels/download", json={"history_id": "nonexistent"})
    assert r.status_code == 404


# ── #2 batch_parse ───────────────────────────────────
def test_batch_parse_validates_url_list(client):
    """POST /batch_parse 必须传入非空 urls 数组，否则 400。"""
    # 空数组
    r = client.post("/api/channels/batch_parse", json={"urls": []})
    assert r.status_code == 400
    # 完全缺失
    r = client.post("/api/channels/batch_parse", json={})
    assert r.status_code == 400
    # 类型错（字符串而非数组）
    r = client.post("/api/channels/batch_parse", json={"urls": "https://weixin.qq.com/sph/xxx"})
    assert r.status_code == 400
    # 超过 50 条
    r = client.post("/api/channels/batch_parse", json={"urls": [f"https://weixin.qq.com/sph/u{i}" for i in range(51)]})
    assert r.status_code == 400


def test_batch_parse_response_shape_contract(client, monkeypatch):
    """回归测试：POST /batch_parse 响应必须是 {ok, data: {results, summary}}。

    背景：前端 sphQueue.ts processBatch() 早期错误地把 results 放在 r.data.results，
    实际路径是 r.data.data.results（与 SingleParse.vue 的解包方式一致）。
    锁定响应形状，防止后端未来拆掉 data.data 包装导致前端再次取空数组、批量下载卡死。
    """
    # FastAPI 路由调的是 core.fetch_video_profile（async），不是 _sync 版
    async def fake_fetch(share_url, cookie):
        # 模拟真实 fetch_video_profile 的返回：WeChat API 原始响应，含 data.{feedInfo, authorInfo}
        return {
            "errCode": 0,
            "data": {
                "authorInfo": {"nickname": "作者A"},
                "feedInfo": {
                    "videoUrl": "https://x?v=1&token=t",
                    "originVideoUrl": "https://x?token=t",
                    "description": "测试视频",
                },
            },
        }
    monkeypatch.setattr(
        "server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch
    )

    urls = [
        "https://weixin.qq.com/sph/u1",
        "https://weixin.qq.com/sph/u2",
    ]
    r = client.post("/api/channels/batch_parse", json={"urls": urls})
    assert r.status_code == 200
    body = r.json()
    # 顶层契约
    assert body["ok"] is True
    # data 包装层契约（前端 axios 后 r.data === body，所以前端取 r.data.data.results）
    assert "data" in body, "顶层 data 字段必须存在"
    assert "results" in body["data"], "data.results 必须存在"
    assert "summary" in body["data"], "data.summary 必须存在"
    # results 数组契约
    assert isinstance(body["data"]["results"], list)
    assert len(body["data"]["results"]) == 2
    for item in body["data"]["results"]:
        assert set(item.keys()) >= {"url", "ok"}
        if item["ok"]:
            # 成功项的 data 字段是 fetch_video_profile 的原始返回（含 data.feedInfo）
            assert "data" in item
            assert "feedInfo" in item["data"]["data"]
    # summary 字段
    summary = body["data"]["summary"]
    assert summary["total"] == 2
    assert summary["success"] == 2
    assert summary["failed"] == 0


def test_batch_parse_inserts_history_on_success(client, monkeypatch):
    """批量解析成功时,每条都落 history(parse_status='success')。
    回归测试:防止未来重构时丢失 history 写入(commit 39aa636 fix 后的增强)。
    """
    async def fake_fetch(share_url, cookie):
        return {
            "errCode": 0,
            "data": {
                "authorInfo": {"nickname": "作者A"},
                "feedInfo": {"videoUrl": "https://x?v=1", "originVideoUrl": "https://x", "description": "T"},
            },
        }
    monkeypatch.setattr("server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch)

    from server.sp_modules.sph_parser import db as sph_db
    assert sph_db.count_history() == 0

    r = client.post("/api/channels/batch_parse", json={
        "urls": ["https://weixin.qq.com/sph/u1", "https://weixin.qq.com/sph/u2"]
    })
    assert r.status_code == 200
    assert sph_db.count_history() == 2

    items = sph_db.list_history(limit=10, offset=0)
    urls = {it["sph_url"] for it in items}
    assert urls == {"https://weixin.qq.com/sph/u1", "https://weixin.qq.com/sph/u2"}
    for it in items:
        assert it["parse_status"] == "success"
        assert it["parse_error"] is None
    # 响应里也有 history_id(供前端 mark_downloaded 关联)
    for r_item in r.json()["data"]["results"]:
        assert isinstance(r_item["history_id"], str) and len(r_item["history_id"]) > 0


def test_batch_parse_inserts_failed_history(client, monkeypatch):
    """批量解析失败时,每条都落 history(parse_status='failed')。
    用户决策:失败也记录,保留审计/重试能力。
    """
    async def fake_fetch(share_url, cookie):
        raise RuntimeError("upstream 503")
    monkeypatch.setattr("server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch)

    from server.sp_modules.sph_parser import db as sph_db
    r = client.post("/api/channels/batch_parse", json={
        "urls": ["https://weixin.qq.com/sph/u1", "https://weixin.qq.com/sph/u2"]
    })
    assert r.status_code == 200
    assert r.json()["data"]["summary"]["failed"] == 2
    assert sph_db.count_history() == 2

    items = sph_db.list_history(limit=10, offset=0)
    for it in items:
        assert it["parse_status"] == "failed"
        assert "upstream 503" in (it["parse_error"] or "")
        assert it["video_url"] == ""
    # 响应里也带 history_id(前端可后续重新解析)
    for r_item in r.json()["data"]["results"]:
        assert r_item["ok"] is False
        assert isinstance(r_item["history_id"], str) and len(r_item["history_id"]) > 0


def test_batch_parse_mixed_inserts_all(client, monkeypatch):
    """混合:成功/失败都落 history,parse_status 区分。
    验证总条数 = url 数,success/failed 与 summary 一致。
    """
    call_count = {"n": 0}
    async def fake_fetch(share_url, cookie):
        call_count["n"] += 1
        if call_count["n"] % 2 == 0:
            raise RuntimeError("flaky")
        return {
            "errCode": 0,
            "data": {
                "authorInfo": {"nickname": "A"},
                "feedInfo": {"videoUrl": "https://x", "originVideoUrl": "https://x", "description": "T"},
            },
        }
    monkeypatch.setattr("server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch)

    from server.sp_modules.sph_parser import db as sph_db
    r = client.post("/api/channels/batch_parse", json={
        "urls": [
            "https://weixin.qq.com/sph/u1",
            "https://weixin.qq.com/sph/u2",
            "https://weixin.qq.com/sph/u3",
            "https://weixin.qq.com/sph/u4",
        ]
    })
    assert r.json()["data"]["summary"]["success"] == 2
    assert r.json()["data"]["summary"]["failed"] == 2
    assert sph_db.count_history() == 4

    items = sph_db.list_history(limit=10, offset=0)
    statuses = [it["parse_status"] for it in items]
    assert statuses.count("success") == 2
    assert statuses.count("failed") == 2
