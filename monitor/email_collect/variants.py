from __future__ import annotations

import re
from typing import Any

PLATFORM_DISPLAY_NAMES = {
    "wechat": "微信公众号",
    "xiaohongshu": "小红书",
    "toutiao": "今日头条",
    "baijiahao": "百度百家号",
    "juejin": "掘金",
    "zhihu": "知乎",
    "x": "X / Twitter",
    "reddit": "Reddit",
}


def summarize_text(text: str, *, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return compact[:limit].rstrip() + ("..." if len(compact) > limit else "")


def build_platform_variant(
    *,
    platform: str,
    source_title: str,
    body_text: str,
    classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    classification = classification or {}
    title = (source_title or "邮件内容再创作").strip()
    summary = summarize_text(body_text)
    risk_flags = classification.get("risk_flags") or []
    tags = classification.get("secondary_types") or [classification.get("primary_type") or "email"]
    platform_name = PLATFORM_DISPLAY_NAMES.get(platform, platform)
    base_context = (
        f"来源标题: {title}\n"
        f"内容摘要: {summary}\n"
        f"分类: {classification.get('primary_type', 'unknown')}\n"
        f"风险提示: {', '.join(risk_flags) if risk_flags else '需要人工事实核验'}\n\n"
    )
    if platform == "x":
        body = base_context + "\n".join(
            f"{idx + 1}/ {item}"
            for idx, item in enumerate(_split_thread_items(body_text, max_items=6))
        )
        metadata = {"hashtags": [f"#{tag}" for tag in tags[:3]], "format": "thread"}
    elif platform == "xiaohongshu":
        body = base_context + f"开头钩子: {summary}\n\n正文要点:\n{_bullet_points(body_text, 5)}"
        metadata = {"hashtags": [f"#{tag}" for tag in tags[:5]], "image_card_suggestions": ["标题卡", "步骤卡", "结论卡"]}
    elif platform == "juejin":
        body = base_context + f"## 问题\n{summary}\n\n## 方案与细节\n{body_text.strip()}\n\n## 验证与坑点\n- 发布前补充可复现验证。\n"
        metadata = {"tags": tags[:5], "category": "tech"}
    elif platform == "zhihu":
        body = base_context + f"## 核心观点\n{summary}\n\n## 依据\n{body_text.strip()}\n\n## 边界\n需要补充来源链接和事实核验。"
        metadata = {"references_needed": True, "mode": "article"}
    elif platform == "reddit":
        body = base_context + f"{summary}\n\n{_bullet_points(body_text, 4)}\n\nQuestion: how are you handling this in practice?"
        metadata = {"subreddit_suggestions": ["technology", "programming"], "rule_risks": risk_flags}
    elif platform in {"toutiao", "baijiahao"}:
        body = base_context + f"## 事件概述\n{summary}\n\n## 关键细节\n{body_text.strip()}\n\n## 影响分析\n请人工补充事实来源和数据边界。"
        metadata = {"seo_keywords": tags[:5], "cover_suggestion": "使用主题相关的产品或场景图"}
    else:
        body = base_context + f"# {title}\n\n{body_text.strip()}\n"
        metadata = {"author": "", "digest": summary, "aigc_or_assisted_label_suggestion": "AI 辅助创作"}
    return {
        "platform": platform,
        "display_name": platform_name,
        "title": title[:80],
        "summary": summary,
        "body": body.strip(),
        "metadata": metadata,
        "quality": {
            "needs_review": True,
            "risk_flags": risk_flags,
            "checklist": ["事实核验", "授权/转载边界", "平台规则", "AIGC 标识"],
        },
    }


def _split_thread_items(text: str, *, max_items: int) -> list[str]:
    sentences = re.split(r"(?<=[。.!?？])\s+", re.sub(r"\s+", " ", text or "").strip())
    items = [item[:240].strip() for item in sentences if item.strip()]
    return items[:max_items] or [summarize_text(text, limit=240)]


def _bullet_points(text: str, count: int) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n{1,}", text or "") if p.strip()]
    selected = paragraphs[:count] or [summarize_text(text)]
    return "\n".join(f"- {item[:220]}" for item in selected)
