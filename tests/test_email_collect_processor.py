from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.email_collect.processor import (
    MAX_LINKS,
    RULE_SCHEMA_VERSION,
    _default_fetch_url,
    analyze_email_content,
    apply_platform_sensitive_filter,
    coerce_email_analysis_rules_payload,
    extract_relevant_links,
    validate_email_analysis_rules,
)
from monitor.email_collect.variants import build_platform_variant


def test_processor_filters_marketing_with_configurable_rules():
    result = analyze_email_content(
        subject="Limited time coupon for your account",
        from_addr="Marketing <deals@promo.example.com>",
        body_text=(
            "Use this coupon today for a limited time discount. "
            "Manage preferences or unsubscribe from future promotion emails."
        ),
    )

    classification = result["classification"]

    assert classification["primary_type"] == "marketing"
    assert classification["action"] == "ignore"
    assert classification["recommended_targets"] == []
    assert classification["filter"]["disposition"] == "ignore"
    assert "keyword:coupon" in classification["filter"]["matched_rules"]


def test_processor_preserves_ignore_for_short_irrelevant_messages():
    result = analyze_email_content(
        subject="FYI",
        from_addr="teammate@example.com",
        body_text="short note",
    )

    classification = result["classification"]

    assert classification["primary_type"] == "irrelevant"
    assert classification["action"] == "ignore"
    assert classification["recommended_targets"] == []
    assert classification["value_score"] == 2


def test_processor_does_not_match_latin_keywords_inside_newsletter():
    result = analyze_email_content(
        subject="Newsletter update",
        body_text=(
            "This newsletter shares routine product tips and account reminders. "
            "It focuses on onboarding notes, maintenance windows, and internal housekeeping."
        ),
    )

    classification = result["classification"]

    assert "industry_news" not in classification["matched_rules"]["topics"]
    assert classification["platform_compliance"]["news_like"] is False
    assert "platform_sensitive_review" not in classification["risk_flags"]


def test_processor_extracts_and_enriches_relevant_links_without_tracking_noise():
    html = """
    <p>Read the benchmark report for the new model.</p>
    <a href="https://example.com/report?utm_source=email&ref=feed">Benchmark report</a>
    <a href="mailto:hello@example.com">Email us</a>
    """

    result = analyze_email_content(
        subject="Research benchmark report",
        body_text="This research benchmark email links to the full report.",
        html_body=html,
        expand_links=True,
        link_fetcher=lambda _url: {
            "title": "Benchmark Report",
            "html": "<html><title>Benchmark Report</title><p>The dataset and evaluation methodology are reusable.</p></html>",
        },
    )

    links = result["classification"]["links"]

    assert links["kept_count"] == 1
    assert links["items"][0]["url"] == "https://example.com/report?ref=feed"
    assert links["items"][0]["enrichment_status"] == "ok"
    assert "evaluation methodology" in links["items"][0]["enrichment"]["excerpt"]
    assert result["cleaning_report"]["link_extraction"]["skipped_reasons"]["unsafe_scheme"] == 1


def test_processor_generates_chinese_processing_draft_for_non_chinese_content():
    result = analyze_email_content(
        subject="Developer migration guide",
        body_text=(
            "This developer guide explains the API migration methodology. "
            "It includes release risk, model evaluation, and dataset setup."
        ),
    )

    translation = result["classification"]["translation"]

    assert result["classification"]["language"] == "en"
    assert translation["required"] is True
    assert "开发者" in translation["text"]
    assert "【中文处理稿】" in result["classification"]["analysis_text"]


def test_processor_marks_other_non_chinese_content_for_chinese_processing():
    result = analyze_email_content(
        subject="モデル評価レポート",
        body_text="新しいモデル評価とリスク分析を共有します。",
    )

    translation = result["classification"]["translation"]

    assert result["classification"]["language"] == "ja"
    assert translation["required"] is True
    assert "来源语言：日语" in translation["text"]
    assert "中文整理要点" in translation["text"]
    assert "【中文处理稿】" in result["classification"]["analysis_text"]


def test_platform_sensitive_filter_is_applied_to_news_variants():
    body = "这是一篇新闻报道，涉及谣言、枪击和内幕消息，需要谨慎发布。"

    filtered, report = apply_platform_sensitive_filter(body, platform="toutiao")
    variant = build_platform_variant(
        platform="toutiao",
        source_title="新闻报道",
        body_text=body,
        classification={
            "primary_type": "news",
            "secondary_types": ["industry_news"],
            "risk_flags": ["platform_sensitive_review"],
        },
    )

    assert "谣言" not in filtered
    assert "枪击" not in variant["body"]
    assert "内幕" not in variant["body"]
    assert report["changed"] is True
    assert variant["metadata"]["platform_compliance"]["changed"] is True


def test_extract_relevant_links_rejects_private_urls():
    report = extract_relevant_links(
        subject="Internal report",
        body_text="Read https://127.0.0.1/admin and https://example.com/report for more report details.",
    )

    assert report["kept_count"] == 1
    assert report["items"][0]["domain"] == "example.com"
    assert report["skipped_reasons"]["private_host"] == 1


def test_extract_relevant_links_bounds_configured_link_volume():
    body = "\n".join(f"Report link https://example.com/report-{idx}" for idx in range(40))

    report = extract_relevant_links(
        subject="Research report",
        body_text=body,
        rules={"link_enrichment": {"max_links": 1000}},
    )

    assert report["kept_count"] == MAX_LINKS


def test_default_link_fetcher_rejects_private_urls_before_network_io():
    try:
        _default_fetch_url("http://127.0.0.1/admin")
    except ValueError as exc:
        assert "blocked URL" in str(exc)
    else:
        raise AssertionError("private URL was not rejected")


def test_validate_email_analysis_rules_normalizes_valid_operator_payload():
    validation = validate_email_analysis_rules(
        {
            "marketing_keywords": [" Promo ", "promo", "优惠"],
            "topic_rules": [
                {
                    "tag": "ops_digest",
                    "primary_type": "news",
                    "keywords": ["运营", "增长"],
                    "targets": ["wechat", "zhihu"],
                }
            ],
            "translation_glossary": {"launch": "发布"},
            "platform_sensitive_words": {"wechat": {"禁词": "合规表述"}},
            "link_enrichment": {"max_links": "5", "timeout_seconds": 8},
        }
    )

    assert validation["ok"] is True
    assert validation["errors"] == []
    assert validation["rules"]["marketing_keywords"] == ["Promo", "promo", "优惠"]
    assert validation["rules"]["link_enrichment"] == {"max_links": 5, "timeout_seconds": 8}
    assert validation["rules"]["topic_rules"][0]["targets"] == ["wechat", "zhihu"]


def test_validate_email_analysis_rules_rejects_unknown_top_level_key():
    validation = validate_email_analysis_rules({"unknown_rule": []})

    assert validation["ok"] is False
    assert "unknown_rule: unknown rule key" in validation["errors"]


def test_validate_email_analysis_rules_rejects_unsupported_platform():
    validation = validate_email_analysis_rules(
        {
            "topic_rules": [
                {
                    "tag": "bad_platform",
                    "keywords": ["research"],
                    "targets": ["wechat", "unsupported"],
                }
            ],
            "platform_sensitive_words": {"unsupported": {"x": "y"}},
        }
    )

    assert validation["ok"] is False
    assert any("unsupported platform(s): unsupported" in error for error in validation["errors"])
    assert "platform_sensitive_words.unsupported: unsupported platform" in validation["errors"]


def test_validate_email_analysis_rules_rejects_out_of_range_link_enrichment():
    validation = validate_email_analysis_rules(
        {"link_enrichment": {"max_depth": 99, "timeout_seconds": 0, "unknown": 1}}
    )

    assert validation["ok"] is False
    assert "link_enrichment.max_depth: must be between 1 and 3" in validation["errors"]
    assert "link_enrichment.timeout_seconds: must be between 1 and 30" in validation["errors"]
    assert "link_enrichment.unknown: unknown option" in validation["errors"]


def test_coerce_email_analysis_rules_payload_accepts_export_wrapper():
    validation = coerce_email_analysis_rules_payload(
        {
            "schema_version": RULE_SCHEMA_VERSION,
            "exported_at": "2026-05-02T16:00:00+08:00",
            "rules": {"marketing_sender_domains": ["newsletters."]},
        }
    )

    assert validation["ok"] is True
    assert validation["rules"] == {"marketing_sender_domains": ["newsletters."]}


def test_coerce_email_analysis_rules_payload_rejects_unsupported_export_schema():
    validation = coerce_email_analysis_rules_payload(
        {
            "schema_version": "email-analysis-rules-schema-v0",
            "rules": {"marketing_sender_domains": ["newsletters."]},
        }
    )

    assert validation["ok"] is False
    assert validation["rules"] == {}
    assert "schema_version: unsupported version email-analysis-rules-schema-v0" in validation["errors"]
