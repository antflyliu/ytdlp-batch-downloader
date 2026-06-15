"""sph_parser/core.py 单元测试（mock httpx，不调真实微信 API）。"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


@pytest.mark.asyncio
async def test_fetch_video_profile_calls_parse_then_feed(monkeypatch):
    """fetch_video_profile 应串行：parse_share_url → get_feed_info → clean_video_url。"""
    calls = []

    async def fake_parse(share_url, cookie):
        calls.append(("parse", share_url, cookie))
        from server.sp_modules.sph_parser.schemas import ParseData, ParseResponse
        return ParseResponse(data=ParseData(
            wx_export_id="ignored",
            playable_url="https://x/?token=tk123&eid=exp456",
        ))

    async def fake_feed(export_id, general_token):
        calls.append(("feed", export_id, general_token))
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

    result = await core.fetch_video_profile("https://weixin.qq.com/sph/xxx", "cookie")
    assert calls[0][0] == "parse"
    assert calls[1] == ("feed", "exp456", "tk123")
    assert result["data"]["feedInfo"]["originVideoUrl"] == "https://x/?encfilekey=ENC&token=TK"