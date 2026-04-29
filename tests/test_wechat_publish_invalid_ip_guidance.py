"""Regression tests for actionable WeChat publish errors."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from monitor import wechat_publisher


class _FakeWechatResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_access_token_invalid_ip_error_tells_user_to_update_wechat_ip_whitelist(monkeypatch):
    wechat_publisher._ACCESS_TOKEN_CACHE.clear()

    def fake_urlopen(url, timeout=15):
        return _FakeWechatResponse(
            {
                "errcode": 40164,
                "errmsg": (
                    "invalid ip 1.119.141.218 ipv6 ::ffff:1.119.141.218, "
                    "not in whitelist rid: 69f057f7-6e7d2b41-3ee16d11"
                ),
            }
        )

    monkeypatch.setattr(wechat_publisher.urllib.request, "urlopen", fake_urlopen)
    publisher = wechat_publisher.WechatPublisher(
        app_id="wx1234567890abcdef",
        app_secret="0123456789abcdef0123456789abcdef",
    )

    with pytest.raises(RuntimeError) as excinfo:
        publisher._get_access_token()

    message = str(excinfo.value)
    assert "IP 白名单" in message
    assert "1.119.141.218" in message
    assert "微信公众号后台" in message


def test_save_to_draft_falls_back_to_default_cover_when_ai_cover_generation_fails(monkeypatch, tmp_path):
    publisher = wechat_publisher.WechatPublisher(
        app_id="wx1234567890abcdef",
        app_secret="0123456789abcdef0123456789abcdef",
        data_dir=str(tmp_path / "articles"),
    )

    monkeypatch.setattr(
        publisher,
        "_upload_images_in_html",
        lambda content, *, base_dir=None: (content, "", []),
    )

    uploaded_paths: list[Path] = []

    def fake_upload_image(image_path, *, base_dir=None):
        path = Path(image_path)
        uploaded_paths.append(path)
        assert path.is_file()
        assert path.suffix == ".png"
        return {"media_id": "generated-cover-media-id"}

    captured_draft: dict = {}

    def fake_create_draft(**kwargs):
        captured_draft.update(kwargs)
        return "draft-media-id"

    def fail_generate_wechat_cover(**kwargs):
        return wechat_publisher._ensure_default_cover_image(
            base_dir=kwargs.get("base_dir"),
            data_dir=publisher.data_dir,
        )

    monkeypatch.setattr(publisher, "_generate_wechat_cover", fail_generate_wechat_cover)
    monkeypatch.setattr(publisher, "_upload_image", fake_upload_image)
    monkeypatch.setattr(publisher, "_create_draft", fake_create_draft)

    result = publisher.save_to_draft(
        "No image article",
        "<p>content without images</p>",
        base_dir=tmp_path,
    )

    assert result.success
    assert result.wx_article_id == "draft-media-id"
    assert uploaded_paths
    assert uploaded_paths[0].name == "_wechat_default_cover.png"
    assert captured_draft["thumb_media_id"] == "generated-cover-media-id"


def test_save_to_draft_uses_ai_generated_cover_before_default_cover(monkeypatch, tmp_path):
    publisher = wechat_publisher.WechatPublisher(
        app_id="wx1234567890abcdef",
        app_secret="0123456789abcdef0123456789abcdef",
        data_dir=str(tmp_path / "articles"),
    )

    monkeypatch.setattr(
        publisher,
        "_upload_images_in_html",
        lambda content, *, base_dir=None: (content, "", []),
    )

    ai_cover = tmp_path / "wechat_ai_cover.png"

    def fake_generate_wechat_cover(**kwargs):
        ai_cover.write_bytes(b"ai-cover")
        return str(ai_cover)

    uploaded_paths: list[Path] = []

    def fake_upload_image(image_path, *, base_dir=None):
        uploaded_paths.append(Path(image_path))
        return {"media_id": "ai-cover-media-id"}

    captured_draft: dict = {}

    monkeypatch.setattr(publisher, "_generate_wechat_cover", fake_generate_wechat_cover)
    monkeypatch.setattr(publisher, "_upload_image", fake_upload_image)
    monkeypatch.setattr(publisher, "_create_draft", lambda **kwargs: captured_draft.update(kwargs) or "draft-id")

    result = publisher.save_to_draft("AI cover article", "<p>body</p>", base_dir=tmp_path)

    assert result.success
    assert uploaded_paths == [ai_cover]
    assert captured_draft["thumb_media_id"] == "ai-cover-media-id"


def test_save_to_draft_falls_back_when_explicit_cover_upload_fails(monkeypatch, tmp_path):
    article_dir = tmp_path / "articles" / "task-1"
    article_dir.mkdir(parents=True)
    publisher = wechat_publisher.WechatPublisher(
        app_id="wx1234567890abcdef",
        app_secret="0123456789abcdef0123456789abcdef",
        data_dir=str(tmp_path / "articles"),
    )

    monkeypatch.setattr(
        publisher,
        "_upload_images_in_html",
        lambda content, *, base_dir=None: (content, "", []),
    )
    ai_cover = article_dir / "wechat_ai_cover.png"

    def fake_generate_wechat_cover(**kwargs):
        ai_cover.write_bytes(b"ai-cover")
        return str(ai_cover)

    uploaded_paths: list[str] = []

    def fake_upload_image(image_path, *, base_dir=None):
        uploaded_paths.append(str(image_path))
        if image_path == "missing-cover.png":
            raise RuntimeError("cover missing")
        return {"media_id": "ai-cover-media-id"}

    captured_draft: dict = {}
    monkeypatch.setattr(publisher, "_generate_wechat_cover", fake_generate_wechat_cover)
    monkeypatch.setattr(publisher, "_upload_image", fake_upload_image)
    monkeypatch.setattr(publisher, "_create_draft", lambda **kwargs: captured_draft.update(kwargs) or "draft-id")

    result = publisher.save_to_draft(
        "Fallback cover",
        "<p>body</p>",
        cover_image="missing-cover.png",
        base_dir=article_dir,
    )

    assert result.success
    assert uploaded_paths == ["missing-cover.png", str(ai_cover)]
    assert captured_draft["thumb_media_id"] == "ai-cover-media-id"


def test_upload_image_rejects_local_path_outside_article_output(tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"not really an image")
    publisher = wechat_publisher.WechatPublisher(
        app_id="wx1234567890abcdef",
        app_secret="0123456789abcdef0123456789abcdef",
        data_dir=str(tmp_path / "articles"),
    )

    with pytest.raises(PermissionError, match="文章输出目录"):
        publisher._upload_image(str(outside))


def test_upload_image_rejects_private_remote_image_urls():
    with pytest.raises(PermissionError, match="内网|本机"):
        wechat_publisher._read_image_bytes("http://127.0.0.1/private.png")


def test_inline_markdown_sanitizes_link_href_attributes():
    safe = wechat_publisher._inline_markdown('[docs](https://example.com/?q=" onclick="alert")')
    dangerous = wechat_publisher._inline_markdown("[bad](javascript:alert(1))")

    assert 'href="https://example.com/?q=&quot; onclick=&quot;alert&quot;"' in safe
    assert "<a " not in dangerous
    assert "javascript:alert(1)" in dangerous


def test_wechat_api_rejects_draft_path_outside_article_output(monkeypatch, tmp_path):
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
            "article_output_dir": str(tmp_path / "articles"),
        },
    )
    monkeypatch.setattr(
        server_main._db,
        "create_wechat_publish_task",
        lambda **kwargs: pytest.fail("should reject before creating a task"),
    )

    server_main.MonitorHandler._handle_wechat_publish(
        handler,
        {
            "title": "unsafe",
            "content": "<p>body</p>",
            "draft_path": str(tmp_path / "outside" / "draft.md"),
        },
        "draft",
    )

    assert sent == [({"error": "无效的输出路径"}, 400)]


def test_create_draft_invalid_media_id_error_mentions_cover_material(monkeypatch):
    publisher = wechat_publisher.WechatPublisher(
        app_id="wx1234567890abcdef",
        app_secret="0123456789abcdef0123456789abcdef",
    )
    monkeypatch.setattr(publisher, "_get_access_token", lambda: "token")
    monkeypatch.setattr(
        publisher,
        "_api_post",
        lambda url, payload: {
            "errcode": 40007,
            "errmsg": "invalid media_id hint: [yTgqiA0254c6-2] rid: 69f06936",
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        publisher._create_draft(
            title="title",
            content="<p>body</p>",
            thumb_media_id="bad-media-id",
        )

    message = str(excinfo.value)
    assert "封面" in message
    assert "永久图片素材" in message
    assert "invalid media_id" in message
