"""SPH 核心业务逻辑 — 移植自 wx-sph-parser/app/sph.py。

两步串行流程：
1. parse_share_url → 调 yuanbao API 解析分享链接，获取 playable_url（含 token + eid）
2. get_feed_info   → 调微信视频号 API 获取视频详情

最后一步从 videoUrl 中清洗出 encfilekey + token 作为 originVideoUrl。
"""
import logging
import random
import re
import string
import time
from urllib.parse import parse_qs, quote, urlencode, urlparse

import httpx

from server.sp_modules.sph_parser.schemas import ParseData, ParseResponse

logger = logging.getLogger("sph.core")

# ── 常量（与 wx-sph-parser/app/sph.py 一致） ──────────────────
PARSE_URL = "https://yuanbao.tencent.com/api/weixin/get_parse_result"
FEED_INFO_URL = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"

PARSE_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "content-type": "application/json",
    "origin": "https://yuanbao.tencent.com",
    "referer": "https://yuanbao.tencent.com/chat/naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "t-userid": "b9575f6b0a8c4a55a08096904a5ef20a",
    "x-agentid": "naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
    "x-commit-tag": "72282a0d",
    "x-device-id": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
    "x-hy106": "",
    "x-hy92": "e963067ffa31002b9646bd0c03000008b1951a",
    "x-hy93": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
    "x-id": "b9575f6b0a8c4a55a08096904a5ef20a",
    "x-instance-id": "5",
    "x-language": "zh-CN",
    "x-os_version": "Mac OS(10.15.7)-Blink",
    "x-platform": "mac",
    "x-requested-with": "XMLHttpRequest",
    "x-source": "web",
    "x-web-third-source": "main",
    "x-webdriver": "0",
    "x-webversion": "2.69.0",
    "x-ybuitest": "0",
}

FEED_INFO_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Origin": "https://channels.weixin.qq.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}


def generate_rid() -> str:
    """生成请求 ID：时间戳十六进制 + 8 位随机 hex — 对应 Go generateRid()。"""
    timestamp_hex = format(int(time.time()), "x")
    random_hex = "".join(random.choices("0123456789abcdef", k=8))
    return f"{timestamp_hex}-{random_hex}"


async def parse_share_url(share_url: str, cookie: str) -> ParseResponse:
    """调 yuanbao API 解析 SPH 分享链接，对应 Go parseShareUrl()。

    返回含 wx_export_id + playable_url 等字段的 ParseResponse。
    异步版（保留以兼容 routes.py）；同步调用请用 parse_share_url_sync。
    """
    logger.info("[parseShareUrl] start, url: %s", share_url)

    payload = {"type": "video_channel_url", "url": share_url, "scene": 1}
    headers = {**PARSE_HEADERS, "cookie": cookie}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(PARSE_URL, json=payload, headers=headers)

    if resp.status_code < 200 or resp.status_code >= 300:
        logger.error("[parseShareUrl] http %d", resp.status_code)
        raise RuntimeError(f"parseShareUrl: http {resp.status_code}")

    result = ParseResponse(**resp.json())
    logger.info("[parseShareUrl] ok, exportId: %s", result.data.wx_export_id)
    return result


def parse_share_url_sync(share_url: str, cookie: str) -> ParseResponse:
    """同步版 parse_share_url（推荐在 SimpleHTTPRequestHandler 同步线程中使用）。

    底层用 httpx.Client + anyio.from_thread.run，**不**创建独立 event loop，
    彻底消除 Windows asyncio overlapped pending operation 警告。
    """
    logger.info("[parseShareUrl-sync] start, url: %s", share_url)

    payload = {"type": "video_channel_url", "url": share_url, "scene": 1}
    headers = {**PARSE_HEADERS, "cookie": cookie}

    with httpx.Client(timeout=30) as client:
        resp = client.post(PARSE_URL, json=payload, headers=headers)

    if resp.status_code < 200 or resp.status_code >= 300:
        logger.error("[parseShareUrl-sync] http %d", resp.status_code)
        raise RuntimeError(f"parseShareUrl: http {resp.status_code}")

    result = ParseResponse(**resp.json())
    logger.info("[parseShareUrl-sync] ok, exportId: %s", result.data.wx_export_id)
    return result


async def get_feed_info(export_id: str, general_token: str) -> dict:
    """调微信视频号 API 获取视频详情，对应 Go getFeedInfo()。

    返回微信 API 原始结构 dict，camelCase。
    异步版（保留以兼容 routes.py）；同步调用请用 get_feed_info_sync。
    """
    logger.info("[getFeedInfo] start, exportId: %s", export_id)

    rid = generate_rid()
    payload = {"baseReq": {"generalToken": general_token}, "exportId": export_id}

    api_url = (
        f"{FEED_INFO_URL}"
        f"?_rid={rid}"
        "&_pageUrl=https%3A%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed"
    )
    referer = (
        "https://channels.weixin.qq.com/finder-preview/pages/feed"
        f"?entry_card_type=48&comment_scene=39&appid=0"
        f"&token={quote(general_token)}"
        f"&entry_scene=0&eid={quote(export_id)}"
    )
    headers = {**FEED_INFO_HEADERS, "Referer": referer}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(api_url, json=payload, headers=headers)

    if resp.status_code < 200 or resp.status_code >= 300:
        logger.error("[getFeedInfo] http %d", resp.status_code)
        raise RuntimeError(f"getFeedInfo: http {resp.status_code}")

    result = resp.json()
    logger.info("[getFeedInfo] ok, errCode: %d", result.get("errCode", -1))
    return result


def get_feed_info_sync(export_id: str, general_token: str) -> dict:
    """同步版 get_feed_info（推荐在 SimpleHTTPRequestHandler 同步线程中使用）。

    同 parse_share_url_sync：消除 Windows asyncio cleanup 警告。
    """
    logger.info("[getFeedInfo-sync] start, exportId: %s", export_id)

    rid = generate_rid()
    payload = {"baseReq": {"generalToken": general_token}, "exportId": export_id}

    api_url = (
        f"{FEED_INFO_URL}"
        f"?_rid={rid}"
        "&_pageUrl=https%3A%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed"
    )
    referer = (
        "https://channels.weixin.qq.com/finder-preview/pages/feed"
        f"?entry_card_type=48&comment_scene=39&appid=0"
        f"&token={quote(general_token)}"
        f"&entry_scene=0&eid={quote(export_id)}"
    )
    headers = {**FEED_INFO_HEADERS, "Referer": referer}

    with httpx.Client(timeout=30) as client:
        resp = client.post(api_url, json=payload, headers=headers)

    if resp.status_code < 200 or resp.status_code >= 300:
        logger.error("[getFeedInfo-sync] http %d", resp.status_code)
        raise RuntimeError(f"getFeedInfo: http {resp.status_code}")

    result = resp.json()
    logger.info("[getFeedInfo-sync] ok, errCode: %d", result.get("errCode", -1))
    return result


def clean_video_url(video_url: str | None) -> str:
    """清洗视频 URL：仅保留 encfilekey + token 参数。"""
    if not video_url:
        return ""

    parsed = urlparse(video_url)
    params = parse_qs(parsed.query)
    filekey = params.get("encfilekey", [""])[0]
    token = params.get("token", [""])[0]

    if filekey and token:
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return f"{base}?encfilekey={filekey}&token={token}"

    return ""


async def fetch_video_profile(share_url: str, cookie: str) -> dict:
    """完整两步串行：parse_share_url → get_feed_info → clean_video_url。

    返回微信 API 原始结构 dict，camelCase。
    副作用：在 data.feedInfo 中插入 originVideoUrl（清洗后的视频 URL）。
    异步版（保留以兼容 routes.py）；同步调用请用 fetch_video_profile_sync。
    """
    logger.info("[fetch] start, shareUrl: %s", share_url)

    # Step 1: parse_share_url — 必须 await 完成才能进入 Step 2
    parse_result = await parse_share_url(share_url, cookie)
    if not parse_result.data.wx_export_id:
        raise RuntimeError("parseShareUrl: missing wx_export_id")

    # Step 2: 从 playable_url 提取 token + eid
    general_token = ""
    export_id = ""
    playable_url = parse_result.data.playable_url
    if playable_url:
        playable_parsed = urlparse(playable_url)
        p = parse_qs(playable_parsed.query)
        general_token = p.get("token", [""])[0]
        export_id = p.get("eid", [""])[0]

    if not general_token:
        logger.warning("[fetch] generalToken is empty in playable_url")
    if not export_id:
        logger.warning("[fetch] exportId (eid) is empty in playable_url")

    # Step 3: get_feed_info — 严格在 parse 之后
    feed_result = await get_feed_info(export_id, general_token)

    # Step 4: 清洗 videoUrl，注入 originVideoUrl
    feed_info = feed_result.get("data", {}).get("feedInfo", {})
    video_url = feed_info.get("videoUrl", "")
    if video_url:
        feed_result["data"]["feedInfo"]["originVideoUrl"] = clean_video_url(video_url)

    return feed_result


def fetch_video_profile_sync(share_url: str, cookie: str) -> dict:
    """同步版 fetch_video_profile（推荐在 SimpleHTTPRequestHandler 同步线程中使用）。

    严格串行：parse_share_url_sync → 提取 token/eid → get_feed_info_sync → clean。
    底层用 httpx.Client，**不**创建 event loop，消除 Windows asyncio cleanup 警告。
    """
    logger.info("[fetch-sync] start, shareUrl: %s", share_url)

    # Step 1: parse_share_url_sync
    parse_result = parse_share_url_sync(share_url, cookie)
    if not parse_result.data.wx_export_id:
        raise RuntimeError("parseShareUrl: missing wx_export_id")

    # Step 2: 从 playable_url 提取 token + eid
    general_token = ""
    export_id = ""
    playable_url = parse_result.data.playable_url
    if playable_url:
        playable_parsed = urlparse(playable_url)
        p = parse_qs(playable_parsed.query)
        general_token = p.get("token", [""])[0]
        export_id = p.get("eid", [""])[0]

    if not general_token:
        logger.warning("[fetch-sync] generalToken is empty in playable_url")
    if not export_id:
        logger.warning("[fetch-sync] exportId (eid) is empty in playable_url")

    # Step 3: get_feed_info_sync
    feed_result = get_feed_info_sync(export_id, general_token)

    # Step 4: 清洗 videoUrl，注入 originVideoUrl
    feed_info = feed_result.get("data", {}).get("feedInfo", {})
    video_url = feed_info.get("videoUrl", "")
    if video_url:
        feed_result["data"]["feedInfo"]["originVideoUrl"] = clean_video_url(video_url)

    return feed_result
