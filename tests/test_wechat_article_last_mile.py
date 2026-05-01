from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from config.validation import validate_wechat_config
from monitor import wechat_publisher
from scripts.article_generator import (
    ArticleGenerationPipeline,
    WechatArticlePromptEngine,
    _parse_article_quality_evaluation,
)
from scripts.llm_client import PROMPT_INPUT_PLACEHOLDER


def test_local_wechat_markdown_renderer_preserves_rich_markdown(tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text(
        """---
title: "AI 创作链路"
author: "作者"
summary: "摘要"
---

类型：文章
选题：AI 创作链路
生成时间：2026-04-30T00:00:00

```json
{"type":"article","task_id":"task-1"}
```

## 摘要

| 项目 | 说明 |
| --- | --- |
| 表格 | **保留** |

- 列表项
1. 有序项

```python
print("hello")
```

> 引用内容

保留 emoji 🚀 和 [链接](https://example.com)。
""",
        encoding="utf-8",
    )

    result = wechat_publisher.render_md_to_html_for_wechat(draft, renderer="local")

    assert result.title == "AI 创作链路"
    assert result.author == "作者"
    assert result.digest == "摘要"
    assert result.renderer == "local"
    assert "<table" in result.content
    assert "<ul" in result.content
    assert "<ol" in result.content
    assert "<pre" in result.content
    assert "<blockquote" in result.content
    assert "🚀" in result.content
    assert "task-1" not in result.content
    assert "类型：文章" not in result.content


def test_local_renderer_strips_llm_thinking_and_keeps_digest_byte_safe(tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text(
        """---
title: "AI 创作链路"
author: "作者"
summary: "<think 模型内部推理不应该作为摘要发送给微信"
---

<think>
这里是模型思考过程，不能进入公众号正文。
</think>

# 可发布正文

这是可以发布的中文内容，用于生成一个安全摘要，避免微信公众号 description size out of limit。
""",
        encoding="utf-8",
    )

    result = wechat_publisher.render_md_to_html_for_wechat(draft, renderer="local")

    assert "<think" not in result.content.lower()
    assert "模型思考过程" not in result.content
    assert result.digest
    assert "模型内部推理" not in result.digest
    assert len(result.digest.encode("utf-8")) <= wechat_publisher._WECHAT_DIGEST_MAX_BYTES


def test_local_renderer_keeps_intro_that_mentions_publish_advice(tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text(
        """---
title: "发布策略"
summary: "摘要"
---

这段导语会自然提到发布建议，但它不是内部草稿材料，必须保留。

# 正文开始

这是正文内容。
""",
        encoding="utf-8",
    )

    result = wechat_publisher.render_md_to_html_for_wechat(draft, renderer="local")

    assert "这段导语会自然提到发布建议" in result.content
    assert "这是正文内容" in result.content


def test_wechat_payload_validation_rejects_over_byte_digest():
    errors = wechat_publisher.validate_wechat_article_payload(
        title="标题",
        content="<p>正文</p>",
        digest="摘要" * 80,
    )

    assert any("摘要不能超过" in error and "字节" in error for error in errors)


def test_wechat_digest_truncation_keeps_ellipsis_byte_safe():
    digest = wechat_publisher._normalize_wechat_digest("摘要" * 80)

    assert digest.endswith("...")
    assert len(digest.encode("utf-8")) <= wechat_publisher._WECHAT_DIGEST_MAX_BYTES


def test_baoyu_renderer_receives_theme_and_color(monkeypatch, tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text("# 标题\n\n正文", encoding="utf-8")
    script = tmp_path / "main.ts"
    script.write_text("// fake", encoding="utf-8")
    html_path = draft.with_suffix(".html")
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(wechat_publisher.shutil, "which", lambda _name: "npx")

    def fake_run(command, **_kwargs):
        captured["command"] = command
        html_path.write_text("<html><body><p>styled</p><script>x()</script></body></html>", encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "title": "标题",
                    "author": "作者",
                    "summary": "摘要",
                    "htmlPath": str(html_path),
                },
                ensure_ascii=False,
            ),
            stderr="",
        )

    monkeypatch.setattr(wechat_publisher.subprocess, "run", fake_run)

    result = wechat_publisher.render_md_to_html_for_wechat(
        draft,
        renderer="baoyu",
        theme="modern",
        color="red",
        baoyu_script=script,
    )

    assert result.renderer == "baoyu-markdown-to-html"
    assert result.content == "<p>styled</p>"
    assert "--theme" in captured["command"]
    assert "modern" in captured["command"]
    assert "--color" in captured["command"]
    assert "red" in captured["command"]


def test_baoyu_runner_uses_native_bun_before_npx(monkeypatch):
    calls: list[str] = []

    def fake_which(name):
        calls.append(name)
        if name == "bun.exe":
            return "C:\\bin\\bun.exe"
        if name == "npx.cmd":
            return "C:\\bin\\npx.cmd"
        return None

    monkeypatch.delenv("BAOYU_MARKDOWN_TO_HTML_COMMAND", raising=False)
    monkeypatch.setattr(wechat_publisher.shutil, "which", fake_which)

    assert wechat_publisher._resolve_baoyu_runner() == ["C:\\bin\\bun.exe"]
    assert "npx.cmd" not in calls


def test_baoyu_runner_skips_npx_bun_on_windows_without_native_bun(monkeypatch):
    monkeypatch.delenv("BAOYU_MARKDOWN_TO_HTML_COMMAND", raising=False)
    monkeypatch.setattr(wechat_publisher.os, "name", "nt")
    monkeypatch.setattr(
        wechat_publisher.shutil,
        "which",
        lambda name: "C:\\bin\\npx.cmd" if name == "npx.cmd" else None,
    )

    with pytest.raises(RuntimeError, match="Windows 环境不使用 npx -y bun"):
        wechat_publisher._resolve_baoyu_runner()


def test_strict_baoyu_renderer_does_not_hide_failures(tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text("# 标题\n\n正文", encoding="utf-8")

    with pytest.raises(RuntimeError, match="禁止回退"):
        wechat_publisher.render_md_to_html_for_wechat(
            draft,
            renderer="baoyu",
            baoyu_script=tmp_path / "missing.ts",
        )


def test_auto_baoyu_renderer_falls_back_to_local_with_warning(monkeypatch, tmp_path: Path):
    draft = tmp_path / "draft.md"
    draft.write_text("# 标题\n\n- 正文", encoding="utf-8")

    def fail_baoyu(*_args, **_kwargs):
        raise RuntimeError("baoyu unavailable")

    monkeypatch.setattr(wechat_publisher, "_render_with_baoyu", fail_baoyu)

    result = wechat_publisher.render_md_to_html_for_wechat(draft, renderer="auto")

    assert result.renderer == "local"
    assert "baoyu unavailable" in result.warnings
    assert "<ul" in result.content


def test_wechat_article_payload_validation_catches_publish_limits():
    errors = wechat_publisher.validate_wechat_article_payload(
        title="标" * 33,
        author="作" * 17,
        digest="摘" * 129,
        content="<p>正文</p><style>bad</style>",
    )

    assert any("标题不能超过" in item for item in errors)
    assert any("作者不能超过" in item for item in errors)
    assert any("摘要不能超过" in item for item in errors)
    assert any("<script>/<style>" in item for item in errors)


def test_wechat_publish_api_rejects_invalid_article_before_task_creation(monkeypatch, tmp_path: Path):
    import server.__main__ as server_main

    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "load_config",
        lambda: {
            "wechat_app_id": "wx1234567890abcdef",
            "wechat_app_secret": "0123456789abcdef0123456789abcdef",
            "wechat_default_theme": "default",
            "wechat_default_color": "blue",
            "wechat_markdown_renderer": "local",
            "article_output_dir": str(tmp_path / "articles"),
        },
    )
    monkeypatch.setattr(
        server_main._db,
        "create_wechat_publish_task",
        lambda **_kwargs: pytest.fail("should reject before creating a task"),
    )

    server_main.MonitorHandler._handle_wechat_publish(
        handler,
        {"title": "超" * 33, "content": "<p>body</p>"},
        "draft",
    )

    assert sent
    assert sent[0][1] == 400
    assert "标题不能超过" in sent[0][0]["error"]


def test_wechat_publish_api_returns_render_metadata_on_success(monkeypatch, tmp_path: Path):
    import server.__main__ as server_main

    article_root = tmp_path / "articles"
    draft_dir = article_root / "task-1"
    draft_dir.mkdir(parents=True)
    draft = draft_dir / "draft.md"
    draft.write_text("# 标题\n\n正文", encoding="utf-8")
    html_path = draft.with_suffix(".wechat.html")
    captured: dict[str, object] = {}
    sent = []

    class FakeThread:
        def __init__(self, *args, **kwargs):
            captured["thread_name"] = kwargs.get("name")

        def start(self):
            captured["thread_started"] = True

    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "load_config",
        lambda: {
            "wechat_app_id": "wx1234567890abcdef",
            "wechat_app_secret": "0123456789abcdef0123456789abcdef",
            "wechat_default_theme": "default",
            "wechat_default_color": "blue",
            "wechat_markdown_renderer": "auto",
            "article_output_dir": str(article_root),
        },
    )
    monkeypatch.setattr(
        wechat_publisher,
        "render_md_to_html_for_wechat",
        lambda *_args, **_kwargs: wechat_publisher.WechatArticleRenderResult(
            title="标题",
            author="作者",
            digest="摘要",
            content="<p>正文</p>",
            renderer="local",
            html_path=str(html_path),
            warnings=["baoyu unavailable"],
        ),
    )

    def fake_create_wechat_publish_task(**kwargs):
        captured["create_kwargs"] = kwargs
        return "wechat-publish-1"

    monkeypatch.setattr(server_main._db, "create_wechat_publish_task", fake_create_wechat_publish_task)
    monkeypatch.setattr(server_main.threading, "Thread", FakeThread)

    server_main.MonitorHandler._handle_wechat_publish(
        handler,
        {"draft_path": str(draft)},
        "draft",
    )

    assert sent == [
        (
            {
                "task_id": "wechat-publish-1",
                "status": "pending",
                "renderer": "local",
                "html_path": str(html_path),
                "warnings": ["baoyu unavailable"],
            },
            202,
        )
    ]
    assert captured["create_kwargs"]["html_content"] == "<p>正文</p>"
    assert captured["thread_started"] is True


def test_wechat_config_includes_local_publish_quota(monkeypatch):
    import server.__main__ as server_main

    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))

    monkeypatch.setattr(
        server_main._db,
        "load_config",
        lambda: {
            "wechat_app_id": "wx1234567890abcdef",
            "wechat_app_secret": "0123456789abcdef",
            "wechat_default_author": "作者",
            "wechat_default_theme": "default",
            "wechat_default_color": "blue",
            "wechat_markdown_renderer": "local",
            "wechat_baoyu_markdown_to_html_script": "",
            "wechat_publish_monthly_limit": "4",
            "wechat_need_open_comment": True,
            "wechat_only_fans_can_comment": False,
        },
    )
    monkeypatch.setattr(
        server_main._db,
        "get_wechat_publish_monthly_usage",
        lambda: {"month": "2026-04", "used": 2, "active": 1},
    )

    server_main.MonitorHandler._api_wechat_config(handler)

    assert sent
    payload, status = sent[0]
    assert status == 200
    assert "wechat_app_secret" not in payload
    assert payload["wechat_publish_monthly_limit"] == 4
    assert payload["publish_quota"] == {
        "month": "2026-04",
        "limit": 4,
        "used": 2,
        "active": 1,
        "remaining": 1,
        "unlimited": False,
        "exhausted": False,
    }


def test_wechat_prompt_engine_adds_platform_contracts():
    engine = WechatArticlePromptEngine.from_config(
        {
            "article_wechat_prompt_role": "资深编辑",
            "article_wechat_prompt_reader_persona": "开发者",
            "article_wechat_prompt_style": "短段落",
            "article_wechat_prompt_max_chars": 3000,
        }
    )

    prompt = engine.build_optimize_prompt()

    assert "微信公众号" in prompt
    assert "Markdown" in prompt
    assert "<script>" in prompt
    assert "3000" in prompt
    assert PROMPT_INPUT_PLACEHOLDER in prompt

    style_prompt = engine.build_style_analysis_prompt("wechat_article")
    rewrite_prompt = engine.build_rewrite_prompt("zh-Hans")
    evaluation_prompt = engine.build_evaluation_prompt("zh-Hans")
    revision_prompt = engine.build_revision_prompt("zh-Hans")

    assert "风格画像" in style_prompt
    assert "不要复制原文句子" in style_prompt
    assert "二次创作方法" in rewrite_prompt
    assert "风格迁移" in rewrite_prompt
    assert "只输出 JSON" in evaluation_prompt
    assert "score" in evaluation_prompt
    assert "修订" in revision_prompt
    assert all(PROMPT_INPUT_PLACEHOLDER in item for item in [style_prompt, rewrite_prompt, evaluation_prompt, revision_prompt])


def test_article_quality_evaluation_parser_accepts_fenced_json():
    report = _parse_article_quality_evaluation(
        """```json
{"score": "85/100", "rationale": "结构清晰", "strengths": ["短段落"], "risks": ["标题偏长"], "revision_instructions": "压缩标题"}
```""",
        threshold=7.0,
    )

    assert report["score"] == 8.5
    assert report["passes_threshold"] is True
    assert report["rationale"] == "结构清晰"
    assert report["strengths"] == ["短段落"]
    assert report["risks"] == ["标题偏长"]
    assert report["revision_instructions"] == "压缩标题"


def test_article_draft_includes_frontmatter_for_baoyu_metadata():
    pipeline = ArticleGenerationPipeline(
        "task-1",
        cfg={"article_author": "作者", "wechat_default_author": "默认作者"},
    )

    draft = pipeline._build_draft("标题", "这是摘要\n\n- 要点", "正文")

    assert draft.startswith("---\n")
    assert 'title: "标题"' in draft
    assert 'author: "作者"' in draft
    assert 'summary: "这是摘要 要点"' in draft
    assert "```json" in draft


def test_wechat_config_validation_accepts_renderer_modes():
    cfg = {
        "wechat_app_id": "wx1234567890abcdef",
        "wechat_app_secret": "0123456789abcdef",
        "wechat_default_theme": "default",
        "wechat_default_color": "blue",
        "wechat_markdown_renderer": "invalid",
    }

    assert any("wechat_markdown_renderer" in item for item in validate_wechat_config(cfg))


def test_strict_baoyu_config_requires_existing_script(tmp_path: Path):
    cfg = {
        "wechat_app_id": "wx1234567890abcdef",
        "wechat_app_secret": "0123456789abcdef",
        "wechat_default_theme": "default",
        "wechat_default_color": "blue",
        "wechat_markdown_renderer": "baoyu-markdown-to-html",
        "wechat_baoyu_markdown_to_html_script": str(tmp_path / "missing.ts"),
    }

    errors = validate_wechat_config(cfg)

    assert any("baoyu-markdown-to-html 脚本" in item or "文件不存在" in item for item in errors)


def test_strict_baoyu_config_requires_runner(monkeypatch, tmp_path: Path):
    script = tmp_path / "main.ts"
    script.write_text("// fake", encoding="utf-8")
    cfg = {
        "wechat_app_id": "wx1234567890abcdef",
        "wechat_app_secret": "0123456789abcdef",
        "wechat_default_theme": "default",
        "wechat_default_color": "blue",
        "wechat_markdown_renderer": "baoyu-markdown-to-html",
        "wechat_baoyu_markdown_to_html_script": str(script),
    }

    monkeypatch.delenv("BAOYU_MARKDOWN_TO_HTML_COMMAND", raising=False)
    monkeypatch.setattr("config.validation.os.name", "nt")
    monkeypatch.setattr("config.validation.shutil.which", lambda _name: None)

    errors = validate_wechat_config(cfg)

    assert any("本机 Bun" in item for item in errors)
