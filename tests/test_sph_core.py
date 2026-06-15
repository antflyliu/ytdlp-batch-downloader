"""sph_parser/core.py 单元测试（mock httpx，不调真实微信 API）。"""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sp_modules.sph_parser import core


def test_generate_rid_format():
    """rid 格式：hex 时间戳（8+ 位） + '-' + 8 位 hex。"""
    rid = core.generate_rid()
    assert re.match(r"^[0-9a-f]+-[0-9a-f]{8}$", rid), f"bad rid: {rid!r}"


def test_clean_video_url_keeps_encfilekey_and_token():
    """清洗后 URL 只保留 encfilekey + token 两个 query 参数。"""
    raw = (
        "https://finder-video.qq.com/stream?"
        "encfilekey=ABC123&token=XYZ789&other_garbage=rm&extra=junk"
    )
    cleaned = core.clean_video_url(raw)
    assert "encfilekey=ABC123" in cleaned
    assert "token=XYZ789" in cleaned
    assert "other_garbage" not in cleaned
    assert "extra" not in cleaned
    assert cleaned.startswith("https://finder-video.qq.com/stream?")


def test_clean_video_url_empty_returns_empty():
    assert core.clean_video_url("") == ""
    assert core.clean_video_url(None) == ""


def test_clean_video_url_missing_required_param_returns_empty():
    """缺少 encfilekey 或 token 时返回空串（避免返回不完整 URL）。"""
    assert core.clean_video_url("https://x.com/?token=only") == ""
    assert core.clean_video_url("https://x.com/?encfilekey=only") == ""


def test_fetch_video_profile_calls_parse_then_feed(monkeypatch):
    """fetch_video_profile 应串行：parse_share_url 必须 await 完成后才能 get_feed_info。"""
    parse_finished = []
    feed_started = []

    async def fake_parse(share_url, cookie):
        from server.sp_modules.sph_parser.schemas import ParseData, ParseResponse
        # 模拟一次真实的 await
        await asyncio.sleep(0)
        parse_finished.append(True)
        return ParseResponse(data=ParseData(
            wx_export_id="ignored",
            playable_url="https://x/?token=tk123&eid=exp456",
        ))

    async def fake_feed(export_id, general_token):
        feed_started.append(parse_finished[-1] if parse_finished else False)
        return {
            "errCode": 0,
            "errMsg": "ok",
            "data": {
                "feedInfo": {"videoUrl": "https://x/?encfilekey=ENC&token=TK&junk=rm"},
                "authorInfo": {},
            },
        }

    monkeypatch.setattr(core, "parse_share_url", fake_parse)
    monkeypatch.setattr(core, "get_feed_info", fake_feed)

    result = asyncio.run(core.fetch_video_profile("https://weixin.qq.com/sph/xxx", "cookie"))
    # 串行契约：feed 开始时 parse 必须已 finished
    assert feed_started == [True], f"parse 未在 feed 之前完成: {feed_started=}, {parse_finished=}"
    assert result["data"]["feedInfo"]["originVideoUrl"] == "https://x/?encfilekey=ENC&token=TK"
