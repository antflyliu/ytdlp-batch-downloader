"""SPH cookie 自动刷新子进程。

环境变量（必填）：
- SPH_CALLBACK_URL: 主进程接收 cookie 的端点（http://127.0.0.1:8765/api/channels/cookie）
- SPH_API_TOKEN: 主进程的 MONITOR_API_TOKEN（Bearer auth）

工作流：
1. 启动 Playwright Chromium（headed 模式）
2. 加载 storage_state（若存在）
3. 导航到 yuanbao.tencent.com
4. 等待用户登录（若未登录）
5. 监听 network 响应捕获 hy_user cookie
6. 拼 cookie 字符串
7. POST {SPH_CALLBACK_URL} 写回主进程
8. 保存 storage_state（下次复用）
9. 返回 0
"""
import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sph-refresher] %(message)s")
logger = logging.getLogger("sph-refresher")


def get_storage_state_path() -> Path:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = project_root / "data" / "sph"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "yuanbao_storage.json"


def extract_cookie_from_context(context) -> str | None:
    """从 BrowserContext 提取 hy_source + hy_user + hy_token 三段。"""
    cookies = context.cookies()
    cookie_map = {c["name"]: c["value"] for c in cookies}
    for key in ("hy_source", "hy_user", "hy_token"):
        if key not in cookie_map or not cookie_map[key]:
            logger.warning("[refresh] missing cookie field: %s", key)
            return None
    return f"hy_source={cookie_map['hy_source']}; hy_user={cookie_map['hy_user']}; hy_token={cookie_map['hy_token']}"


def post_cookie_to_main(callback_url: str, api_token: str, cookie: str) -> bool:
    """通过 POST 写回主进程。"""
    try:
        import urllib.request
        req = urllib.request.Request(
            callback_url,
            data=json.dumps({"cookie": cookie, "source": "playwright"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
            logger.info("[refresh] callback status=%d", resp.status)
            return ok
    except Exception as e:
        logger.error("[refresh] callback failed: %s", e)
        return False


def main() -> int:
    callback_url = os.environ.get("SPH_CALLBACK_URL")
    api_token = os.environ.get("SPH_API_TOKEN", "")
    if not callback_url:
        logger.error("[refresh] SPH_CALLBACK_URL not set")
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("[refresh] playwright not installed. Run: pip install playwright && playwright install chromium")
        return 3

    storage_path = get_storage_state_path()
    logger.info("[refresh] start, storage_state=%s", storage_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 决策 3：headed 模式
        context_args = {}
        if storage_path.exists():
            context_args["storage_state"] = str(storage_path)
        context = browser.new_context(**context_args)
        page = context.new_page()

        try:
            page.goto("https://yuanbao.tencent.com", timeout=30000)
            # 等待用户登录：检测 URL 中出现 chat 或工作台标识
            logger.info("[refresh] please log in to yuanbao.tencent.com in the opened browser...")

            # 等待直到 cookies 中出现 hy_user（最长 5 分钟）
            for i in range(60):
                time.sleep(5)
                cookies = context.cookies()
                if any(c["name"] == "hy_user" and c["value"] for c in cookies):
                    logger.info("[refresh] hy_user cookie detected after %ds", i * 5)
                    break
            else:
                logger.error("[refresh] timeout waiting for login")
                return 4

            cookie_str = extract_cookie_from_context(context)
            if not cookie_str:
                return 5

            # 保存 storage_state
            context.storage_state(path=str(storage_path))

            # 写回主进程
            if post_cookie_to_main(callback_url, api_token, cookie_str):
                logger.info("[refresh] cookie written to main process")
                return 0
            return 6
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
