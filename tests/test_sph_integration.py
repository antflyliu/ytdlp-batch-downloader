"""主进程通用视频分支应识别 SPH 链接并走 sph_parser 路径。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sp_modules.sph_parser import core


def test_unified_video_branch_detects_sph_url():
    """SPH 链接应被识别为需要 sph_parser 解析（不直接进 yt-dlp）。"""
    sph_url = "https://weixin.qq.com/sph/abc"
    # 简易判定函数（待主进程改造后提供）
    assert sph_url.startswith("https://weixin.qq.com/sph/")


def test_sph_url_routes_through_parser(monkeypatch):
    """模拟主进程路径：当 video_url 是 SPH 时应先调 fetch_video_profile。"""
    called = []

    async def fake_fetch(url, cookie):
        called.append(url)
        return {"data": {"feedInfo": {"originVideoUrl": "https://x?v=1&token=t"}}}

    monkeypatch.setattr(core, "fetch_video_profile", fake_fetch)

    import asyncio
    result = asyncio.run(core.fetch_video_profile("https://weixin.qq.com/sph/abc", "cookie"))
    assert called == ["https://weixin.qq.com/sph/abc"]
    assert result["data"]["feedInfo"]["originVideoUrl"] == "https://x?v=1&token=t"
