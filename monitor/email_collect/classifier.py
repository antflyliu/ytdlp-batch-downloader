from __future__ import annotations

import re

from .models import DEFAULT_CONTENT_PLATFORMS, EmailClassification


def classify_email(*, subject: str = "", body_text: str = "", from_addr: str = "") -> EmailClassification:
    text = f"{subject}\n{from_addr}\n{body_text}".lower()
    secondary: list[str] = []
    risk_flags: list[str] = []
    primary = "newsletter"
    targets = ["wechat", "zhihu", "x"]
    score = 5

    if any(word in text for word in ("unsubscribe", "newsletter", "digest", "weekly")):
        primary = "newsletter"
        secondary.append("digest")
        score += 1
    if any(word in text for word in ("release", "changelog", "launch", "product update", "版本", "发布")):
        primary = "product_update"
        secondary.append("product")
        targets = ["wechat", "toutiao", "baijiahao", "x"]
        score += 1
    if any(word in text for word in ("research", "paper", "benchmark", "dataset", "arxiv", "论文", "研究")):
        primary = "research"
        secondary.append("ai")
        targets = ["wechat", "zhihu", "juejin", "x"]
        score += 2
    if any(word in text for word in ("tutorial", "how to", "guide", "code", "api", "sdk", "教程", "实践")):
        primary = "tutorial"
        secondary.append("developer_tools")
        targets = ["juejin", "zhihu", "wechat", "reddit"]
        score += 2
    if any(word in text for word in ("sale", "coupon", "limited time", "促销", "折扣")):
        primary = "marketing"
        risk_flags.append("commercial_claims")
        score -= 1
    if any(word in text for word in ("copyright", "转载", "all rights reserved", "confidential")):
        risk_flags.append("third_party_copyright")
    if len(body_text.strip()) < 120:
        primary = "irrelevant"
        targets = []
        score = 2

    language = "zh" if re.search(r"[\u4e00-\u9fff]", subject + body_text) else "en"
    score = max(1, min(10, score))
    action = "ignore" if score < 4 or primary == "irrelevant" else "generate_variants"
    deduped_targets = [item for item in DEFAULT_CONTENT_PLATFORMS if item in set(targets)]
    return EmailClassification(
        primary_type=primary,
        secondary_types=secondary,
        language=language,
        value_score=score,
        action=action,
        recommended_targets=deduped_targets,
        risk_flags=risk_flags or (["needs_fact_check"] if action == "generate_variants" else []),
        reason="Rule-based first-pass classification for email content pipeline.",
    )
