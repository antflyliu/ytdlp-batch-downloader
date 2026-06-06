from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


ProgressCallback = Callable[[dict], None]
CancelCheck = Callable[[], bool]


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


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
    ):
        self.progress = progress or (lambda _event: None)
        self.cancel_check = cancel_check or (lambda: False)

    def _progress(self, **event) -> None:
        self.progress(event)

    def _cancel_if_requested(self) -> None:
        if self.cancel_check():
            raise WeReadExportError("任务已取消")

    async def ensure_login(self, context) -> bool:
        page = await context.new_page()
        self._progress(current="正在检查微信读书登录状态")
        try:
            await page.goto("https://weread.qq.com/web/shelf", timeout=30000)
            await asyncio.sleep(3)
            if "login" in page.url.lower():
                self._progress(current="请在弹出的浏览器窗口中扫码登录微信读书")
                await page.goto("https://weread.qq.com/#login", timeout=30000)
                for _ in range(120):
                    self._cancel_if_requested()
                    await asyncio.sleep(5)
                    if "login" not in page.url.lower():
                        self._progress(current="微信读书登录成功")
                        return True
                return False
            self._progress(current="微信读书已登录")
            return True
        finally:
            await page.close()

    async def fetch_book_meta(self, context, book_id: str) -> dict | None:
        page = await context.new_page()
        try:
            return await page.evaluate(
                """
                async (bookId) => {
                    const r1 = await fetch('https://i.weread.qq.com/book/info?bookId=' + bookId,
                        {credentials: 'include'});
                    const info = await r1.json();

                    const r2 = await fetch('https://i.weread.qq.com/book/chapterInfos', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({bookIds: [bookId], synckeys: [0], teenmode: 0}),
                        credentials: 'include',
                    });
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
            await page.goto(reader_url, wait_until="networkidle", timeout=30000)
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
            context = await playwright.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                viewport={"width": 1200, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                if not await self.ensure_login(context):
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
                    result = await self.fetch_chapter(context, book_id, chapter_id, raw_dir=raw_dir)
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
                await context.close()

    def run(self, **kwargs) -> WeReadExportResult:
        return asyncio.run(self.run_async(**kwargs))
