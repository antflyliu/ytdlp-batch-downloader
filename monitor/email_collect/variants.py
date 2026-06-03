from __future__ import annotations

import re
from typing import Any

from .platforms import PLATFORM_DISPLAY_NAMES, get_platform_strategy
from .processor import RULE_VERSION, apply_platform_sensitive_filter


def summarize_text(text: str, *, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return compact[:limit].rstrip() + ("..." if len(compact) > limit else "")


def build_platform_variant(
    *,
    platform: str,
    source_title: str,
    body_text: str,
    classification: dict[str, Any] | None = None,
    analysis_rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    classification = classification or {}
    title = (source_title or "邮件内容再创作").strip()
    if _should_apply_platform_filter(classification):
        filtered_body_text, compliance_report = apply_platform_sensitive_filter(
            body_text,
            platform=platform,
            rules=analysis_rules,
        )
    else:
        filtered_body_text = body_text
        compliance_report = {
            "platform": platform,
            "matched_terms": [],
            "changed": False,
            "rule_version": RULE_VERSION,
            "skipped_reason": "not_news_like",
        }
    summary = summarize_text(filtered_body_text)
    risk_flags = classification.get("risk_flags") or []
    tags = classification.get("secondary_types") or [classification.get("primary_type") or "email"]
    platform_name = PLATFORM_DISPLAY_NAMES.get(platform, platform)
    strategy = get_platform_strategy(platform)
    output_contract = strategy["output_contract"]
    prompt_profile = strategy["prompt_profile"]
    checklist = _dedupe_list(
        list(prompt_profile.get("review_checklist") or [])
        + ["事实核验", "来源授权", "平台规则", "AIGC 标识", "平台原生表达"]
    )
    base_context = _base_context(
        title=title,
        summary=summary,
        classification=classification,
        risk_flags=risk_flags,
        output_contract=output_contract,
        prompt_profile=prompt_profile,
        checklist=checklist,
    )
    if platform == "x":
        body = base_context + "\n".join(
            f"{idx + 1}/ {item}"
            for idx, item in enumerate(_split_thread_items(filtered_body_text, max_items=6))
        )
        metadata = {"hashtags": [f"#{tag}" for tag in tags[:3]], "format": "thread"}
    elif platform == "xiaohongshu":
        body = base_context + f"开头钩子: {summary}\n\n正文要点:\n{_bullet_points(filtered_body_text, 5)}"
        metadata = {"hashtags": [f"#{tag}" for tag in tags[:5]], "image_card_suggestions": ["标题卡", "步骤卡", "结论卡"]}
    elif platform == "juejin":
        body = base_context + f"## 问题\n{summary}\n\n## 方案与细节\n{filtered_body_text.strip()}\n\n## 验证与坑点\n- 发布前补充可复现验证。\n"
        metadata = {"tags": tags[:5], "category": "tech"}
    elif platform == "zhihu":
        body = base_context + f"## 核心观点\n{summary}\n\n## 依据\n{filtered_body_text.strip()}\n\n## 边界\n需要补充来源链接和事实核验。"
        metadata = {"references_needed": True, "mode": "article"}
    elif platform == "reddit":
        body = base_context + f"{summary}\n\n{_bullet_points(filtered_body_text, 4)}\n\nQuestion: how are you handling this in practice?"
        metadata = {"subreddit_suggestions": ["technology", "programming"], "rule_risks": risk_flags}
    elif platform in {"toutiao", "baijiahao"}:
        body = base_context + f"## 事件概述\n{summary}\n\n## 关键细节\n{filtered_body_text.strip()}\n\n## 影响分析\n请人工补充事实来源和数据边界。"
        metadata = {"seo_keywords": tags[:5], "cover_suggestion": "使用主题相关的产品或场景图"}
    else:
        body = base_context + f"# {title}\n\n{filtered_body_text.strip()}\n"
        metadata = {"author": "", "digest": summary, "aigc_or_assisted_label_suggestion": "AI 辅助创作"}
    metadata["platform_compliance"] = compliance_report
    metadata["output_contract"] = output_contract
    metadata["prompt_profile"] = prompt_profile
    metadata["style_guidance"] = strategy.get("style_guidance") or []
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
            "checklist": checklist,
            "style_review": strategy.get("style_guidance") or [],
        },
    }


def _base_context(
    *,
    title: str,
    summary: str,
    classification: dict[str, Any],
    risk_flags: list[str],
    output_contract: dict[str, Any],
    prompt_profile: dict[str, Any],
    checklist: list[str],
) -> str:
    required_sections = output_contract.get("required_sections") or []
    style_line = "、".join(required_sections) if required_sections else str(output_contract.get("format") or "article")
    return (
        f"来源标题: {title}\n"
        f"内容摘要: {summary}\n"
        f"分类: {classification.get('primary_type', 'unknown')}\n"
        f"目标读者: {prompt_profile.get('audience', '目标平台读者')}\n"
        f"平台写作要求: {prompt_profile.get('structure', style_line)}\n"
        f"语气: {prompt_profile.get('tone', '清晰、准确')}\n"
        f"风险提示: {', '.join(risk_flags) if risk_flags else '需要人工事实核验'}\n"
        f"发布前检查: {' / '.join(checklist[:6])}\n\n"
    )


def _split_thread_items(text: str, *, max_items: int) -> list[str]:
    sentences = re.split(r"(?<=[。.!?？])\s+", re.sub(r"\s+", " ", text or "").strip())
    items = [item[:240].strip() for item in sentences if item.strip()]
    return items[:max_items] or [summarize_text(text, limit=240)]


def _bullet_points(text: str, count: int) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n{1,}", text or "") if p.strip()]
    selected = paragraphs[:count] or [summarize_text(text)]
    return "\n".join(f"- {item[:220]}" for item in selected)


def _dedupe_list(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _should_apply_platform_filter(classification: dict[str, Any]) -> bool:
    compliance = classification.get("platform_compliance") or {}
    if compliance.get("news_like"):
        return True
    if classification.get("primary_type") == "news":
        return True
    return "platform_sensitive_review" in set(classification.get("risk_flags") or [])
