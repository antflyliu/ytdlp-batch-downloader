from __future__ import annotations

import copy
import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .classifier import classify_email
from .cleaner import html_to_text
from .models import DEFAULT_CONTENT_PLATFORMS

LinkFetcher = Callable[[str], str | dict[str, Any] | None]

RULE_VERSION = "email-content-analysis-v1"
RULE_SCHEMA_VERSION = "email-analysis-rules-schema-v1"
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "mkt_tok", "spm"}
UNSAFE_SCHEMES = {"", "mailto", "tel", "javascript", "data", "file"}
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}
MAX_LINKS = 30
MAX_ENRICHED_LINKS = 10
MAX_ENRICHMENT_DEPTH = 3
MAX_EXCERPT_CHARS = 3_000
MAX_TIMEOUT_SECONDS = 30
MAX_FETCH_BYTES = 1_000_000
RULE_TOP_LEVEL_KEYS = {
    "marketing_keywords",
    "marketing_sender_domains",
    "news_keywords",
    "topic_rules",
    "translation_glossary",
    "platform_sensitive_words",
    "link_enrichment",
}
RULE_STRING_LIST_KEYS = {"marketing_keywords", "marketing_sender_domains", "news_keywords"}
LINK_ENRICHMENT_LIMITS = {
    "max_links": (1, MAX_LINKS),
    "max_enriched_links": (1, MAX_ENRICHED_LINKS),
    "max_depth": (1, MAX_ENRICHMENT_DEPTH),
    "excerpt_chars": (100, MAX_EXCERPT_CHARS),
    "timeout_seconds": (1, MAX_TIMEOUT_SECONDS),
    "max_bytes": (1_000, MAX_FETCH_BYTES),
}

DEFAULT_EMAIL_ANALYSIS_RULES: dict[str, Any] = {
    "marketing_keywords": [
        "sale",
        "coupon",
        "limited time",
        "deal",
        "discount",
        "promotion",
        "sponsor",
        "black friday",
        "unsubscribe",
        "manage preferences",
        "促销",
        "优惠",
        "折扣",
        "限时",
        "退订",
    ],
    "marketing_sender_domains": ["promo.", "marketing.", "mailers.", "newsletter."],
    "news_keywords": ["breaking", "report", "according to", "announced", "policy", "新闻", "报道", "消息", "政策", "发布会"],
    "topic_rules": [
        {
            "tag": "ai_research",
            "primary_type": "research",
            "keywords": ["research", "paper", "benchmark", "dataset", "arxiv", "llm", "model", "论文", "研究", "模型"],
            "targets": ["wechat", "zhihu", "juejin", "x"],
        },
        {
            "tag": "developer_practice",
            "primary_type": "tutorial",
            "keywords": ["tutorial", "guide", "how to", "api", "sdk", "code", "migration", "教程", "实践", "代码"],
            "targets": ["juejin", "zhihu", "wechat", "reddit"],
        },
        {
            "tag": "product_update",
            "primary_type": "product_update",
            "keywords": ["release", "launch", "changelog", "product update", "版本", "发布", "更新"],
            "targets": ["wechat", "toutiao", "baijiahao", "x"],
        },
        {
            "tag": "industry_news",
            "primary_type": "news",
            "keywords": ["breaking", "news", "report", "according to", "announced", "新闻", "报道", "消息", "政策"],
            "targets": ["wechat", "toutiao", "baijiahao", "zhihu"],
        },
        {
            "tag": "security",
            "primary_type": "security",
            "keywords": ["security", "vulnerability", "cve", "attack", "breach", "安全", "漏洞", "攻击"],
            "targets": ["wechat", "zhihu", "juejin"],
        },
    ],
    "translation_glossary": {
        "research": "研究",
        "paper": "论文",
        "benchmark": "基准测试",
        "dataset": "数据集",
        "release": "发布",
        "launch": "上线",
        "migration": "迁移",
        "developer": "开发者",
        "engineering": "工程",
        "evaluation": "评估",
        "methodology": "方法论",
        "risk": "风险",
        "guide": "指南",
        "tutorial": "教程",
        "security": "安全",
        "vulnerability": "漏洞",
        "policy": "政策",
        "market": "市场",
        "model": "模型",
        "api": "API",
        "sdk": "SDK",
    },
    "platform_sensitive_words": {
        "common": {
            "赌博": "违规博彩",
            "色情": "成人内容",
            "血腥": "不适内容",
            "自杀": "极端事件",
            "枪击": "暴力事件",
            "炸弹": "爆炸物",
            "屠杀": "严重冲突",
            "谣言": "未经证实信息",
            "war": "conflict",
            "massacre": "violent incident",
        },
        "wechat": {"翻墙": "跨境网络访问", "封杀": "限制"},
        "toutiao": {"内幕": "未公开信息", "绝密": "非公开"},
        "baijiahao": {"震惊": "值得关注", "最强": "较强"},
        "zhihu": {"带节奏": "引发讨论", "撕裂": "分歧"},
        "xiaohongshu": {"医美": "健康消费", "暴富": "快速增长"},
    },
    "link_enrichment": {
        "max_links": 8,
        "max_enriched_links": 3,
        "max_depth": 1,
        "excerpt_chars": 900,
        "timeout_seconds": 6,
        "max_bytes": 200_000,
    },
}


def merge_email_analysis_rules(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = copy.deepcopy(DEFAULT_EMAIL_ANALYSIS_RULES)
    if not isinstance(overrides, dict):
        return rules

    def merge(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = copy.deepcopy(value)

    merge(rules, overrides)
    return rules


def email_analysis_rules_schema() -> dict[str, Any]:
    """Return a lightweight JSON-schema-like contract for operator-maintained rules."""
    return {
        "schema_version": RULE_SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "allowed_top_level_keys": sorted(RULE_TOP_LEVEL_KEYS),
        "string_list_keys": sorted(RULE_STRING_LIST_KEYS),
        "topic_rule_shape": {
            "tag": "non-empty string",
            "primary_type": "optional string",
            "keywords": "non-empty string[]",
            "targets": list(DEFAULT_CONTENT_PLATFORMS),
        },
        "translation_glossary": "object<string,string>",
        "platform_sensitive_words": {
            "platforms": ["common", *DEFAULT_CONTENT_PLATFORMS],
            "shape": "object<platform, object<term,replacement>>",
        },
        "link_enrichment_limits": {
            key: {"min": bounds[0], "max": bounds[1]}
            for key, bounds in LINK_ENRICHMENT_LIMITS.items()
        },
        "export_shape": {
            "schema_version": RULE_SCHEMA_VERSION,
            "rules": "EmailAnalysisRules object",
            "exported_at": "ISO-8601 timestamp",
        },
    }


def validate_email_analysis_rules(candidate: Any) -> dict[str, Any]:
    """Validate and normalize email analysis rule overrides without external deps."""
    errors: list[str] = []
    if candidate is None:
        candidate = {}
    if not isinstance(candidate, dict):
        return {"ok": False, "errors": ["rules must be an object"], "rules": {}}

    normalized: dict[str, Any] = {}
    for key, value in candidate.items():
        if key not in RULE_TOP_LEVEL_KEYS:
            errors.append(f"{key}: unknown rule key")
            continue
        if key in RULE_STRING_LIST_KEYS:
            normalized[key] = _validate_string_list(key, value, errors)
        elif key == "topic_rules":
            normalized[key] = _validate_topic_rules(value, errors)
        elif key == "translation_glossary":
            normalized[key] = _validate_string_map(key, value, errors)
        elif key == "platform_sensitive_words":
            normalized[key] = _validate_platform_sensitive_words(value, errors)
        elif key == "link_enrichment":
            normalized[key] = _validate_link_enrichment(value, errors)

    return {"ok": not errors, "errors": errors, "rules": normalized}


def coerce_email_analysis_rules_payload(payload: Any) -> dict[str, Any]:
    """Accept direct rules or an exported wrapper and return a validation payload."""
    if isinstance(payload, dict) and "rules" in payload:
        schema_version = payload.get("schema_version")
        if schema_version and schema_version != RULE_SCHEMA_VERSION:
            return {
                "ok": False,
                "errors": [f"schema_version: unsupported version {schema_version}"],
                "rules": {},
            }
        payload = payload.get("rules")
    return validate_email_analysis_rules(payload)


def _keyword_matches(text: str, keyword: Any) -> bool:
    value = str(keyword or "").strip().lower()
    if not value:
        return False
    lowered = (text or "").lower()
    if re.search(r"[\u4e00-\u9fff]", value):
        return value in lowered
    if re.search(r"[a-z0-9_]", value):
        return re.search(rf"(?<![a-z0-9_]){re.escape(value)}(?![a-z0-9_])", lowered) is not None
    return value in lowered


def _any_keyword_matches(text: str, keywords: Any) -> bool:
    return any(_keyword_matches(text, keyword) for keyword in keywords or [])


def _validate_string_list(key: str, value: Any, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{key}: must be a string array")
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        item_value = str(item).strip() if isinstance(item, str) else ""
        if not item_value:
            errors.append(f"{key}[{index}]: must be a non-empty string")
            continue
        result.append(item_value)
    return _dedupe_strings(result)


def _validate_string_map(key: str, value: Any, errors: list[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        errors.append(f"{key}: must be an object")
        return {}
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        map_key = str(raw_key).strip() if isinstance(raw_key, str) else ""
        map_value = str(raw_value).strip() if isinstance(raw_value, str) else ""
        if not map_key:
            errors.append(f"{key}: map keys must be non-empty strings")
            continue
        if not map_value:
            errors.append(f"{key}.{map_key}: replacement must be a non-empty string")
            continue
        result[map_key] = map_value
    return result


def _validate_topic_rules(value: Any, errors: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        errors.append("topic_rules: must be an array")
        return []
    valid_targets = set(DEFAULT_CONTENT_PLATFORMS)
    result: list[dict[str, Any]] = []
    for index, rule in enumerate(value):
        if not isinstance(rule, dict):
            errors.append(f"topic_rules[{index}]: must be an object")
            continue
        tag = str(rule.get("tag") or "").strip()
        if not tag:
            errors.append(f"topic_rules[{index}].tag: must be a non-empty string")
        keywords = _validate_string_list(f"topic_rules[{index}].keywords", rule.get("keywords"), errors)
        targets = _validate_string_list(f"topic_rules[{index}].targets", rule.get("targets") or [], errors)
        invalid_targets = [target for target in targets if target not in valid_targets]
        if invalid_targets:
            errors.append(
                f"topic_rules[{index}].targets: unsupported platform(s): {', '.join(invalid_targets)}"
            )
        normalized_rule = {
            "tag": tag,
            "primary_type": str(rule.get("primary_type") or "").strip(),
            "keywords": keywords,
            "targets": [target for target in targets if target in valid_targets],
        }
        if tag and keywords:
            result.append(normalized_rule)
    return result


def _validate_platform_sensitive_words(value: Any, errors: list[str]) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        errors.append("platform_sensitive_words: must be an object")
        return {}
    valid_platforms = {"common", *DEFAULT_CONTENT_PLATFORMS}
    result: dict[str, dict[str, str]] = {}
    for platform, replacements in value.items():
        platform_key = str(platform).strip()
        if platform_key not in valid_platforms:
            errors.append(f"platform_sensitive_words.{platform_key}: unsupported platform")
            continue
        result[platform_key] = _validate_string_map(f"platform_sensitive_words.{platform_key}", replacements, errors)
    return result


def _validate_link_enrichment(value: Any, errors: list[str]) -> dict[str, int]:
    if not isinstance(value, dict):
        errors.append("link_enrichment: must be an object")
        return {}
    result: dict[str, int] = {}
    for key, raw_value in value.items():
        if key not in LINK_ENRICHMENT_LIMITS:
            errors.append(f"link_enrichment.{key}: unknown option")
            continue
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            errors.append(f"link_enrichment.{key}: must be an integer")
            continue
        min_value, max_value = LINK_ENRICHMENT_LIMITS[key]
        if not min_value <= parsed <= max_value:
            errors.append(f"link_enrichment.{key}: must be between {min_value} and {max_value}")
            continue
        result[key] = parsed
    return result


def analyze_email_content(
    *,
    subject: str = "",
    body_text: str = "",
    from_addr: str = "",
    html_body: str = "",
    rules: dict[str, Any] | None = None,
    expand_links: bool = False,
    link_fetcher: LinkFetcher | None = None,
    max_depth: int | None = None,
) -> dict[str, Any]:
    effective_rules = merge_email_analysis_rules(rules)
    baseline = classify_email(subject=subject, body_text=body_text, from_addr=from_addr).as_dict()
    language = _detect_language(subject + "\n" + body_text)
    links = extract_relevant_links(subject=subject, body_text=body_text, html_body=html_body, rules=effective_rules)
    if expand_links:
        enrich_links(
            links,
            subject=subject,
            body_text=body_text,
            rules=effective_rules,
            link_fetcher=link_fetcher,
            max_depth=max_depth,
        )
    tags, matched_topic_rules, targets, primary_override = _classify_topics(subject, body_text, effective_rules)
    marketing_report = _marketing_filter(subject, body_text, from_addr, tags, effective_rules)
    translation = _translation_metadata(body_text, language, effective_rules)
    news_like = _is_news_like(subject, body_text, baseline, tags, effective_rules)
    platform_compliance = build_platform_compliance_report(
        body_text,
        platforms=DEFAULT_CONTENT_PLATFORMS,
        rules=effective_rules,
        news_like=news_like,
    )

    classification = dict(baseline)
    if primary_override and baseline.get("primary_type") not in {"research", "tutorial", "security"}:
        classification["primary_type"] = primary_override
    if marketing_report["disposition"] == "ignore":
        classification.update(
            {
                "primary_type": "marketing",
                "action": "ignore",
                "recommended_targets": [],
                "value_score": min(int(classification.get("value_score") or 5), 3),
            }
        )
    elif classification.get("action") == "ignore" and not matched_topic_rules:
        classification["recommended_targets"] = []
        classification["value_score"] = int(classification.get("value_score") or 2)
    else:
        classification["action"] = "generate_variants"
        classification["recommended_targets"] = _dedupe_platforms(
            list(classification.get("recommended_targets") or []) + targets
        )
        classification["value_score"] = max(int(classification.get("value_score") or 5), _score_from_tags(tags, links))

    secondary = list(classification.get("secondary_types") or [])
    classification["secondary_types"] = _dedupe_strings(secondary + tags)
    classification["language"] = language
    risk_flags = list(classification.get("risk_flags") or [])
    if news_like:
        risk_flags.append("platform_sensitive_review")
    if links["kept_count"] and not expand_links:
        risk_flags.append("links_not_expanded")
    classification["risk_flags"] = _dedupe_strings(
        risk_flags or (["needs_fact_check"] if classification.get("action") == "generate_variants" else [])
    )
    classification["reason"] = _reason(classification, marketing_report, matched_topic_rules, links)
    classification.update(
        {
            "rule_version": RULE_VERSION,
            "tags": classification["secondary_types"],
            "matched_rules": {
                "topics": matched_topic_rules,
                "filter": marketing_report["matched_rules"],
            },
            "filter": marketing_report,
            "links": _public_link_report(links),
            "translation": translation,
            "platform_compliance": platform_compliance,
            "entities": {
                "sender_domain": _sender_domain(from_addr),
                "link_domains": _dedupe_strings([item.get("domain", "") for item in links["items"] if item.get("domain")]),
            },
        }
    )
    classification["analysis_text"] = _build_analysis_text(body_text, translation, links)
    return {
        "classification": classification,
        "cleaning_report": {
            "link_extraction": {
                "extracted_count": links["extracted_count"],
                "kept_count": links["kept_count"],
                "skipped_count": links["skipped_count"],
                "skipped_reasons": links["skipped_reasons"],
            },
            "translation_required": translation["required"],
            "news_like": news_like,
            "rule_version": RULE_VERSION,
        },
    }


class _AnchorExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href") or ""
        self._current = {"url": href, "label": ""}

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["label"] = (self._current.get("label") or "") + data

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current is not None:
            self.items.append(self._current)
            self._current = None


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        normalized, skipped = _normalize_public_url(newurl, resolve_host=True)
        if skipped:
            raise ValueError(f"blocked redirect URL: {skipped}")
        return super().redirect_request(req, fp, code, msg, headers, normalized)


def extract_relevant_links(
    *,
    subject: str = "",
    body_text: str = "",
    html_body: str = "",
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_rules = merge_email_analysis_rules(rules)
    candidates: list[dict[str, str]] = []
    if html_body:
        parser = _AnchorExtractor()
        try:
            parser.feed(html_body)
            parser.close()
            candidates.extend({"url": item["url"], "label": item.get("label", ""), "source": "html"} for item in parser.items)
        except Exception:
            pass

    for match in re.finditer(r"https?://[^\s<>'\")]+", body_text or ""):
        url = match.group(0).rstrip(".,;:!?)]}")
        candidates.append(
            {
                "url": url,
                "label": "",
                "source": "text",
                "context": _context_around(body_text, match.start(), match.end()),
            }
        )

    items: list[dict[str, Any]] = []
    skipped_reasons: dict[str, int] = {}
    seen: set[str] = set()
    for candidate in candidates:
        normalized, skipped = _normalize_public_url(candidate.get("url", ""))
        if skipped:
            skipped_reasons[skipped] = skipped_reasons.get(skipped, 0) + 1
            continue
        if normalized in seen:
            skipped_reasons["duplicate"] = skipped_reasons.get("duplicate", 0) + 1
            continue
        seen.add(normalized)
        label = _compact(candidate.get("label", ""))
        context = _compact(candidate.get("context", "") or label)
        score = _link_relevance_score(subject, body_text, label, context, normalized, effective_rules)
        if score <= 0:
            skipped_reasons["low_relevance"] = skipped_reasons.get("low_relevance", 0) + 1
            continue
        parsed = urlparse(normalized)
        items.append(
            {
                "url": normalized,
                "domain": parsed.hostname or "",
                "label": label,
                "context": context,
                "source": candidate.get("source") or "text",
                "relevance_score": score,
                "enrichment_status": "not_requested",
            }
        )

    items.sort(key=lambda item: item["relevance_score"], reverse=True)
    max_links = _bounded_int((effective_rules.get("link_enrichment") or {}).get("max_links"), 8, max_value=MAX_LINKS)
    items = items[:max_links]
    return {
        "items": items,
        "extracted_count": len(candidates),
        "kept_count": len(items),
        "skipped_count": sum(skipped_reasons.values()),
        "skipped_reasons": skipped_reasons,
    }


def enrich_links(
    links: dict[str, Any],
    *,
    subject: str = "",
    body_text: str = "",
    rules: dict[str, Any] | None = None,
    link_fetcher: LinkFetcher | None = None,
    max_depth: int | None = None,
) -> None:
    effective_rules = merge_email_analysis_rules(rules)
    link_rules = effective_rules.get("link_enrichment") or {}
    depth = _bounded_int(max_depth or link_rules.get("max_depth"), 1, max_value=MAX_ENRICHMENT_DEPTH)
    max_enriched = _bounded_int(link_rules.get("max_enriched_links"), 3, max_value=MAX_ENRICHED_LINKS)
    fetcher = link_fetcher or (lambda url: _default_fetch_url(url, rules=effective_rules))
    for item in links.get("items", [])[:max_enriched]:
        _enrich_single_link(
            item,
            subject=subject,
            body_text=body_text,
            rules=effective_rules,
            fetcher=fetcher,
            depth=depth,
            seen={item.get("url", "")},
        )


def apply_platform_sensitive_filter(
    text: str,
    *,
    platform: str,
    rules: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    effective_rules = merge_email_analysis_rules(rules)
    replacements: dict[str, str] = {}
    platform_rules = effective_rules.get("platform_sensitive_words") or {}
    replacements.update(platform_rules.get("common") or {})
    replacements.update(platform_rules.get(platform) or {})

    filtered = text or ""
    matched: list[dict[str, str]] = []
    for term, replacement in replacements.items():
        pattern = re.compile(re.escape(str(term)), re.IGNORECASE)
        if not pattern.search(filtered):
            continue
        filtered = pattern.sub(str(replacement), filtered)
        matched.append({"term": str(term), "replacement": str(replacement)})
    return filtered, {
        "platform": platform,
        "matched_terms": matched,
        "changed": bool(matched),
        "rule_version": RULE_VERSION,
    }


def build_platform_compliance_report(
    text: str,
    *,
    platforms: tuple[str, ...] | list[str],
    rules: dict[str, Any] | None = None,
    news_like: bool = False,
) -> dict[str, Any]:
    report = {"news_like": bool(news_like), "rule_version": RULE_VERSION, "platforms": {}}
    if not news_like:
        return report
    for platform in platforms:
        _filtered, platform_report = apply_platform_sensitive_filter(text, platform=platform, rules=rules)
        report["platforms"][platform] = platform_report
    return report


def _enrich_single_link(
    item: dict[str, Any],
    *,
    subject: str,
    body_text: str,
    rules: dict[str, Any],
    fetcher: LinkFetcher,
    depth: int,
    seen: set[str],
) -> None:
    url = item.get("url") or ""
    try:
        payload = fetcher(url)
        title, text, html_body = _normalize_fetch_payload(payload)
        excerpt_chars = _bounded_int(
            (rules.get("link_enrichment") or {}).get("excerpt_chars"),
            900,
            max_value=MAX_EXCERPT_CHARS,
        )
        excerpt = _related_excerpt(text, subject + "\n" + body_text, excerpt_chars)
        item["enrichment_status"] = "ok"
        item["enrichment"] = {
            "title": title,
            "excerpt": excerpt,
            "content_chars": len(text),
        }
        if depth > 1 and html_body:
            child_links = extract_relevant_links(subject=subject, body_text=text, html_body=html_body, rules=rules)
            child_items = []
            for child in child_links.get("items", [])[:2]:
                child_url = child.get("url") or ""
                if child_url in seen:
                    continue
                seen.add(child_url)
                _enrich_single_link(
                    child,
                    subject=subject,
                    body_text=body_text + "\n" + text,
                    rules=rules,
                    fetcher=fetcher,
                    depth=depth - 1,
                    seen=seen,
                )
                child_items.append(child)
            item["enrichment"]["child_links"] = child_items
    except Exception as exc:
        item["enrichment_status"] = "failed"
        item["enrichment_error"] = str(exc)[:180]


def _default_fetch_url(url: str, *, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    effective_rules = merge_email_analysis_rules(rules)
    link_rules = effective_rules.get("link_enrichment") or {}
    timeout_seconds = _bounded_int(
        link_rules.get("timeout_seconds"),
        int(DEFAULT_EMAIL_ANALYSIS_RULES["link_enrichment"]["timeout_seconds"]),
        max_value=30,
    )
    max_bytes = _bounded_int(
        link_rules.get("max_bytes"),
        int(DEFAULT_EMAIL_ANALYSIS_RULES["link_enrichment"]["max_bytes"]),
        max_value=1_000_000,
    )
    normalized, skipped = _normalize_public_url(url, resolve_host=True)
    if skipped:
        raise ValueError(f"blocked URL: {skipped}")
    request = Request(normalized, headers={"User-Agent": "ytdlp-batch-email-processor/1.0"})
    opener = build_opener(_SafeRedirectHandler)
    with opener.open(
        request,
        timeout=timeout_seconds,
    ) as response:
        final_url = response.geturl()
        _final_normalized, final_skipped = _normalize_public_url(final_url, resolve_host=True)
        if final_skipped:
            raise ValueError(f"blocked final URL: {final_skipped}")
        content_type = response.headers.get("content-type", "")
        if not any(kind in content_type.lower() for kind in ("text/html", "text/plain", "application/xhtml")):
            raise ValueError(f"unsupported content type: {content_type}")
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    data = raw.decode("utf-8", errors="replace")
    return {"html": data if "<html" in data.lower() or "<p" in data.lower() else "", "text": data}


def _normalize_fetch_payload(payload: str | dict[str, Any] | None) -> tuple[str, str, str]:
    if payload is None:
        raise ValueError("empty response")
    if isinstance(payload, str):
        raw = payload
        html_body = raw if "<" in raw and ">" in raw else ""
        text = html_to_text(raw) if html_body else raw
        return _extract_title(raw), _compact_text(text), html_body
    raw_html = str(payload.get("html") or "")
    raw_text = str(payload.get("text") or "")
    title = str(payload.get("title") or "") or _extract_title(raw_html)
    text = raw_text or html_to_text(raw_html)
    return title, _compact_text(text), raw_html


def _normalize_public_url(value: str, *, resolve_host: bool = False) -> tuple[str, str]:
    value = html.unescape(str(value or "").strip())
    parsed = urlparse(value)
    if parsed.scheme.lower() in UNSAFE_SCHEMES:
        return "", "unsafe_scheme"
    if parsed.scheme.lower() not in {"http", "https"}:
        return "", "unsafe_scheme"
    host = (parsed.hostname or "").lower()
    if not host:
        return "", "missing_host"
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost") or host.endswith(".local"):
        return "", "private_host"
    try:
        address = ipaddress.ip_address(host)
        if _is_blocked_ip(address):
            return "", "private_host"
    except ValueError:
        pass
    if resolve_host:
        try:
            _reject_blocked_dns_targets(host, parsed.port or (443 if parsed.scheme.lower() == "https" else 80))
        except ValueError:
            return "", "private_host"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    normalized = urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            "",
            urlencode(query, doseq=True),
            "",
        )
    )
    return normalized, ""


def _reject_blocked_dns_targets(host: str, port: int) -> None:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("host could not be resolved") from exc
    if not addresses:
        raise ValueError("host could not be resolved")
    for _, _, _, _, sockaddr in addresses:
        if _is_blocked_ip(ipaddress.ip_address(sockaddr[0])):
            raise ValueError("host resolves to a blocked address")


def _is_blocked_ip(address: ipaddress._BaseAddress) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _detect_language(text: str) -> str:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    latin_words = len(re.findall(r"[A-Za-z]{2,}", text or ""))
    japanese_chars = len(re.findall(r"[\u3040-\u30ff]", text or ""))
    korean_chars = len(re.findall(r"[\uac00-\ud7af]", text or ""))
    if japanese_chars:
        return "ja"
    if korean_chars:
        return "ko"
    if chinese_chars >= 8 or chinese_chars > latin_words:
        return "zh"
    if chinese_chars and latin_words:
        return "mixed"
    return "en" if latin_words else "unknown"


def _classify_topics(
    subject: str,
    body_text: str,
    rules: dict[str, Any],
) -> tuple[list[str], list[str], list[str], str]:
    text = f"{subject}\n{body_text}".lower()
    tags: list[str] = []
    matched: list[str] = []
    targets: list[str] = []
    primary = ""
    for rule in rules.get("topic_rules") or []:
        if not _any_keyword_matches(text, rule.get("keywords") or []):
            continue
        tag = str(rule.get("tag") or "").strip()
        if tag:
            tags.append(tag)
            matched.append(tag)
        if not primary and rule.get("primary_type"):
            primary = str(rule.get("primary_type"))
        targets.extend(str(item) for item in rule.get("targets") or [])
    return _dedupe_strings(tags), _dedupe_strings(matched), _dedupe_platforms(targets), primary


def _marketing_filter(
    subject: str,
    body_text: str,
    from_addr: str,
    tags: list[str],
    rules: dict[str, Any],
) -> dict[str, Any]:
    text = f"{subject}\n{from_addr}\n{body_text}".lower()
    matched_rules: list[str] = []
    score = 0
    for keyword in rules.get("marketing_keywords") or []:
        if _keyword_matches(text, keyword):
            matched_rules.append(f"keyword:{keyword}")
            score += 1
    sender_domain = _sender_domain(from_addr)
    for domain_rule in rules.get("marketing_sender_domains") or []:
        if str(domain_rule).lower() in sender_domain:
            matched_rules.append(f"sender:{domain_rule}")
            score += 1
    has_high_value_tag = any(tag in {"ai_research", "developer_practice", "industry_news", "security"} for tag in tags)
    disposition = "ignore" if score >= 2 and not has_high_value_tag else "keep"
    return {
        "disposition": disposition,
        "matched_rules": _dedupe_strings(matched_rules),
        "score": score,
        "configurable": True,
    }


def _translation_metadata(body_text: str, language: str, rules: dict[str, Any]) -> dict[str, Any]:
    if language == "zh" or (language == "unknown" and not str(body_text or "").strip()):
        return {
            "required": False,
            "target_language": "zh-Hans",
            "status": "not_required",
            "method": "local_chinese_draft",
            "text": "",
        }
    translated = _local_chinese_processing_draft(body_text, language, rules.get("translation_glossary") or {})
    return {
        "required": True,
        "target_language": "zh-Hans",
        "status": "draft",
        "method": "local_chinese_draft",
        "text": translated,
        "quality_note": "Local Chinese draft for routing and downstream generation; final article generation can refine it.",
    }


def _local_chinese_processing_draft(text: str, language: str, glossary: dict[str, str]) -> str:
    compact = _compact_text(text)
    sentences = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+", compact) if item.strip()]
    selected = sentences[:8] or [compact]
    language_name = {"en": "英语", "ja": "日语", "ko": "韩语", "mixed": "混合语言"}.get(language, "非中文")
    lines = [f"来源语言：{language_name}。"]
    sorted_glossary = sorted(glossary.items(), key=lambda item: len(str(item[0])), reverse=True)
    converted_items = []
    for sentence in selected:
        converted = sentence
        for source, target in sorted_glossary:
            converted = re.sub(re.escape(str(source)), str(target), converted, flags=re.IGNORECASE)
        converted_items.append(converted)
    if language == "en":
        lines.append("中文整理要点：")
        lines.extend(f"- {item}" for item in converted_items if item)
    else:
        lines.append("中文整理要点：")
        lines.append("- 该邮件为非中文来源，已进入中文处理流程；请在后续文章生成阶段按 zh-Hans 继续精译与改写。")
        signals = _translated_signal_terms(compact, glossary)
        if signals:
            lines.append(f"- 识别到的主题信号：{', '.join(signals)}。")
        lines.append(f"- 原文摘录：{_compact_text(' '.join(selected))[:800]}")
    return "\n".join(line for line in lines if line)[:4000]


def _translated_signal_terms(text: str, glossary: dict[str, str]) -> list[str]:
    lowered = (text or "").lower()
    signals = []
    for source, target in glossary.items():
        if _keyword_matches(lowered, source) and str(target) not in signals:
            signals.append(str(target))
    return signals[:8]


def _is_news_like(subject: str, body_text: str, baseline: dict[str, Any], tags: list[str], rules: dict[str, Any]) -> bool:
    if baseline.get("primary_type") == "news" or "industry_news" in tags:
        return True
    text = f"{subject}\n{body_text}".lower()
    return _any_keyword_matches(text, rules.get("news_keywords") or [])


def _build_analysis_text(body_text: str, translation: dict[str, Any], links: dict[str, Any]) -> str:
    sections: list[str] = []
    if translation.get("required") and translation.get("text"):
        sections.append("【中文处理稿】\n" + str(translation["text"]).strip())
    if body_text.strip():
        title = "【原始邮件正文】" if translation.get("required") else "【邮件正文】"
        sections.append(title + "\n" + body_text.strip())
    enriched_lines = []
    for item in links.get("items", []):
        enrichment = item.get("enrichment") or {}
        if item.get("enrichment_status") == "ok" and enrichment.get("excerpt"):
            title = enrichment.get("title") or item.get("label") or item.get("domain") or item.get("url")
            enriched_lines.append(f"- {title}\n  {item.get('url')}\n  {enrichment.get('excerpt')}")
        elif item.get("label") or item.get("context"):
            label = item.get("label") or item.get("context")
            enriched_lines.append(f"- {label}\n  {item.get('url')}")
    if enriched_lines:
        sections.append("【链接补充材料】\n" + "\n".join(enriched_lines[:5]))
    return "\n\n".join(sections).strip()[:12000]


def _public_link_report(links: dict[str, Any]) -> dict[str, Any]:
    return {
        "extracted_count": links["extracted_count"],
        "kept_count": links["kept_count"],
        "skipped_count": links["skipped_count"],
        "skipped_reasons": links["skipped_reasons"],
        "items": links["items"],
    }


def _reason(classification: dict[str, Any], marketing_report: dict[str, Any], topics: list[str], links: dict[str, Any]) -> str:
    if marketing_report["disposition"] == "ignore":
        return "Matched configurable marketing filter rules; content is retained but excluded from generation by default."
    parts = ["Rule-based email analysis completed."]
    if topics:
        parts.append(f"Matched topic tags: {', '.join(topics)}.")
    if links["kept_count"]:
        parts.append(f"Retained {links['kept_count']} relevant link(s) for downstream context.")
    if classification.get("language") not in {"zh", "unknown"}:
        parts.append("Chinese processing draft generated for non-Chinese source text.")
    return " ".join(parts)


def _score_from_tags(tags: list[str], links: dict[str, Any]) -> int:
    score = 5 + min(len(tags), 3)
    if links.get("kept_count"):
        score += 1
    return max(1, min(10, score))


def _link_relevance_score(
    subject: str,
    body_text: str,
    label: str,
    context: str,
    url: str,
    rules: dict[str, Any],
) -> int:
    text = f"{label}\n{context}\n{url}".lower()
    if any(word in text for word in ("unsubscribe", "preferences", "privacy", "view in browser", "退订", "隐私")):
        return 0
    score = 1
    subject_terms = {term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]{3,}", subject or "")}
    if subject_terms and _any_keyword_matches(text, subject_terms):
        score += 2
    for rule in rules.get("topic_rules") or []:
        if _any_keyword_matches(text, rule.get("keywords") or []):
            score += 2
    if label:
        score += 1
    if context:
        score += 1
    if body_text and url in body_text:
        score += 1
    return min(score, 10)


def _related_excerpt(text: str, query_text: str, limit: int) -> str:
    compact = _compact_text(text)
    if len(compact) <= limit:
        return compact
    query_terms = [term.lower() for term in re.findall(r"[A-Za-z\u4e00-\u9fff]{4,}", query_text or "")][:20]
    lower = compact.lower()
    first_hit = next((lower.find(term) for term in query_terms if lower.find(term) >= 0), -1)
    if first_hit < 0:
        return compact[:limit].rstrip()
    start = max(0, first_hit - limit // 4)
    return compact[start : start + limit].strip()


def _extract_title(raw_html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html or "", re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _compact(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))))


def _context_around(text: str, start: int, end: int, width: int = 100) -> str:
    return _compact((text or "")[max(0, start - width) : min(len(text or ""), end + width)])


def _sender_domain(from_addr: str) -> str:
    match = re.search(r"@([A-Za-z0-9.-]+)", from_addr or "")
    return (match.group(1) if match else "").lower()


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _compact_text(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", str(value or "").replace("\r\n", "\n")).strip()


def _bounded_int(value: Any, default: int, *, min_value: int = 1, max_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dedupe_platforms(values: list[str]) -> list[str]:
    wanted = set(_dedupe_strings(values))
    return [platform for platform in DEFAULT_CONTENT_PLATFORMS if platform in wanted]
