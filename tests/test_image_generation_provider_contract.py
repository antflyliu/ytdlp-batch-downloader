"""Contract tests for the shared AI image generation provider layer."""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from scripts import image_generation


def test_image_generation_fallback_order_prefers_minimax_openai_gemini(monkeypatch, tmp_path):
    calls: list[str] = []

    class FailingProvider(image_generation.ImageProvider):
        name = "failing"

        def __init__(self, name: str):
            self.name = name

        def is_configured(self) -> bool:
            return True

        def generate(self, request: image_generation.ImageGenerationRequest) -> image_generation.ImageGenerationResult:
            calls.append(self.name)
            raise RuntimeError(f"{self.name} failed")

    class SuccessProvider(image_generation.ImageProvider):
        name = "gemini"

        def is_configured(self) -> bool:
            return True

        def generate(self, request: image_generation.ImageGenerationRequest) -> image_generation.ImageGenerationResult:
            calls.append(self.name)
            path = Path(request.output_path or tmp_path / "cover.png")
            path.write_bytes(b"image")
            return image_generation.ImageGenerationResult(provider=self.name, path=path, mime_type="image/png")

    monkeypatch.setattr(
        image_generation,
        "_build_provider",
        lambda name, cfg: SuccessProvider() if name == "gemini" else FailingProvider(name),
    )

    result = image_generation.generate_image_with_fallback(
        image_generation.ImageGenerationRequest(
            prompt="article cover",
            output_path=tmp_path / "cover.png",
        ),
        {
            "image_generation_fallback_order": "minimax,openai,gemini",
            "minimax_api_key": "minimax-key",
            "openai_api_key": "openai-key",
            "gemini_api_key": "gemini-key",
        },
    )

    assert calls == ["minimax", "openai", "gemini"]
    assert result.provider == "gemini"
    assert result.path.is_file()


def test_image_generation_primary_provider_is_tried_before_fallback_order(monkeypatch, tmp_path):
    calls: list[str] = []

    class Provider(image_generation.ImageProvider):
        def __init__(self, name: str):
            self.name = name

        def is_configured(self) -> bool:
            return True

        def generate(self, request: image_generation.ImageGenerationRequest) -> image_generation.ImageGenerationResult:
            calls.append(self.name)
            path = Path(request.output_path)
            path.write_bytes(b"image")
            return image_generation.ImageGenerationResult(provider=self.name, path=path)

    monkeypatch.setattr(image_generation, "_build_provider", lambda name, cfg: Provider(name))

    result = image_generation.generate_image_with_fallback(
        image_generation.ImageGenerationRequest(prompt="cover", output_path=tmp_path / "cover.png"),
        {
            "image_generation_provider": "openai",
            "image_generation_fallback_order": "minimax,openai,gemini,local",
        },
    )

    assert calls == ["openai"]
    assert result.provider == "openai"


def test_openai_image_provider_can_inherit_openai_llm_credentials_when_image_key_is_blank():
    provider = image_generation.OpenAIImageProvider(
        {
            "llm_provider": "openai",
            "llm_api_key": "llm-key",
            "llm_base_url": "https://api.openai.com/v1",
            "openai_api_key": "",
            "openai_base_url": "",
        }
    )

    assert provider.is_configured()
    assert provider._api_key() == "llm-key"
    assert provider._base_url() == "https://api.openai.com/v1"


def test_openai_image_provider_does_not_inherit_openai_compatible_llm_endpoint_key():
    provider = image_generation.OpenAIImageProvider(
        {
            "llm_provider": "openai",
            "llm_api_key": "nvidia-key",
            "llm_base_url": "https://integrate.api.nvidia.com/v1",
            "openai_api_key": "",
            "openai_base_url": "",
        }
    )

    assert not provider.is_configured()
    assert provider._api_key() == ""
    assert provider._base_url() == "https://api.openai.com/v1"


def test_gpt_image_model_rejects_custom_openai_compatible_base_url():
    provider = image_generation.OpenAIImageProvider(
        {
            "openai_api_key": "openai-key",
            "openai_base_url": "https://integrate.api.nvidia.com/v1",
            "openai_image_model": "gpt-image-2",
        }
    )

    with pytest.raises(ValueError, match="OpenAI 官方图片接口"):
        provider._base_url()


def test_openai_image_provider_uses_dalle_compatible_payload(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_post_json(url, payload, headers, timeout=180):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return {"data": [{"url": "https://example.test/cover.png"}]}

    def fake_download_url(url, path, headers=None):
        assert url == "https://example.test/cover.png"
        path.write_bytes(b"\xff\xd8\xffimage")
        return path

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    monkeypatch.setattr(image_generation, "_download_url", fake_download_url)

    result = image_generation.OpenAIImageProvider(
        {
            "openai_api_key": "openai-key",
            "openai_base_url": "https://api.openai.com/v1",
            "openai_image_model": "dall-e-3",
        }
    ).generate(
        image_generation.ImageGenerationRequest(
            prompt="cover",
            output_path=tmp_path / "cover.png",
            aspect_ratio="16:9",
            output_format="png",
        )
    )

    assert result.path.read_bytes() == b"\xff\xd8\xffimage"
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "dall-e-3"
    assert payload["size"] == "1792x1024"
    assert payload["response_format"] == "url"
    assert "output_format" not in payload


def test_minimax_image_provider_accepts_image_url_arrays(monkeypatch, tmp_path):
    def fake_post_json(url, payload, headers, timeout=180):
        assert url == "https://api.minimaxi.com/v1/image_generation"
        assert payload["response_format"] == "base64"
        assert headers["Authorization"] == "Bearer minimax-key"
        return {
            "base_resp": {"status_code": 0},
            "data": {"image_urls": ["https://example.test/cover.png"]},
        }

    def fake_download_url(url, path, headers=None):
        assert url == "https://example.test/cover.png"
        path.write_bytes(b"\xff\xd8\xffimage")
        return path

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    monkeypatch.setattr(image_generation, "_download_url", fake_download_url)

    result = image_generation.MiniMaxImageProvider({"minimax_api_key": "minimax-key"}).generate(
        image_generation.ImageGenerationRequest(prompt="cover", output_path=tmp_path / "cover.png")
    )

    assert result.provider == "minimax"
    assert result.path.read_bytes() == b"\xff\xd8\xffimage"


def test_minimax_image_provider_accepts_full_endpoint_url(monkeypatch, tmp_path):
    def fake_post_json(url, payload, headers, timeout=180):
        assert url == "https://api.minimaxi.com/v1/image_generation"
        assert payload["n"] == 1
        assert payload["response_format"] == "base64"
        assert headers["Authorization"] == "Bearer minimax-key"
        return {
            "base_resp": {"status_code": 0},
            "data": {"image_urls": ["https://example.test/cover.png"]},
        }

    def fake_download_url(url, path, headers=None):
        assert url == "https://example.test/cover.png"
        path.write_bytes(b"image")
        return path

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)
    monkeypatch.setattr(image_generation, "_download_url", fake_download_url)

    result = image_generation.MiniMaxImageProvider(
        {
            "minimax_api_key": "minimax-key",
            "minimax_base_url": "https://api.minimaxi.com/v1/image_generation",
        }
    ).generate(image_generation.ImageGenerationRequest(prompt="cover", output_path=tmp_path / "cover.png"))

    assert result.provider == "minimax"
    assert result.path.read_bytes() == b"image"


def test_minimax_image_provider_default_base_url_uses_current_official_host(monkeypatch, tmp_path):
    def fake_post_json(url, payload, headers, timeout=180):
        assert url == "https://api.minimaxi.com/v1/image_generation"
        return {
            "base_resp": {"status_code": 0},
            "data": {"image_base64s": [base64.b64encode(b"image").decode("ascii")]},
        }

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)

    result = image_generation.MiniMaxImageProvider(
        {"minimax_api_key": "minimax-key"}
    ).generate(image_generation.ImageGenerationRequest(prompt="cover", output_path=tmp_path / "cover.png"))

    assert result.provider == "minimax"
    assert result.path.read_bytes() == b"image"


def test_minimax_image_provider_preserves_actual_jpeg_suffix(monkeypatch, tmp_path):
    encoded = base64.b64encode(b"\xff\xd8\xffjpeg").decode("ascii")

    def fake_post_json(url, payload, headers, timeout=180):
        assert url == "https://api.minimaxi.com/v1/image_generation"
        return {
            "base_resp": {"status_code": 0},
            "data": {"image_base64s": [encoded]},
        }

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)

    result = image_generation.MiniMaxImageProvider(
        {
            "minimax_api_key": "minimax-key",
            "minimax_base_url": "https://api.minimaxi.com/v1/image_generation",
        }
    ).generate(image_generation.ImageGenerationRequest(prompt="cover", output_path=tmp_path / "cover.png"))

    assert result.path.suffix == ".jpg"
    assert result.mime_type == "image/jpeg"
    assert result.path.read_bytes() == b"\xff\xd8\xffjpeg"


def test_minimax_image_provider_rejects_metadata_failed_count(monkeypatch, tmp_path):
    def fake_post_json(url, payload, headers, timeout=180):
        return {
            "base_resp": {"status_code": 0},
            "metadata": {"failed_count": "1", "success_count": "0"},
            "data": {"image_base64s": []},
        }

    monkeypatch.setattr(image_generation, "_post_json", fake_post_json)

    with pytest.raises(RuntimeError, match="部分失败"):
        image_generation.MiniMaxImageProvider(
            {
                "minimax_api_key": "minimax-key",
                "minimax_base_url": "https://api.minimaxi.com/v1/image_generation",
            }
        ).generate(image_generation.ImageGenerationRequest(prompt="cover", output_path=tmp_path / "cover.png"))


def test_image_generation_skips_unknown_provider_and_uses_local_fallback(tmp_path):
    result = image_generation.generate_image_with_fallback(
        image_generation.ImageGenerationRequest(
            prompt="fallback cover",
            output_path=tmp_path / "cover.png",
        ),
        {
            "image_generation_provider": "missing-provider",
            "image_generation_fallback_order": "minimax",
        },
    )

    assert result.provider == "local"
    assert result.path.is_file()


def test_image_generation_uses_local_placeholder_when_remote_providers_are_unconfigured(tmp_path):
    result = image_generation.generate_image_with_fallback(
        image_generation.ImageGenerationRequest(
            prompt="fallback cover",
            output_path=tmp_path / "cover.png",
            aspect_ratio="16:9",
        ),
        {
            "image_generation_fallback_order": "minimax,openai,gemini,local",
        },
    )

    assert result.provider == "local"
    assert result.path.is_file()
    assert result.path.suffix == ".png"
