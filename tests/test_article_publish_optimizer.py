from __future__ import annotations

import json

from scripts import article_publish_optimizer as optimizer


def test_clean_publish_body_removes_internal_summary_material():
    raw = """---
title: "article_x"
summary: "摘要素材 一句话摘要 不应发布"
---

类型：文章
选题：article_x
生成时间：2026-05-01T14:14:36+08:00

```json
{"type":"article","task_id":"article_x"}
```

## 摘要

# 摘要素材

## 一句话摘要

这是内部摘要素材。

## 推荐章节结构

| 章节 | 标题 |
| --- | --- |

# 真正标题

**摘要**：这句摘要放在 digest，不进入正文。

---

## 正文第一节

正文内容。
"""

    body = optimizer.clean_publish_body(raw)

    assert "摘要素材" not in body
    assert "推荐章节结构" not in body
    assert "真正标题" not in body
    assert body.startswith("## 正文第一节")
    assert "正文内容" in body


def test_clean_publish_body_keeps_public_intro_after_markdown_separator():
    raw = """# 公共标题

**摘要**：这句摘要放入 digest。

---

## 公开开头

这段不能被当成 frontmatter 删除。

---

## 第二节

正文继续。
"""

    body = optimizer.clean_publish_body(raw)

    assert body.startswith("## 公开开头")
    assert "这段不能被当成 frontmatter 删除" in body
    assert "## 第二节" in body


def test_clean_publish_body_keeps_legitimate_intro_before_first_h1():
    raw = """---
title: "公开标题"
summary: "摘要"
---

这是一段真正要发布的导语，即使它出现在第一个一级标题之前也不能删除。

# 第一部分

正文内容。
"""

    body = optimizer.clean_publish_body(raw)

    assert body.startswith("这是一段真正要发布的导语")
    assert "# 第一部分" in body
    assert "正文内容" in body


def test_hot_title_candidates_uses_llm_scores_and_limits_length(monkeypatch):
    def fake_llm_call(_cfg, _prompt, payload, *, model_key):
        assert model_key == "article_llm_summary_model"
        assert "正文" in payload["body"]
        return json.dumps(
            [
                {
                    "title": "这个标题故意非常非常非常非常长需要截断",
                    "score": 90,
                    "reason": "有好奇心",
                    "metrics": {
                        "curiosity": 28,
                        "relevance": 28,
                        "specificity": 18,
                        "clarity": 8,
                        "integrity": 8,
                    },
                },
                {"title": "你的心智为何如此奇怪", "score": 95, "reason": "贴题"},
            ],
            ensure_ascii=False,
        )

    monkeypatch.setattr(optimizer, "_llm_call", fake_llm_call)

    candidates = optimizer.generate_hot_title_candidates("## 正文\n\n心智内容", "article_x", {"llm_api_key": "k"})

    assert candidates[0].title == "你的心智为何如此奇怪"
    assert len(candidates[1].title) <= optimizer.HOT_TITLE_MAX_CHARS
    assert "article_x" not in {item.title for item in candidates}


def test_publish_summary_is_plain_and_120_chars(monkeypatch):
    monkeypatch.setattr(
        optimizer,
        "_llm_call",
        lambda *_args, **_kwargs: "摘要素材：" + "这是一段很长的公众号摘要" * 20,
    )

    summary = optimizer.generate_publish_summary("## 正文\n\n正文内容", "标题", {"llm_api_key": "k"})

    assert "摘要素材" not in summary
    assert len(summary) <= optimizer.PUBLISH_SUMMARY_MAX_CHARS
    assert len(summary.encode("utf-8")) <= optimizer.PUBLISH_SUMMARY_MAX_BYTES
    assert summary.endswith("...")


def test_zhuque_detection_records_skip_without_official_api():
    report = optimizer.run_zhuque_detection(body="正文" * 200, image_paths=["images/a.jpg"], cfg={})

    assert report["status"] == "skipped_no_api"
    assert report["provider"] == "zhuque"
    assert "no stable public API" in report["notes"][0]


def test_zhuque_detection_runs_text_and_image_apis(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_api_call(url, payload, timeout_seconds):
        calls.append((url, payload))
        assert timeout_seconds == 9
        return {"ok": True, "kind": "image" if "image_path" in payload else "text"}

    monkeypatch.setattr(optimizer, "_optional_zhuque_api_call", fake_api_call)

    report = optimizer.run_zhuque_detection(
        body="正文内容",
        image_paths=["images/a.jpg", "images/b.jpg"],
        cfg={
            "zhuque_text_api_url": "https://zhuque.test/text",
            "zhuque_image_api_url": "https://zhuque.test/image",
            "zhuque_detection_timeout_seconds": 9,
            "zhuque_detection_parallelism": 2,
        },
    )

    assert report["status"] == "completed"
    assert report["text"] == {"ok": True, "kind": "text"}
    assert sorted(item["path"] for item in report["images"]) == ["images/a.jpg", "images/b.jpg"]
    assert {url for url, _payload in calls} == {"https://zhuque.test/text", "https://zhuque.test/image"}
