"""/api/channels/* FastAPI 路由。

9 个端点（详见 Spec §3）：
1. GET  /parse_sph            单链接解析
2. POST /batch_parse          批量解析
3. POST /cookie               更新 cookie
4. GET  /cookie               查询 cookie 状态
5. POST /cookie/refresh       启动 playwright 子进程
6. GET  /cookie/refresh-status 轮询刷新状态
7. POST /cookie/refresh-cancel 取消刷新
8. GET  /history              解析历史
9. POST /download             立即下载
"""
import asyncio
import datetime as dt
import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from server.sp_modules.sph_parser import config as sph_config
from server.sp_modules.sph_parser import core, db as sph_db

logger = logging.getLogger("sph.routes")

router = APIRouter()


# ── 响应辅助 ──────────────────────────────────────────
def ok(data: Any = None) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


def err(status: int, msg: str, code: str | None = None, data: Any = None) -> JSONResponse:
    body = {"ok": False, "error": msg}
    if code:
        body["code"] = code
    if data:
        body["data"] = data
    return JSONResponse(body, status_code=status)


# ── Cookie 状态模块变量（refresh 状态机） ─────────────
_sph_refresh_state: dict = {"state": "idle", "pid": None, "started_at": None, "finished_at": None, "last_error": None, "cookie_updated": False}


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")


def _cookie_preview(plain: str) -> str:
    """截断展示：保留 hy_source=web; 其他字段前 4 字符 + ***。"""
    parts = [p.strip() for p in plain.split(";") if p.strip()]
    preview_parts = []
    for p in parts:
        key, _, val = p.partition("=")
        if key == "hy_source":
            preview_parts.append(f"{key}={val}")
        elif val:
            preview_parts.append(f"{key}={val[:4]}***")
    return "; ".join(preview_parts)


# ── #1 GET /parse_sph ─────────────────────────────────
@router.get("/parse_sph")
async def api_parse_sph(url: str = Query("")):
    if not url or not url.strip():
        return err(400, "url parameter is required")
    if not url.startswith("https://weixin.qq.com/sph/"):
        return err(400, "invalid sph url, must start with https://weixin.qq.com/sph/")

    cookie = sph_config.get_cookie()
    if not cookie:
        return err(401, "cookie not configured", code="NO_COOKIE")

    try:
        feed_resp = await asyncio.wait_for(core.fetch_video_profile(url, cookie), timeout=30)
        logger.info("[api_parse_sph] feed_resp: %s", feed_resp)
    except asyncio.TimeoutError:
        return err(504, "timeout", code="TIMEOUT")
    except Exception as e:
        logger.error("[parse_sph] %s", e)
        msg = str(e)
        if "parseShareUrl" in msg:
            return err(502, f"yuanbao parse failed: {msg}", code="PARSE_FAILED")
        if "getFeedInfo" in msg:
            return err(502, f"feed info fetch failed: {msg}", code="FEED_FAILED")
        return err(502, f"parse failed: {msg}")

    # 落 history
    feed_info = feed_resp.get("data", {}).get("feedInfo", {})
    logger.info("[api_parse_sph] feed_info: %s", feed_info)
    author_info = feed_resp.get("data", {}).get("authorInfo", {})
    logger.info("[api_parse_sph] author_info: %s", author_info)
    history_item = {
        "id": str(uuid.uuid4()),
        "sph_url": url,
        "video_title": feed_info.get("description", ""),
        "author_nickname": author_info.get("nickname", ""),
        "cover_url": feed_info.get("coverUrl", ""),
        "video_url": feed_info.get("originVideoUrl", ""),
        "description": feed_info.get("description", ""),
        "downloaded": False,
        "downloaded_path": None,
        "parse_status": "success",
        "parse_error": None,
    }
    try:
        sph_db.insert_history(history_item)
    except Exception as e:
        logger.warning("[parse_sph] history insert failed: %s", e)

    return ok({"authorInfo": author_info, "feedInfo": feed_info})


# ── #2 POST /batch_parse ─────────────────────────────
@router.post("/batch_parse")
async def api_batch_parse(body: dict):
    urls = body.get("urls")
    if not isinstance(urls, list) or not urls:
        return err(400, "urls must be a non-empty array")
    if len(urls) > 50:
        return err(400, "urls length exceeds 50")

    max_concurrent = min(int(body.get("max_concurrent", 3)), 10)
    sem = asyncio.Semaphore(max_concurrent)

    async def one(u: str) -> dict:
        async with sem:
            try:
                r = await asyncio.wait_for(core.fetch_video_profile(u, sph_config.get_cookie()), timeout=30)
                return {"url": u, "ok": True, "data": r}
            except Exception as e:
                return {"url": u, "ok": False, "error": str(e)}

    results = await asyncio.gather(*(one(u) for u in urls))
    summary = {"total": len(results), "success": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}
    return ok({"results": results, "summary": summary})


# ── #3 POST /cookie ─────────────────────────────────
@router.post("/cookie")
async def api_cookie_post(body: dict):
    cookie = body.get("cookie", "").strip()
    if not cookie:
        return err(400, "cookie field is required")
    if len(cookie) > 4096:
        return err(400, "cookie too long, max 4096 chars")
    parts = {p.split("=", 1)[0].strip(): p.split("=", 1)[1].strip() for p in cookie.split(";") if "=" in p}
    if "hy_source" not in parts or "web" not in parts["hy_source"]:
        return err(400, "invalid format: hy_source must contain 'web'")
    if not parts.get("hy_user") or not parts.get("hy_token"):
        return err(400, "invalid format: hy_user and hy_token required")
    sph_config.update_cookie(cookie)
    return ok({"updated_at": _now_iso(), "preview": _cookie_preview(cookie)})


# ── #4 GET /cookie ──────────────────────────────────
@router.get("/cookie")
async def api_cookie_get():
    plain = sph_config.get_cookie()
    if not plain:
        return ok({"exists": False, "source": None, "age_seconds": None, "preview": None})
    return ok({
        "exists": True,
        "source": "manual",  # 简化：get_sph_cookie 不返回 source；可后续扩展
        "age_seconds": None,
        "preview": _cookie_preview(plain),
    })


# ── #5 POST /cookie/refresh ─────────────────────────
@router.post("/cookie/refresh")
async def api_cookie_refresh():
    if _sph_refresh_state["state"] == "running":
        return err(409, "refresh already running", data={"state": "running", "pid": _sph_refresh_state["pid"]})

    callback_url = os.environ.get("SPH_REFRESH_CALLBACK_URL", "http://127.0.0.1:8765/api/channels/cookie")
    api_token = os.environ.get("MONITOR_API_TOKEN", "")

    project_root = Path(__file__).resolve().parents[3]
    script_path = project_root / "scripts" / "sph_cookie_refresher.py"
    if not script_path.exists():
        return err(500, f"refresher script not found: {script_path}")

    env = {**os.environ, "SPH_CALLBACK_URL": callback_url, "SPH_API_TOKEN": api_token}
    try:
        proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            env=env,
            stdout=subprocess.DEVNULL,  # 修复: 避免 pipe buffer 满后子进程阻塞
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return err(500, f"failed to start refresher: {e}")

    _sph_refresh_state.update({
        "state": "running",
        "pid": proc.pid,
        "started_at": _now_iso(),
        "finished_at": None,
        "last_error": None,
        "cookie_updated": False,
    })
    # 修复: 后台 watcher 轮询子进程退出，自动 transition 状态
    asyncio.create_task(_watch_refresh_subprocess(proc))
    from fastapi.responses import JSONResponse
    return JSONResponse({"ok": True, "data": {"state": "running", "pid": proc.pid, "started_at": _sph_refresh_state["started_at"]}}, status_code=202)


async def _watch_refresh_subprocess(proc: subprocess.Popen) -> None:
    """后台 task：轮询子进程退出并更新 _sph_refresh_state。

    子进程通过 HTTP POST {SPH_CALLBACK_URL} 写回 cookie，所以这里只需要
    关心退出码（0 = success, 非 0 = failed）。
    """
    loop = asyncio.get_event_loop()
    try:
        returncode = await loop.run_in_executor(None, proc.wait)
        _sph_refresh_state["state"] = "success" if returncode == 0 else "failed"
        _sph_refresh_state["finished_at"] = _now_iso()
        if returncode != 0:
            _sph_refresh_state["last_error"] = f"refresher exited with code {returncode}"
    except Exception as e:
        _sph_refresh_state["state"] = "failed"
        _sph_refresh_state["finished_at"] = _now_iso()
        _sph_refresh_state["last_error"] = f"watcher error: {e}"


# ── #6 GET /cookie/refresh-status ───────────────────
@router.get("/cookie/refresh-status")
async def api_cookie_refresh_status():
    return ok(_sph_refresh_state)


# ── #7 POST /cookie/refresh-cancel ──────────────────
@router.post("/cookie/refresh-cancel")
async def api_cookie_refresh_cancel():
    if _sph_refresh_state["state"] != "running":
        return err(409, "no refresh running")
    pid = _sph_refresh_state["pid"]
    try:
        import signal
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as e:
        logger.warning("[cancel] kill failed: %s", e)
    _sph_refresh_state.update({"state": "idle", "pid": None, "finished_at": _now_iso()})
    return ok({"cancelled": True, "pid": pid})


# ── #8 GET /history ─────────────────────────────────
@router.get("/history")
async def api_history(limit: int = 20, offset: int = 0, keyword: str | None = None):
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    items = sph_db.list_history(limit=limit, offset=offset, keyword=keyword)
    total = sph_db.count_history(keyword=keyword)
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})


# ── #9 POST /download ───────────────────────────────
@router.post("/download")
async def api_download(body: dict):
    """触发下载（仅解析 + 落 history；实际 yt-dlp 由 server/__main__.py 集成，本路由暂未提供）。

    当前实现：解析 + 落 history 后返回 202 + task_id。
    调用方应轮询 /api/download-tasks/{id} 获取进度（待 Task 3.4 集成）。
    """
    history_id = body.get("history_id")
    sph_url = body.get("sph_url")
    quality = body.get("quality", "best")
    sub_langs = body.get("sub_langs", "zh-Hans,en")

    if not history_id and not sph_url:
        return err(400, "history_id or sph_url required")

    if history_id:
        item = sph_db.get_history(history_id)
        if not item:
            return err(404, f"history_id not found: {history_id}")
        video_url = item["video_url"]
    else:
        try:
            feed_resp = await asyncio.wait_for(
                core.fetch_video_profile(sph_url, sph_config.get_cookie()),
                timeout=30,
            )
            video_url = feed_resp.get("data", {}).get("feedInfo", {}).get("originVideoUrl", "")
        except Exception as e:
            return err(502, f"parse failed: {e}")
        if not video_url:
            return err(502, "no originVideoUrl in parse result")

    task_id = str(uuid.uuid4())
    # 记录到 history（download 触发时间）
    try:
        sph_db.insert_history({
            "id": task_id,
            "sph_url": history_id and sph_db.get_history(history_id)["sph_url"] or sph_url,
            "video_title": "",
            "author_nickname": "",
            "cover_url": "",
            "video_url": video_url,
            "description": "",
            "downloaded": False,
            "downloaded_path": None,
            "parse_status": "queued",
            "parse_error": None,
        })
    except Exception as e:
        logger.warning("[download] history insert failed: %s", e)

    return ok({
        "task_id": task_id,
        "state": "queued",
        "video_url": video_url,
        "output_path": "",  # 由 server/__main__.py 集成后填充
    })
