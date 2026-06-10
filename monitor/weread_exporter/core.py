from __future__ import annotations

import asyncio
import hashlib
import inspect
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MEASURE_RE = re.compile(r'^[a-zA-Z0-9`~!@#$%^&*()\-_=+\[\]{}|;:\',<.>/?\\"\s]+$')
SENTENCE_END = set("。！？；：」）】》…—")

CANVAS_HOOK = """
(function() {
    window.__wr_chars = [];
    window.__wr_page_marks = [0];

    var orig = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function(text, x, y) {
        if (text && text.trim()) {
            window.__wr_chars.push({
                t: text,
                x: Math.round(x * 10) / 10,
                y: Math.round(y * 10) / 10
            });
        }
        return orig.apply(this, arguments);
    };

    window.__wr_mark = function() {
        window.__wr_page_marks.push(window.__wr_chars.length);
    };

    window.__wr_count = function() {
        return window.__wr_chars.length;
    };
})();
"""

CHROME_CDP_ENDPOINT_ENV = "WEREAD_CHROME_CDP_ENDPOINT"
CHROME_PATH_ENV = "WEREAD_CHROME_PATH"
BROWSER_MODE_ENV = "WEREAD_BROWSER_MODE"
DEFAULT_CHROME_CDP_ENDPOINT = "http://127.0.0.1:9222"
DEFAULT_CHROME_CDP_INITIAL_URL = "https://weread.qq.com/web/shelf"
BROWSER_MODE_AUTO = "auto"
BROWSER_MODE_CHROME_CDP = "chrome_cdp"
BROWSER_MODE_PERSISTENT = "persistent"
BROWSER_MODE_ALIASES = {
    "": BROWSER_MODE_AUTO,
    "auto": BROWSER_MODE_AUTO,
    "cdp": BROWSER_MODE_CHROME_CDP,
    "chrome": BROWSER_MODE_CHROME_CDP,
    "chrome-cdp": BROWSER_MODE_CHROME_CDP,
    "chrome_cdp": BROWSER_MODE_CHROME_CDP,
    "existing_chrome": BROWSER_MODE_CHROME_CDP,
    "persistent": BROWSER_MODE_PERSISTENT,
    "chromium": BROWSER_MODE_PERSISTENT,
    "isolated": BROWSER_MODE_PERSISTENT,
}


class WeReadExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class WeReadExportResult:
    title: str
    author: str
    total: int
    ok: int
    failed: int
    skipped: int
    merged_path: str
    meta_path: str


@dataclass(frozen=True)
class BrowserSession:
    context: Any
    kind: str
    close: Callable[[], Awaitable[None]]


ProgressCallback = Callable[[dict], None]
CancelCheck = Callable[[], bool]


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def normalize_browser_mode(value: str | None) -> str:
    raw = (value or "").strip().lower().replace(" ", "_")
    return BROWSER_MODE_ALIASES.get(raw, BROWSER_MODE_AUTO)


def configured_browser_mode() -> str:
    return normalize_browser_mode(os.environ.get(BROWSER_MODE_ENV))


def configured_chrome_cdp_endpoint() -> str:
    return (os.environ.get(CHROME_CDP_ENDPOINT_ENV) or DEFAULT_CHROME_CDP_ENDPOINT).strip().rstrip("/")


def chrome_cdp_available(endpoint: str | None = None, *, timeout: float = 0.5) -> bool:
    base_url = (endpoint or configured_chrome_cdp_endpoint()).strip().rstrip("/")
    if not base_url:
        return False
    try:
        request = Request(f"{base_url}/json/version", headers={"Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            if getattr(response, "status", 200) >= 400:
                return False
            payload = json.loads(response.read(4096).decode("utf-8", errors="ignore") or "{}")
            return bool(payload.get("Browser") or payload.get("webSocketDebuggerUrl"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError, TimeoutError, ValueError):
        return False


def find_chrome_executable() -> str | None:
    configured = (os.environ.get(CHROME_PATH_ENV) or os.environ.get("CHROME_PATH") or "").strip()
    if configured and Path(configured).is_file():
        return configured

    for name in ("chrome", "chrome.exe", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = [os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")]
    candidates = [
        *(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe" for root in program_files if root),
        Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe" if local_app_data else None,
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return str(candidate)
    return None


def _cdp_port(endpoint: str) -> int:
    parsed = urlparse(endpoint)
    if parsed.port:
        return int(parsed.port)
    return 443 if parsed.scheme == "https" else 80


def launch_chrome_cdp(
    *,
    endpoint: str | None = None,
    profile_dir: str | Path,
    initial_url: str = DEFAULT_CHROME_CDP_INITIAL_URL,
    timeout: float = 8,
) -> dict:
    target_endpoint = (endpoint or configured_chrome_cdp_endpoint()).strip().rstrip("/")
    if chrome_cdp_available(target_endpoint):
        return {
            "ok": True,
            "available": True,
            "started": False,
            "endpoint": target_endpoint,
            "profile_dir": str(Path(profile_dir).expanduser().resolve()),
        }

    chrome_path = find_chrome_executable()
    if not chrome_path:
        return {
            "ok": False,
            "available": False,
            "started": False,
            "endpoint": target_endpoint,
            "profile_dir": str(Path(profile_dir).expanduser().resolve()),
            "error": "未找到 Chrome 可执行文件，可通过 WEREAD_CHROME_PATH 指定 chrome.exe",
        }

    profile_path = Path(profile_dir).expanduser().resolve()
    profile_path.mkdir(parents=True, exist_ok=True)
    port = _cdp_port(target_endpoint)
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_path}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        initial_url,
    ]
    popen_kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    process = subprocess.Popen(args, **popen_kwargs)

    deadline = time.monotonic() + max(timeout, 0)
    while time.monotonic() < deadline:
        if chrome_cdp_available(target_endpoint):
            return {
                "ok": True,
                "available": True,
                "started": True,
                "pid": process.pid,
                "endpoint": target_endpoint,
                "profile_dir": str(profile_path),
            }
        time.sleep(0.25)

    return {
        "ok": False,
        "available": False,
        "started": True,
        "pid": process.pid,
        "endpoint": target_endpoint,
        "profile_dir": str(profile_path),
        "error": "Chrome 已启动，但 CDP 端口暂未响应",
    }


def ensure_chrome_cdp(*, data_dir: str, initial_url: str = DEFAULT_CHROME_CDP_INITIAL_URL) -> dict:
    return launch_chrome_cdp(
        endpoint=configured_chrome_cdp_endpoint(),
        profile_dir=Path(data_dir) / "weread_chrome_cdp_profile",
        initial_url=initial_url,
    )


def ensure_chrome_cdp_with_options(
    *,
    data_dir: str,
    endpoint: str | None = None,
    profile_dir: str | Path | None = None,
    initial_url: str = DEFAULT_CHROME_CDP_INITIAL_URL,
) -> dict:
    return launch_chrome_cdp(
        endpoint=endpoint or configured_chrome_cdp_endpoint(),
        profile_dir=profile_dir or Path(data_dir) / "weread_chrome_cdp_profile",
        initial_url=initial_url,
    )


def wr_hash(value: str) -> str:
    digest = hashlib.md5(value.encode()).hexdigest()
    result = digest[:3] + "32" + digest[-2:]
    chunks = []
    for i in range(0, len(value), 9):
        chunks.append("%x" % int(value[i : min(i + 9, len(value))]))
    for i, chunk in enumerate(chunks):
        width = "%x" % len(chunk)
        if len(width) == 1:
            width = "0" + width
        result += width + chunk
        if i < len(chunks) - 1:
            result += "g"
    if len(result) < 20:
        result += digest[: 20 - len(result)]
    result += hashlib.md5(result.encode()).hexdigest()[:3]
    return result


def parse_book_id(url_or_id: str) -> str:
    raw = (url_or_id or "").strip()
    match = re.search(r"/bookDetail/([^/?#]+)", raw, re.I)
    if match:
        return match.group(1)
    match = re.search(r"/web/reader/([0-9a-z]+)", raw, re.I)
    if match:
        return match.group(1).rsplit("k", 1)[0]
    match = re.search(r"([0-9a-z]{20,})", raw, re.I)
    if match:
        return match.group(1)
    return raw


def split_spread(chars: list[dict]) -> list[list[dict]]:
    if len(chars) < 20:
        return [chars]
    singles = [(i, c) for i, c in enumerate(chars) if len(str(c.get("t") or "")) == 1]
    if len(singles) < 10:
        return [chars]
    for index in range(1, len(singles)):
        prev_y = float(singles[index - 1][1].get("y") or 0)
        curr_y = float(singles[index][1].get("y") or 0)
        if prev_y > 400 and curr_y < 200:
            cut_idx = singles[index][0]
            return [chars[:cut_idx], chars[cut_idx:]]
    return [chars]


def reconstruct_page(chars: list[dict]) -> str:
    if not chars:
        return ""
    real = [c for c in chars if len(str(c.get("t") or "")) == 1 or not MEASURE_RE.match(str(c.get("t") or ""))]
    if not real:
        return ""
    rows: dict[int, list[dict]] = {}
    for char in real:
        y_key = round(float(char.get("y") or 0) / 3) * 3
        rows.setdefault(y_key, []).append(char)
    lines = []
    for y_key in sorted(rows):
        sorted_chars = sorted(rows[y_key], key=lambda c: float(c.get("x") or 0))
        line = "".join(str(c.get("t") or "") for c in sorted_chars)
        if line.strip():
            lines.append(line.strip())
    return "\n".join(lines)


def clean_text(raw_text: str, chapter_title: str) -> str:
    lines = raw_text.split("\n")
    cleaned = []
    title_seen = False
    for line in lines:
        text = line.strip()
        if not title_seen and text == chapter_title:
            title_seen = True
            continue
        cleaned.append(text)

    paragraphs = []
    current = []
    for line in cleaned:
        if not line:
            if current:
                paragraphs.append("".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("".join(current))

    merged = []
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        if merged and merged[-1] and merged[-1][-1] not in SENTENCE_END:
            merged[-1] += paragraph
        else:
            merged.append(paragraph)
    return "\n\n".join(merged)


def safe_filename(value: str, *, fallback: str = "book", max_length: int = 90) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (value or "").strip())
    safe = re.sub(r"\s+", " ", safe).strip(" .")
    return (safe[:max_length].rstrip(" .") or fallback)


class WeReadPlaywrightRunner:
    def __init__(
        self,
        *,
        progress: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        browser_mode: str | None = None,
        chrome_cdp_endpoint: str | None = None,
    ):
        self.progress = progress or (lambda _event: None)
        self.cancel_check = cancel_check or (lambda: False)
        self.browser_mode = normalize_browser_mode(browser_mode or configured_browser_mode())
        self.chrome_cdp_endpoint = (chrome_cdp_endpoint or configured_chrome_cdp_endpoint()).rstrip("/")

    def _progress(self, **event) -> None:
        self.progress(event)

    def _cancel_if_requested(self) -> None:
        if self.cancel_check():
            raise WeReadExportError("任务已取消")

    def _weread_api_headers(self) -> dict:
        return {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://weread.qq.com",
            "Referer": "https://weread.qq.com/web/shelf",
        }

    def _weread_web_headers(self, referer: str = "https://weread.qq.com/web/shelf") -> dict:
        return {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://weread.qq.com",
            "Referer": referer,
        }

    async def _web_session_user_vid(self, context) -> str:
        cookies_getter = getattr(context, "cookies", None)
        if cookies_getter is None:
            return ""
        try:
            cookies = cookies_getter("https://weread.qq.com")
            if inspect.isawaitable(cookies):
                cookies = await cookies
        except Exception:
            return ""
        for cookie in cookies or []:
            if isinstance(cookie, dict) and cookie.get("name") == "wr_vid":
                return str(cookie.get("value") or "").strip()
        return ""

    async def _web_session_valid(self, context) -> bool | None:
        request_context = getattr(context, "request", None)
        if request_context is None:
            return None
        user_vid = await self._web_session_user_vid(context)
        if not user_vid:
            return False
        try:
            response = await request_context.get(
                f"https://weread.qq.com/web/user?userVid={quote(user_vid, safe='')}",
                headers=self._weread_web_headers(),
            )
        except Exception:
            return None
        status = getattr(response, "status", None)
        if status in {401, 403}:
            return False
        if not bool(getattr(response, "ok", False)):
            return None
        try:
            payload = response.json()
            if inspect.isawaitable(payload):
                payload = await payload
        except Exception:
            return True
        if isinstance(payload, dict) and payload.get("errcode"):
            return False
        return True

    async def _book_info_session_valid(self, context, book_id: str | None) -> bool | None:
        return await self._web_session_valid(context)

    def _web_book_id_candidates(self, page_meta: dict | None, reader_book_id: str) -> list[str]:
        values: list[Any] = []
        if isinstance(page_meta, dict):
            raw_candidates = page_meta.get("webBookIds")
            if isinstance(raw_candidates, list):
                values.extend(raw_candidates)
            values.append(page_meta.get("webBookId"))
        values.append(reader_book_id)

        candidates: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            text = text.split("?", 1)[0].split("#", 1)[0]
            if re.fullmatch(r"[0-9a-z]+k[0-9a-z]+", text, re.I):
                text = text.rsplit("k", 1)[0]
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(text)
        return candidates

    async def ensure_login(self, context, book_id: str | None = None) -> bool:
        self._progress(current="正在检查微信读书登录状态")
        login_status = await self._book_info_session_valid(context, book_id)
        if login_status is True:
            self._progress(current="微信读书已登录")
            return True

        page = await context.new_page()
        try:
            try:
                await page.goto("https://weread.qq.com/web/shelf", wait_until="domcontentloaded", timeout=30000)
            except Exception:
                login_status = await self._book_info_session_valid(context, book_id)
                if login_status is True:
                    self._progress(current="微信读书已登录")
                    return True
                raise
            await asyncio.sleep(3)
            login_status = await self._book_info_session_valid(context, book_id)
            if login_status is False or "login" in page.url.lower():
                self._progress(current="请在弹出的调试 Chrome 窗口中重新登录微信读书")
                try:
                    await page.goto("https://weread.qq.com/web/login", wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    await page.goto("https://weread.qq.com/#login", wait_until="domcontentloaded", timeout=30000)
                for _ in range(120):
                    self._cancel_if_requested()
                    await asyncio.sleep(5)
                    login_status = await self._book_info_session_valid(context, book_id)
                    if login_status is True or (login_status is None and "login" not in page.url.lower()):
                        self._progress(current="微信读书登录成功")
                        return True
                return False
            self._progress(current="微信读书已登录")
            return True
        finally:
            await page.close()

    async def fetch_book_meta(self, context, book_id: str) -> dict | None:
        web_error: WeReadExportError | None = None
        try:
            return await self._fetch_book_meta_via_web_reader(context, book_id)
        except WeReadExportError as exc:
            web_error = exc
            self._progress(current="当前网页接口未返回完整元数据，尝试旧版微信读书接口")
        except Exception as exc:
            web_error = WeReadExportError(str(exc))
            self._progress(current="当前网页接口读取异常，尝试旧版微信读书接口")

        request_error: WeReadExportError | None = None
        try:
            request_context = getattr(context, "request", None)
            if request_context is not None:
                try:
                    return await self._fetch_book_meta_via_request(request_context, book_id)
                except WeReadExportError as exc:
                    request_error = exc
                    self._progress(current="API 请求未获得可用微信读书登录态，改用页面会话读取元数据")
            return await self._fetch_book_meta_via_page(context, book_id)
        except WeReadExportError as exc:
            if request_error is not None:
                prefix = f"{web_error}；" if web_error else ""
                raise WeReadExportError(f"{prefix}{request_error}；页面会话读取也失败：{exc}") from exc
            raise
        except Exception as exc:
            if request_error is not None:
                prefix = f"{web_error}；" if web_error else ""
                raise WeReadExportError(
                    f"{prefix}{request_error}；页面会话读取也失败：{exc}。请在调试 Chrome 窗口重新登录微信读书后重试。"
                ) from exc
            raise WeReadExportError(
                f"读取微信读书元数据失败：{exc}。请确认调试 Chrome 中已登录微信读书且网络可访问 i.weread.qq.com。"
            ) from exc

    async def _fetch_book_meta_via_web_reader(self, context, reader_book_id: str) -> dict:
        page = await context.new_page()
        reader_url = f"https://weread.qq.com/web/reader/{reader_book_id}"
        try:
            await page.goto(reader_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            page_meta = await page.evaluate(
                """
                () => {
                    const metaContent = (selector) => {
                        const el = document.querySelector(selector);
                        return el ? (el.getAttribute('content') || '') : '';
                    };
                    const ogImage = metaContent('meta[property="og:image"]');
                    const scriptsAndResources = [
                        ...performance.getEntriesByType('resource').map((entry) => entry.name),
                        location.href,
                        ogImage,
                    ];
                    const candidates = [];
                    const seen = new Set();
                    const addCandidate = (value, score) => {
                        let id = String(value || '').trim();
                        if (!id) {
                            return;
                        }
                        id = decodeURIComponent(id).split('?')[0].split('#')[0].split('k')[0];
                        const key = id.toLowerCase();
                        if (seen.has(key)) {
                            return;
                        }
                        seen.add(key);
                        candidates.push({id, score});
                    };
                    for (const value of scriptsAndResources) {
                        const text = String(value || '');
                        let score = 4;
                        if (text.includes('/web/book/readInfo')) {
                            score = 0;
                        } else if (text.includes('/web/book/bookmarklist') || text.includes('/web/book/read')) {
                            score = 1;
                        } else if (text.includes('/web/review/')) {
                            score = 2;
                        }
                        for (const match of text.matchAll(/[?&]bookId=([^&#]+)/g)) {
                            addCandidate(match[1], score);
                        }
                        for (const match of text.matchAll(/\\/cover\\/[^/]+\\/([^/]+)\\//g)) {
                            const coverId = decodeURIComponent(match[1]);
                            addCandidate(coverId, /^[0-9]+$/.test(coverId) ? 3 : 8);
                        }
                        for (const match of text.matchAll(/\\/web\\/reader\\/([0-9a-z]+)/ig)) {
                            addCandidate(match[1], 9);
                        }
                    }
                    const webBookIds = candidates
                        .sort((left, right) => left.score - right.score)
                        .map((candidate) => candidate.id);
                    const title = metaContent('meta[property="og:title"]')
                        || (document.title || '').split(' - ')[0]
                        || '';
                    const keywords = metaContent('meta[name="keywords"]').split(',');
                    const author = keywords.length > 1 ? keywords[1] : '';
                    return {webBookId: webBookIds[0] || '', webBookIds, title, author};
                }
                """
            )
        finally:
            await page.close()

        web_book_ids = self._web_book_id_candidates(page_meta, reader_book_id)
        if not web_book_ids:
            raise WeReadExportError("当前微信读书网页未解析到 web bookId")
        request_context = getattr(context, "request", None)
        if request_context is None:
            raise WeReadExportError("当前浏览器上下文不支持网页接口请求")
        errors = []
        for index, web_book_id in enumerate(web_book_ids):
            try:
                return await self._fetch_book_meta_via_web_request(
                    request_context,
                    web_book_id=web_book_id,
                    reader_book_id=reader_book_id,
                    title_hint=str((page_meta or {}).get("title") or ""),
                    author_hint=str((page_meta or {}).get("author") or ""),
                )
            except WeReadExportError as exc:
                errors.append(f"{web_book_id}: {exc}")
                if index < len(web_book_ids) - 1:
                    self._progress(current=f"网页 bookId {web_book_id} 未返回可用目录，尝试其他候选")
        raise WeReadExportError("当前微信读书网页接口未返回章节目录：" + "；".join(errors))

    async def _fetch_book_meta_via_web_request(
        self,
        request_context,
        *,
        web_book_id: str,
        reader_book_id: str,
        title_hint: str = "",
        author_hint: str = "",
    ) -> dict:
        referer = f"https://weread.qq.com/web/reader/{reader_book_id}"
        read_info_response = await request_context.get(
            "https://weread.qq.com/web/book/readInfo"
            f"?bookId={quote(web_book_id, safe='')}&finishedBookCount=1&finishedBookIndex=1&finishedDate=1",
            headers=self._weread_web_headers(referer),
        )
        read_info = await self._api_response_json(read_info_response, "web/book/readInfo")
        book_info = read_info.get("bookInfo") if isinstance(read_info.get("bookInfo"), dict) else {}

        max_free = book_info.get("maxFreeInfo") if isinstance(book_info.get("maxFreeInfo"), dict) else {}
        numeric_hints = [
            book_info.get("lastChapterIdx"),
            max_free.get("maxfreeChapterUid"),
            *(book_info.get("copyrightChapterUids") or []),
        ]
        max_hint = 0
        for value in numeric_hints:
            try:
                max_hint = max(max_hint, int(value or 0))
            except (TypeError, ValueError):
                continue
        max_candidate = min(max(max_hint + 120, 220), 3000)
        chapter_uids = list(range(0, max_candidate + 1))
        outline_response = await request_context.post(
            "https://weread.qq.com/web/book/outline",
            data={"bookId": web_book_id, "chapterUids": chapter_uids},
            headers={**self._weread_web_headers(referer), "Content-Type": "application/json"},
        )
        outline = await self._api_response_json(outline_response, "web/book/outline")

        chapters = []
        seen: set[str] = set()
        for item in outline.get("itemsArray") or []:
            if not isinstance(item, dict) or not item.get("items"):
                continue
            chapter_uid = item.get("chapterUid")
            if chapter_uid is None:
                continue
            chapter_key = str(chapter_uid)
            if chapter_key in seen:
                continue
            seen.add(chapter_key)
            title = ""
            for outline_item in item.get("items") or []:
                if isinstance(outline_item, dict) and outline_item.get("text"):
                    title = str(outline_item.get("text") or "")
                    break
            chapters.append({"id": chapter_uid, "title": title or f"第 {len(chapters) + 1} 章", "words": 0})

        if not chapters:
            raise WeReadExportError("当前微信读书网页接口未返回章节目录")

        return {
            "title": book_info.get("title") or title_hint or web_book_id,
            "author": book_info.get("author") or author_hint or "",
            "web_book_id": web_book_id,
            "reader_book_id": reader_book_id,
            "chapters": chapters,
        }

    async def _fetch_book_meta_via_request(self, request_context, book_id: str) -> dict:
        base_headers = self._weread_api_headers()
        info_response = await request_context.get(
            f"https://i.weread.qq.com/book/info?bookId={quote(book_id, safe='')}",
            headers=base_headers,
        )
        info = await self._api_response_json(info_response, "book/info")

        chapter_response = await request_context.post(
            "https://i.weread.qq.com/book/chapterInfos",
            data={"bookIds": [book_id], "synckeys": [0], "teenmode": 0},
            headers={**base_headers, "Content-Type": "application/json"},
        )
        chapter_data = await self._api_response_json(chapter_response, "book/chapterInfos")
        return self._normalize_book_meta(info, chapter_data)

    async def _api_response_json(self, response, label: str) -> dict:
        if not bool(getattr(response, "ok", False)):
            status = getattr(response, "status", "unknown")
            status_text = str(getattr(response, "status_text", "") or "").strip()
            suffix = f" {status_text}" if status_text else ""
            raise WeReadExportError(f"微信读书元数据请求失败：{label} HTTP {status}{suffix}")
        payload = response.json()
        if inspect.isawaitable(payload):
            payload = await payload
        if not isinstance(payload, dict):
            raise WeReadExportError(f"微信读书元数据响应格式异常：{label}")
        return payload

    def _normalize_book_meta(self, info: dict, chapter_data: dict) -> dict:
        chapters = []
        for item in chapter_data.get("data") or []:
            if isinstance(item, dict):
                chapters = item.get("updated") or []
        return {
            "title": info.get("title") or "",
            "author": info.get("author") or "",
            "chapters": [
                {
                    "id": chapter.get("chapterUid"),
                    "title": chapter.get("title"),
                    "words": chapter.get("wordCount") or 0,
                }
                for chapter in chapters
                if isinstance(chapter, dict)
            ],
        }

    async def _fetch_book_meta_via_page(self, context, book_id: str) -> dict | None:
        page = await context.new_page()
        try:
            await page.goto("https://weread.qq.com/web/shelf", wait_until="domcontentloaded", timeout=30000)
            return await page.evaluate(
                """
                async (bookId) => {
                    const r1 = await fetch('https://i.weread.qq.com/book/info?bookId=' + bookId,
                        {credentials: 'include'});
                    if (!r1.ok) {
                        throw new Error('book/info HTTP ' + r1.status);
                    }
                    const info = await r1.json();

                    const r2 = await fetch('https://i.weread.qq.com/book/chapterInfos', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({bookIds: [bookId], synckeys: [0], teenmode: 0}),
                        credentials: 'include',
                    });
                    if (!r2.ok) {
                        throw new Error('book/chapterInfos HTTP ' + r2.status);
                    }
                    const chapData = await r2.json();

                    let chapters = [];
                    for (const item of (chapData.data || [])) {
                        chapters = item.updated || [];
                    }

                    return {
                        title: info.title || '',
                        author: info.author || '',
                        chapters: chapters.map(c => ({
                            id: c.chapterUid,
                            title: c.title,
                            words: c.wordCount || 0,
                        })),
                    };
                }
                """,
                book_id,
            )
        finally:
            await page.close()

    async def wait_stable(self, page, *, min_chars: int = 10, timeout: float = 8) -> int:
        for _ in range(int(timeout / 0.5)):
            self._cancel_if_requested()
            c1 = await page.evaluate("() => window.__wr_count()")
            await asyncio.sleep(0.5)
            c2 = await page.evaluate("() => window.__wr_count()")
            if c2 == c1 and c1 >= min_chars:
                return int(c2)
        return int(await page.evaluate("() => window.__wr_count()"))

    async def fetch_chapter(
        self,
        context,
        book_id: str,
        chapter_id: str | int,
        *,
        raw_dir: Path | None = None,
    ) -> dict:
        reader_url = f"https://weread.qq.com/web/reader/{book_id}k{wr_hash(str(chapter_id))}"
        page = await context.new_page()
        try:
            await page.add_init_script(CANVAS_HOOK)
            await page.goto(reader_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2)

            count = await self.wait_stable(page)
            if count < 5:
                return {"ok": False, "text": "", "pages": 0, "reason": "no_content"}

            stale = 0
            page_num = 0
            while page_num < 500:
                self._cancel_if_requested()
                await page.evaluate("() => window.__wr_mark()")
                await page.keyboard.press("ArrowRight")
                await asyncio.sleep(1.2)
                new_count = await self.wait_stable(page, min_chars=count)
                if wr_hash(str(chapter_id)) not in page.url:
                    break
                if new_count == count:
                    stale += 1
                    if stale >= 3:
                        break
                else:
                    stale = 0
                    count = new_count
                page_num += 1

            await page.evaluate("() => window.__wr_mark()")
            all_chars = await page.evaluate("() => window.__wr_chars")
            marks = await page.evaluate("() => window.__wr_page_marks")

            if raw_dir:
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{chapter_id}.json").write_text(
                    json.dumps({"chars": all_chars, "marks": marks}, ensure_ascii=False),
                    encoding="utf-8",
                )

            page_texts = []
            for i in range(len(marks) - 1):
                page_chars = all_chars[marks[i] : marks[i + 1]]
                for spread in split_spread(page_chars):
                    text = reconstruct_page(spread)
                    if text:
                        page_texts.append(text)

            full_text = "\n\n".join(page_texts)
            return {
                "ok": bool(full_text),
                "text": full_text,
                "pages": len(page_texts),
                "reason": "" if full_text else "empty",
            }
        except WeReadExportError:
            raise
        except Exception as exc:
            return {"ok": False, "text": "", "pages": 0, "reason": str(exc)}
        finally:
            await page.close()

    async def _noop_close(self) -> None:
        return None

    async def _open_chrome_cdp_context(self, playwright) -> BrowserSession:
        self._progress(current=f"正在连接已登录 Chrome（CDP）：{self.chrome_cdp_endpoint}")
        try:
            browser = await playwright.chromium.connect_over_cdp(self.chrome_cdp_endpoint, timeout=3000)
        except Exception as exc:
            raise WeReadExportError(
                f"无法连接 Chrome CDP：{self.chrome_cdp_endpoint}。请使用 --remote-debugging-port 启动 Chrome，或改用独立会话。"
            ) from exc

        if not browser.contexts:
            raise WeReadExportError("Chrome CDP 未返回默认浏览器上下文，无法复用已登录会话")

        self._progress(current="已连接 Chrome，会在当前登录会话中新建标签页")
        return BrowserSession(
            context=browser.contexts[0],
            kind=BROWSER_MODE_CHROME_CDP,
            close=self._noop_close,
        )

    async def _open_persistent_context(self, playwright, profile_dir: Path) -> BrowserSession:
        self._progress(current="正在启动独立 Chromium 会话")
        context = await playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            viewport={"width": 1200, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        return BrowserSession(
            context=context,
            kind=BROWSER_MODE_PERSISTENT,
            close=context.close,
        )

    async def _open_browser_context(self, playwright, profile_dir: Path) -> BrowserSession:
        if self.browser_mode in {BROWSER_MODE_AUTO, BROWSER_MODE_CHROME_CDP}:
            try:
                return await self._open_chrome_cdp_context(playwright)
            except WeReadExportError:
                if self.browser_mode == BROWSER_MODE_CHROME_CDP:
                    raise
                self._progress(current="未检测到可复用 Chrome CDP，改用独立 Chromium 会话")

        return await self._open_persistent_context(playwright, profile_dir)

    async def run_async(
        self,
        *,
        book_id: str,
        output_dir: str,
        cache_dir: str,
        save_raw: bool = True,
    ) -> WeReadExportResult:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise WeReadExportError("未安装 Playwright，请先执行 pip install playwright 并安装 chromium") from exc

        output_root = Path(output_dir)
        profile_dir = Path(cache_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        profile_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as playwright:
            session = await self._open_browser_context(playwright, profile_dir)
            context = session.context
            try:
                if not await self.ensure_login(context, book_id=book_id):
                    raise WeReadExportError("微信读书登录超时")

                self._cancel_if_requested()
                self._progress(current="正在读取书籍元数据")
                meta = await self.fetch_book_meta(context, book_id)
                if not meta or not meta.get("chapters"):
                    raise WeReadExportError("无法获取章节列表，请检查 book_id 或阅读权限")

                title = str(meta.get("title") or book_id)
                author = str(meta.get("author") or "")
                chapters = list(meta.get("chapters") or [])
                total = len(chapters)
                safe_title = safe_filename(title, fallback=book_id)
                book_dir = output_root / book_id
                chapter_dir = book_dir / "chapters"
                raw_dir = book_dir / "raw" if save_raw else None
                merged_file = output_root / f"{safe_title}.md"
                meta_file = book_dir / "meta.json"
                chapter_dir.mkdir(parents=True, exist_ok=True)
                meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                self._progress(
                    title=title,
                    author=author,
                    total=total,
                    current=f"开始导出《{title}》",
                    meta=meta,
                )

                ok = fail = skipped = 0
                for index, chapter in enumerate(chapters, start=1):
                    self._cancel_if_requested()
                    chapter_id = chapter.get("id")
                    chapter_title = str(chapter.get("title") or f"第 {index} 章")
                    out_file = chapter_dir / f"{index:03d}.md"
                    if out_file.exists() and out_file.stat().st_size > 100 and "[FAILED]" not in out_file.read_text(encoding="utf-8", errors="ignore"):
                        skipped += 1
                        self._progress(
                            result={
                                "status": "skipped",
                                "title": chapter_title,
                                "path": str(out_file),
                            },
                            current=f"跳过已导出章节 {index}/{total}: {chapter_title}",
                        )
                        continue

                    self._progress(current=f"正在导出章节 {index}/{total}: {chapter_title}")
                    reader_book_id = str(meta.get("reader_book_id") or book_id)
                    result = await self.fetch_chapter(context, reader_book_id, chapter_id, raw_dir=raw_dir)
                    if result["ok"]:
                        cleaned = clean_text(result["text"], chapter_title)
                        out_file.write_text(f"# {chapter_title}\n\n{cleaned}\n", encoding="utf-8")
                        ok += 1
                        self._progress(
                            result={
                                "status": "success",
                                "title": chapter_title,
                                "path": str(out_file),
                                "pages": result.get("pages") or 0,
                                "chars": len(cleaned),
                            },
                            current=f"完成章节 {index}/{total}: {chapter_title}",
                        )
                    else:
                        out_file.write_text(
                            f"# {chapter_title}\n\n[FAILED: {result['reason']}]\n",
                            encoding="utf-8",
                        )
                        fail += 1
                        self._progress(
                            result={
                                "status": "failed",
                                "title": chapter_title,
                                "path": str(out_file),
                                "error": str(result.get("reason") or ""),
                            },
                            current=f"章节失败 {index}/{total}: {chapter_title}",
                        )
                    await asyncio.sleep(1.5)

                if ok + skipped <= 0:
                    raise WeReadExportError("全部章节导出失败")

                if ok + skipped > 0:
                    with merged_file.open("w", encoding="utf-8") as out:
                        out.write(f"# {title}\n\n")
                        if author:
                            out.write(f"**{author}**\n\n")
                        out.write("---\n\n")
                        for chapter_file in sorted(chapter_dir.glob("*.md")):
                            out.write(chapter_file.read_text(encoding="utf-8", errors="ignore"))
                            out.write("\n\n---\n\n")
                    self._progress(
                        result={
                            "kind": "artifact",
                            "status": "success",
                            "title": f"{title} 合并 Markdown",
                            "path": str(merged_file),
                            "content_type": "text/markdown",
                        },
                        current=f"导出完成：{merged_file.name}",
                    )

                return WeReadExportResult(
                    title=title,
                    author=author,
                    total=total,
                    ok=ok,
                    failed=fail,
                    skipped=skipped,
                    merged_path=str(merged_file) if merged_file.exists() else "",
                    meta_path=str(meta_file),
                )
            finally:
                await session.close()

    def run(self, **kwargs) -> WeReadExportResult:
        return asyncio.run(self.run_async(**kwargs))
