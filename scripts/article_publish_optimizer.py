"""Publish-ready article optimization for WeChat drafts.

This module keeps internal generation artifacts separate from the public
Markdown uploaded to WeChat: title, digest, body, and optional AIGC detection
metadata are prepared as reusable last-mile publishing assets.
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from scripts.llm_client import PROMPT_INPUT_PLACEHOLDER, create_llm_client

_log = logging.getLogger("article_publish_optimizer")

HOT_TITLE_MAX_CHARS = 30
PUBLISH_SUMMARY_MAX_CHARS = 120
PUBLISH_SUMMARY_MAX_BYTES = 120
TITLE_SCORE_FIELDS = ("curiosity", "relevance", "specificity", "clarity", "integrity")
_FRONTMATTER_RE = re.compile(r"\A---\r?\n[\s\S]*?\r?\n---\r?\n?")
_THINKING_BLOCK_RE = re.compile(r"<(think|thinking)\b[^>]*>[\s\S]*?</\1>", re.IGNORECASE)
_LEADING_THINKING_RE = re.compile(r"^\s*<(?:think|thinking)\b", re.IGNORECASE)
_MARKDOWN_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S")
_INTERNAL_DRAFT_HEADING_RE = re.compile(
    r"^\s{0,3}#{1,4}\s*(?:摘要素材|一句话摘要|推荐章节结构|发布建议|标题候选|爆款标题|创作思路)\s*$"
)


@dataclass
class TitleCandidate:
    title: str
    score: float
    reason: str = ""
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "score": self.score,
            "reason": self.reason,
            "metrics": self.metrics,
        }


@dataclass
class PublishOptimizationResult:
    title: str
    summary: str
    body: str
    title_candidates: list[TitleCandidate]
    aigc_report: dict[str, Any]


def _strip_thinking(value: object) -> str:
    text = str(value or "")
    previous = None
    while previous != text:
        previous = text
        text = _THINKING_BLOCK_RE.sub("\n", text)
    if _LEADING_THINKING_RE.search(text):
        heading = _MARKDOWN_HEADING_RE.search(text)
        text = text[heading.start() :] if heading else ""
    text = re.sub(r"</?(?:think|thinking)\b[^>]*>", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _plain_text(value: object) -> str:
    text = _strip_thinking(value)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[#>*_`|~\-]+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def truncate_with_ellipsis(text: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    if max_chars <= 3:
        return cleaned[:max_chars]
    return cleaned[: max_chars - 3].rstrip() + "..."


def truncate_summary_for_wechat(text: str) -> str:
    cleaned = truncate_with_ellipsis(text, PUBLISH_SUMMARY_MAX_CHARS)
    if len(cleaned.encode("utf-8")) <= PUBLISH_SUMMARY_MAX_BYTES:
        return cleaned
    suffix = "..."
    prefix = cleaned
    while prefix and len((prefix.rstrip() + suffix).encode("utf-8")) > PUBLISH_SUMMARY_MAX_BYTES:
        prefix = prefix[:-1]
    return (prefix.rstrip() + suffix) if prefix else ""


def _strip_internal_metadata(body: str) -> str:
    lines = body.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith(("类型：", "类型:", "选题：", "选题:", "生成时间：", "生成时间:")):
            index += 1
            continue
        break
    if index < len(lines) and lines[index].strip().startswith("```json"):
        end = index + 1
        while end < len(lines) and not lines[end].strip().startswith("```"):
            end += 1
        if end < len(lines):
            meta = "\n".join(lines[index + 1 : end])
            if '"task_id"' in meta or '"type"' in meta:
                index = end + 1
    return "\n".join(lines[index:]).strip()


def _drop_summary_material_prefix(body: str) -> str:
    lines = body.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^#\s+.+", stripped) and "摘要素材" not in stripped:
            prefix = lines[:idx]
            if any(_INTERNAL_DRAFT_HEADING_RE.match(item.strip()) for item in prefix):
                return "\n".join(lines[idx:]).strip()
            return body.strip()
    return body.strip()


def _drop_leading_public_title_and_digest(body: str) -> str:
    lines = body.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"^#\s+.+", lines[0].strip()):
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"^\*{0,2}摘要\*{0,2}\s*[：:]", lines[0].strip()):
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip() in {"---", "***", "___"}:
        lines.pop(0)
    return "\n".join(lines).strip()


def clean_publish_body(body: str) -> str:
    """Return only the public article body, without planning or draft metadata."""
    text = _strip_thinking(body)
    text = _FRONTMATTER_RE.sub("", text, count=1).strip()
    text = _strip_internal_metadata(text)
    text = _drop_summary_material_prefix(text)
    text = _drop_leading_public_title_and_digest(text)
    return text.strip()


def _json_from_response(response: object) -> Any:
    text = str(response or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fenced:
        text = fenced.group(1).strip()
    else:
        start_candidates = [pos for pos in (text.find("["), text.find("{")) if pos >= 0]
        if start_candidates:
            start = min(start_candidates)
            end = max(text.rfind("]"), text.rfind("}"))
            if end > start:
                text = text[start : end + 1]
    try:
        return json.loads(text)
    except Exception:
        return None


def _llm_call(cfg: dict[str, Any], prompt: str, payload: dict[str, Any], *, model_key: str) -> str | None:
    if not (cfg.get("llm_api_key") or cfg.get("llm_base_url") or cfg.get("llm_provider")):
        return None
    try:
        client = create_llm_client(
            provider=str(cfg.get("llm_provider") or "qwen"),
            model=str(cfg.get(model_key) or cfg.get("llm_model") or ""),
            api_key=cfg.get("llm_api_key"),
            base_url=cfg.get("llm_base_url"),
            proxy=cfg.get("llm_proxy"),
        )
        return client.call_with_retry(prompt, payload, max_retries=2, timeout=90, temperature=0.2)
    except Exception as exc:
        _log.warning("[发布优化] LLM 调用失败: %s", exc)
        return None


def _normalize_title(value: object) -> str:
    title = re.sub(r"\s+", "", str(value or "")).strip(" 　\"'“”‘’#")
    title = re.sub(r"[。.!！?？]+$", "", title)
    return truncate_with_ellipsis(title, HOT_TITLE_MAX_CHARS)


def _fallback_title_candidates(seed_title: str, body: str) -> list[TitleCandidate]:
    candidates: list[str] = []
    if seed_title and not seed_title.startswith("article_"):
        candidates.append(seed_title)
    first_heading = re.search(r"(?m)^#{1,3}\s+(.+)$", body or "")
    if first_heading:
        candidates.append(first_heading.group(1).strip())
    plain = _plain_text(body)
    if "心智" in plain:
        candidates.extend(["你的心智为何如此奇怪", "人类心智的隐藏真相", "从线虫到人类的心智跃迁"])
    if not candidates:
        candidates.append("这篇文章值得重新读一遍")
    unique = []
    for title in candidates:
        normalized = _normalize_title(title)
        if normalized and normalized not in unique:
            unique.append(normalized)
        if len(unique) >= 3:
            break
    return [
        TitleCandidate(
            title=title,
            score=max(60.0, 82.0 - idx * 4),
            reason="规则兜底候选，等待 LLM 可用时可重新评分。",
            metrics={"curiosity": 16, "relevance": 24, "specificity": 16, "clarity": 14, "integrity": 12},
        )
        for idx, title in enumerate(unique)
    ]


def generate_hot_title_candidates(
    body: str,
    seed_title: str,
    cfg: dict[str, Any],
) -> list[TitleCandidate]:
    prompt = (
        "你是微信公众号爆款标题编辑。请基于正文生成3个标题，并逐项评分。\n"
        "硬性要求：每个标题30个中文字符以内；不使用虚假悬念；必须贴合正文主题；不要出现任务ID。\n"
        "评分指标总分100：curiosity好奇心30，relevance主题相关30，specificity具体感20，"
        "clarity清晰度10，integrity不标题党10。\n"
        "只返回JSON数组，格式："
        "[{\"title\":\"标题\",\"score\":88,\"reason\":\"理由\",\"metrics\":{\"curiosity\":27,\"relevance\":28,\"specificity\":17,\"clarity\":8,\"integrity\":8}}]\n\n"
        f"{PROMPT_INPUT_PLACEHOLDER}"
    )
    payload = {"seed_title": seed_title, "body": clean_publish_body(body)[:5000]}
    parsed = _json_from_response(_llm_call(cfg, prompt, payload, model_key="article_llm_summary_model"))
    candidates: list[TitleCandidate] = []
    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            title = _normalize_title(item.get("title"))
            if not title:
                continue
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            score = item.get("score")
            try:
                score_value = float(score)
            except (TypeError, ValueError):
                score_value = float(sum(float(metrics.get(key, 0) or 0) for key in TITLE_SCORE_FIELDS))
            candidates.append(
                TitleCandidate(
                    title=title,
                    score=score_value,
                    reason=str(item.get("reason") or "").strip(),
                    metrics={key: float(metrics.get(key, 0) or 0) for key in TITLE_SCORE_FIELDS},
                )
            )
    if not candidates:
        candidates = _fallback_title_candidates(seed_title, body)
    deduped: dict[str, TitleCandidate] = {}
    for candidate in candidates:
        deduped.setdefault(candidate.title, candidate)
    return sorted(deduped.values(), key=lambda item: item.score, reverse=True)[:3]


def _extract_body_summary(body: str) -> str:
    match = re.search(r"(?m)^\*{0,2}摘要\*{0,2}\s*[：:]\s*(.+)$", body or "")
    if match:
        return _plain_text(match.group(1))
    paragraphs = [
        _plain_text(part)
        for part in re.split(r"\n\s*\n", clean_publish_body(body))
        if _plain_text(part) and not part.strip().startswith("#")
    ]
    return paragraphs[0] if paragraphs else _plain_text(body)


def generate_publish_summary(body: str, title: str, cfg: dict[str, Any]) -> str:
    prompt = (
        "你是微信公众号摘要编辑。请为文章生成一个可直接放入公众号摘要字段的摘要。\n"
        "要求：120字以内；第一句话就说明读者能获得什么；不要出现'摘要素材'、'关键要点'、编号列表或Markdown；"
        "超过120字必须压缩，不要编造正文没有的信息。\n\n"
        f"{PROMPT_INPUT_PLACEHOLDER}"
    )
    payload = {"title": title, "body": clean_publish_body(body)[:5000]}
    response = _llm_call(cfg, prompt, payload, model_key="article_llm_summary_model")
    summary = _plain_text(response) if response else ""
    if not summary:
        summary = _extract_body_summary(body)
    summary = re.sub(r"^(摘要素材|一句话摘要|摘要)[:：\s]+", "", summary).strip()
    return truncate_summary_for_wechat(summary)


def _optional_zhuque_api_call(url: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def run_zhuque_detection(
    *,
    body: str,
    image_paths: list[str],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Run optional Zhuque/Tata AIGC detection when official API endpoints exist.

    The public Zhuque website is UI-only. Without configured official endpoints,
    this function records an auditable skip instead of scraping a brittle page.
    """
    text_api = str(cfg.get("zhuque_text_api_url") or cfg.get("aigc_text_detection_api_url") or "").strip()
    image_api = str(cfg.get("zhuque_image_api_url") or cfg.get("aigc_image_detection_api_url") or "").strip()
    timeout_seconds = int(cfg.get("zhuque_detection_timeout_seconds") or 60)
    report: dict[str, Any] = {
        "provider": "zhuque",
        "status": "skipped_no_api",
        "text": None,
        "images": [],
        "notes": [
            "aigczhuque.com exposes public web detection, but no stable public API contract was found.",
            "Configure zhuque_text_api_url/zhuque_image_api_url when an official API contract is available.",
        ],
    }
    tasks: list[tuple[str, str, str, dict[str, Any]]] = []
    if text_api:
        tasks.append(("text", "", text_api, {"text": _plain_text(body), "source": "wechat_article"}))
    if image_api:
        for path in image_paths:
            tasks.append(("image", path, image_api, {"image_path": path, "source": "wechat_article"}))
    if not tasks:
        return report

    max_workers = min(max(1, int(cfg.get("zhuque_detection_parallelism") or 4)), len(tasks))
    had_success = False
    had_error = False
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_optional_zhuque_api_call, url, payload, timeout_seconds): (kind, path)
            for kind, path, url, payload in tasks
        }
        for future in as_completed(future_map):
            kind, path = future_map[future]
            try:
                result = future.result()
                had_success = True
                if kind == "text":
                    report["text"] = result
                else:
                    report["images"].append({"path": path, "result": result})
            except Exception as exc:
                had_error = True
                if kind == "text":
                    report["text_error"] = str(exc)
                else:
                    report.setdefault("image_errors", []).append({"path": path, "error": str(exc)})
    if had_error:
        report["status"] = "error"
    elif had_success:
        report["status"] = "completed"
    return report


def build_publish_markdown(title: str, author: str, summary: str, body: str) -> str:
    safe_title = str(title or "").replace('"', '\\"')
    safe_author = str(author or "").replace('"', '\\"')
    safe_summary = str(summary or "").replace('"', '\\"')
    return (
        "---\n"
        f'title: "{safe_title}"\n'
        f'author: "{safe_author}"\n'
        f'summary: "{safe_summary}"\n'
        "---\n\n"
        f"{clean_publish_body(body)}\n"
    )


def optimize_for_publish(
    *,
    body: str,
    seed_title: str,
    seed_summary: str,
    cfg: dict[str, Any],
    image_paths: list[str] | None = None,
) -> PublishOptimizationResult:
    clean_body = clean_publish_body(body)
    title_candidates = generate_hot_title_candidates(clean_body, seed_title, cfg)
    selected_title = title_candidates[0].title if title_candidates else _normalize_title(seed_title)
    summary = generate_publish_summary(seed_summary + "\n\n" + clean_body, selected_title, cfg)
    aigc_report = run_zhuque_detection(body=clean_body, image_paths=image_paths or [], cfg=cfg)
    return PublishOptimizationResult(
        title=selected_title,
        summary=summary,
        body=clean_body,
        title_candidates=title_candidates,
        aigc_report=aigc_report,
    )
