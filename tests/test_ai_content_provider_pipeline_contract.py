"""Regression tests for AI content provider adapters and persisted task options."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db  # noqa: E402
from scripts import article_generator  # noqa: E402
from scripts.video_gen_pipeline import VideoGenerationPipeline, _generated_file_url  # noqa: E402


@pytest.fixture(autouse=True)
def _default_local_whisper_runtime_is_cpu(monkeypatch):
    monkeypatch.setattr(article_generator, "_local_whisper_cuda_available", lambda: False)
    monkeypatch.setattr(article_generator, "_local_whisper_gpu_memory_mb", lambda: (None, None))
    monkeypatch.setattr(
        article_generator,
        "_local_whisper_supported_compute_types",
        lambda device: {"int8", "int8_float32", "float32"} if device == "cpu" else set(),
    )


def test_video_gen_task_persists_provider_workflow_options(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_db, "_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(monitor_db, "_DB_PATH", str(tmp_path / "data" / "monitor.db"))
    monkeypatch.setattr(monitor_db, "_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(monitor_db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"))

    monitor_db.init_db()
    task_id = monitor_db.create_video_gen_task(
        mode="generate",
        topic="contract topic",
        script_text=None,
        template_key="1080x1920/image_default.html",
        scene_count=3,
        prompt_prefix="warm editorial",
        image_workflow="runninghub:app-123",
        tts_workflow="edge-tts",
        bgm_volume=0.4,
    )

    task = monitor_db.get_video_gen_task(task_id)

    assert task is not None
    assert task["prompt_prefix"] == "warm editorial"
    assert task["image_workflow"] == "runninghub:app-123"
    assert task["tts_workflow"] == "edge-tts"
    assert task["bgm_volume"] == 0.4


def test_comfyui_failure_does_not_fall_back_without_runninghub(tmp_path):
    pipeline = VideoGenerationPipeline("video_gen_contract", cfg={"comfyui_url": "http://127.0.0.1:8188"})

    with pytest.raises(RuntimeError, match="未配置 RunningHub"):
        pipeline._generate_scene_images(
            [{"image_prompt": "contract image"}],
            tmp_path,
            {"image_workflow": ""},
        )


def test_comfyui_failure_falls_back_to_runninghub_when_configured(tmp_path, monkeypatch):
    pipeline = VideoGenerationPipeline(
        "video_gen_contract",
        cfg={
            "comfyui_url": "http://127.0.0.1:8188",
            "runninghub_url": "https://example.invalid",
            "runninghub_api_key": "secret",
        },
    )

    def fail_comfy(*_args, **_kwargs):
        raise RuntimeError("comfy down")

    def fake_runninghub(_scene, output_dir, _workflow_ref, index):
        path = output_dir / f"scene_{index + 1:02d}.png"
        path.write_bytes(b"fake image")
        return str(path)

    monkeypatch.setattr(pipeline, "_generate_comfyui_image", fail_comfy)
    monkeypatch.setattr(pipeline, "_generate_runninghub_image", fake_runninghub)

    paths, provider = pipeline._generate_scene_images(
        [{"image_prompt": "contract image"}],
        tmp_path,
        {"image_workflow": "runninghub:app-123"},
    )

    assert provider == "runninghub"
    assert Path(paths[0]).read_bytes() == b"fake image"


def test_configured_local_tts_failure_is_not_silently_replaced(tmp_path, monkeypatch):
    pipeline = VideoGenerationPipeline("video_gen_contract", cfg={"local_tts_url": "http://tts.invalid"})

    class FakeResponse:
        headers = {"Content-Type": "text/plain"}
        content = b""

        def raise_for_status(self):
            raise RuntimeError("tts down")

    monkeypatch.setattr("scripts.video_gen_pipeline.requests.post", lambda *_a, **_k: FakeResponse())

    with pytest.raises(RuntimeError, match="tts down"):
        pipeline._synthesize_narration(
            [{"narration": "hello world"}],
            tmp_path,
            {"tts_workflow": "local"},
        )


def test_generated_file_urls_are_query_encoded_for_windows_paths():
    url = _generated_file_url(Path("D:/output/含 空格/final.mp4"))

    assert url.startswith("/api/video-generate/file?path=")
    assert " " not in url
    assert "含 空格" not in url


def test_article_llm_failure_marks_pipeline_stage_as_error(monkeypatch):
    class FailingClient:
        def call_with_retry(self, *_args, **_kwargs):
            raise RuntimeError("llm down")

    monkeypatch.setattr(article_generator, "create_llm_client", lambda **_kwargs: FailingClient())

    with pytest.raises(RuntimeError, match="LLM 处理失败"):
        article_generator._llm_or_fallback(
            {"llm_base_url": "http://llm.invalid"},
            f"prompt {article_generator.PROMPT_INPUT_PLACEHOLDER}",
            "source text",
            model_key="article_llm_optimize_model",
            fallback_prefix="fallback",
        )


def test_article_llm_empty_response_reports_selected_backend(monkeypatch):
    class EmptyClient:
        def call_with_retry(self, *_args, **kwargs):
            assert kwargs["raise_last_error"] is True
            return " \n "

    monkeypatch.setattr(article_generator, "create_llm_client", lambda **_kwargs: EmptyClient())

    with pytest.raises(RuntimeError) as exc_info:
        article_generator._llm_or_fallback(
            {
                "llm_provider": "openai",
                "llm_base_url": "http://llm.invalid/v1",
                "article_llm_optimize_model": "gpt-test",
            },
            f"prompt {article_generator.PROMPT_INPUT_PLACEHOLDER}",
            "source text",
            model_key="article_llm_optimize_model",
            fallback_prefix="fallback",
        )

    message = str(exc_info.value)
    assert "LLM 处理失败: 服务未返回内容" in message
    assert "provider=openai" in message
    assert "model=gpt-test" in message
    assert "base_url=http://llm.invalid/v1" in message


def test_article_proxy_auto_uses_source_video_account(monkeypatch):
    captured_accounts: list[dict] = []

    def fake_resolve(account, *_args, **_kwargs):
        captured_accounts.append(dict(account))
        return SimpleNamespace(
            resolved_mode="account_static",
            proxy="http://account-proxy.local:1080",
            proxy_pool=None,
            provider_name=None,
            provider_tier=None,
            resolved_proxy_source="account_static",
            reason="account proxy",
            warnings=[],
            masked_proxy_endpoint="http://account-proxy.local:1080",
            session_mode=None,
        )

    monkeypatch.setattr(article_generator.proxy_router, "resolve_proxy_download", fake_resolve)
    monkeypatch.setattr(
        article_generator.db,
        "list_accounts",
        lambda *_args, **_kwargs: [
            {"id": 1, "proxy_enabled": 1, "proxy_pool_id": 1, "download_proxy_mode": "account_only"}
        ],
    )

    plan = article_generator._resolve_article_subtitle_proxy_plan(
        {"article_subtitle_proxy_mode": "auto"},
        account={"id": 9, "proxy_enabled": 1, "proxy_pool_id": 7, "download_proxy_mode": "auto"},
    )

    assert captured_accounts[0]["id"] == 9
    assert plan.proxies[0] == "http://account-proxy.local:1080"


def test_article_proxy_plan_keeps_dynamic_proxy_pool(monkeypatch):
    def fake_resolve(_account, *_args, **_kwargs):
        return SimpleNamespace(
            resolved_mode="paid_system",
            proxy=None,
            proxy_pool=["http://pool-a.local:8080", "http://pool-b.local:8080"],
            provider_name="contract-provider",
            provider_tier="paid",
            resolved_proxy_source="system_paid",
            reason="dynamic pool",
            warnings=[],
            masked_proxy_endpoint="http://pool-a.local:8080",
            session_mode="rotating",
        )

    monkeypatch.setattr(article_generator.proxy_router, "resolve_proxy_download", fake_resolve)

    plan = article_generator._resolve_article_subtitle_proxy_plan(
        {"article_subtitle_proxy_mode": "system_only"},
    )

    assert plan.proxies == ["http://pool-a.local:8080", "http://pool-b.local:8080"]


def test_article_subtitle_429_falls_back_to_whisper_with_source_audio(tmp_path, monkeypatch):
    state = {
        "task": {
            "task_id": "article_contract",
            "monitor_video_id": None,
            "video_id": "contract-video",
            "video_url": "https://www.youtube.com/watch?v=contract-video",
            "video_title": "Contract Video",
            "target_lang": "zh-Hans",
            "auto_translate": True,
            "status": "pending",
            "stages": {},
        }
    }
    audio_path = tmp_path / "source.webm"
    audio_path.write_bytes(b"fake audio")

    def update_task(_task_id, **kwargs):
        task = state["task"]
        for key, value in kwargs.items():
            if key == "stages":
                task["stages"] = value
            elif value is not monitor_db._UNSET:
                task[key] = value

    monkeypatch.setattr(article_generator.db, "get_article_task", lambda _task_id: state["task"])
    monkeypatch.setattr(article_generator.db, "update_article_task", update_task)
    monkeypatch.setattr(article_generator.db, "now_iso", lambda: "2026-04-28T12:00:00+08:00")
    monkeypatch.setattr(
        article_generator,
        "_download_subtitles",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            article_generator.SubtitleDownloadError("字幕下载网络错误: HTTP Error 429: Too Many Requests")
        ),
    )
    monkeypatch.setattr(article_generator, "_download_audio_for_whisper", lambda *_args, **_kwargs: str(audio_path))
    monkeypatch.setattr(article_generator, "_local_whisper", lambda *_args, **_kwargs: "transcript from whisper")
    monkeypatch.setattr(article_generator, "_remote_whisper", lambda *_args, **_kwargs: None)

    result = article_generator.ArticleGenerationPipeline(
        "article_contract",
        cfg={
            "article_output_dir": str(tmp_path / "articles"),
            "whisper_provider": "local",
            "llm_base_url": "",
        },
    ).run()

    assert result["status"] == "done"
    assert Path(result["draft_path"]).is_file()
    draft = Path(result["draft_path"]).read_text(encoding="utf-8")
    final_body = Path(result["result"]["article_final_body_path"]).read_text(encoding="utf-8")
    assert "transcript from whisper" in draft
    assert "<source_type>" not in draft
    assert "<style_profile>" not in final_body
    assert "<summary_strategy>" not in final_body
    assert "已切换 Whisper" in result["stages"]["subtitles"]["message"]


def test_article_remote_subtitle_success_skips_whisper_and_audio_download(tmp_path, monkeypatch):
    state = {
        "task": {
            "task_id": "article_contract",
            "monitor_video_id": None,
            "video_id": "contract-video",
            "video_url": "https://www.youtube.com/watch?v=contract-video",
            "video_title": "Contract Video",
            "target_lang": "zh-Hans",
            "auto_translate": True,
            "status": "pending",
            "stages": {},
        }
    }

    def update_task(_task_id, **kwargs):
        task = state["task"]
        for key, value in kwargs.items():
            if key == "stages":
                task["stages"] = value
            elif value is not monitor_db._UNSET:
                task[key] = value

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Whisper/audio branch must not run when subtitles are available")

    monkeypatch.setattr(article_generator.db, "get_article_task", lambda _task_id: state["task"])
    monkeypatch.setattr(article_generator.db, "update_article_task", update_task)
    monkeypatch.setattr(article_generator.db, "now_iso", lambda: "2026-05-01T12:00:00+08:00")
    monkeypatch.setattr(
        article_generator,
        "_download_subtitles",
        lambda *_args, **_kwargs: ("subtitle transcript", {"language": "en", "proxy": "http://127.0.0.1:10808"}),
    )
    monkeypatch.setattr(article_generator, "_download_audio_for_whisper", fail_if_called)
    monkeypatch.setattr(article_generator, "_local_whisper", fail_if_called)
    monkeypatch.setattr(article_generator, "_remote_whisper", fail_if_called)

    result = article_generator.ArticleGenerationPipeline(
        "article_contract",
        cfg={
            "article_output_dir": str(tmp_path / "articles"),
            "whisper_provider": "local",
            "llm_base_url": "",
        },
    ).run()

    assert result["status"] == "done"
    assert result["result"]["transcript_source"] == "remote_subtitle"
    assert "whisper" not in result["stages"]
    assert "字幕下载完成" in result["stages"]["subtitles"]["message"]


def test_article_wechat_source_never_enters_video_or_whisper_branches(tmp_path, monkeypatch):
    state = {
        "task": {
            "task_id": "article_contract",
            "source_type": "wechat_article",
            "article_text": "公众号原文第一段。\n\n公众号原文第二段。",
            "source_title": "公众号原文",
            "target_lang": "zh-Hans",
            "auto_translate": True,
            "status": "pending",
            "stages": {},
        }
    }

    def update_task(_task_id, **kwargs):
        task = state["task"]
        for key, value in kwargs.items():
            if key == "stages":
                task["stages"] = value
            elif value is not monitor_db._UNSET:
                task[key] = value

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("video subtitle/Whisper branch must not run for wechat_article source")

    monkeypatch.setattr(article_generator.db, "get_article_task", lambda _task_id: state["task"])
    monkeypatch.setattr(article_generator.db, "update_article_task", update_task)
    monkeypatch.setattr(article_generator.db, "now_iso", lambda: "2026-05-01T12:00:00+08:00")
    monkeypatch.setattr(article_generator, "_download_subtitles", fail_if_called)
    monkeypatch.setattr(article_generator, "_download_audio_for_whisper", fail_if_called)
    monkeypatch.setattr(article_generator, "_local_whisper", fail_if_called)
    monkeypatch.setattr(article_generator, "_remote_whisper", fail_if_called)

    result = article_generator.ArticleGenerationPipeline(
        "article_contract",
        cfg={
            "article_output_dir": str(tmp_path / "articles"),
            "whisper_provider": "local",
            "llm_base_url": "",
        },
    ).run()

    assert result["status"] == "done"
    assert result["result"]["transcript_source"] == "wechat_article"
    assert "whisper" not in result["stages"]
    assert result["stages"]["subtitles"]["message"] == "已读取公众号文章正文"


def test_llm_or_fallback_strips_thinking_blocks(monkeypatch):
    class FakeClient:
        def call_with_retry(self, *_args, **_kwargs):
            return "<think>private reasoning</think>\n\n## 正文\n\n可发布内容"

    monkeypatch.setattr(article_generator, "create_llm_client", lambda **_kwargs: FakeClient())

    result = article_generator._llm_or_fallback(
        {"llm_base_url": "http://llm.invalid/v1"},
        "prompt",
        "input",
        model_key="article_llm_summary_model",
        fallback_prefix="fallback",
    )

    assert result == "## 正文\n\n可发布内容"


def test_illustration_plan_empty_llm_response_returns_no_plans(monkeypatch):
    from scripts import article_image_generator
    import scripts.llm_client as llm_client_mod

    class FakeClient:
        def call_with_retry(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(llm_client_mod, "create_llm_client", lambda **_kwargs: FakeClient())

    plans = article_image_generator._analyze_illustration_plan("正文" * 200, "标题", {})

    assert plans == []


def test_article_minimax_generation_accepts_full_endpoint_and_url_array(monkeypatch):
    from scripts import article_image_generator

    class FakeResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    calls: list[tuple[str, dict | None]] = []

    def fake_urlopen(req, timeout=None):
        if hasattr(req, "full_url"):
            url = req.full_url
            body = getattr(req, "data", None)
            if not body:
                calls.append((url, None))
                assert url == "https://example.test/inline.png"
                return FakeResponse(b"inline-image")
            payload = json.loads(body.decode("utf-8")) if body else None
            calls.append((url, payload))
            assert url == "https://api.minimaxi.com/v1/image_generation"
            assert payload["n"] == 1
            assert payload["response_format"] == "base64"
            assert payload["aspect_ratio"] == "3:4"
            return FakeResponse(
                b'{"base_resp":{"status_code":0},"data":{"image_urls":["https://example.test/inline.png"]}}'
            )
        raise AssertionError(f"unexpected request: {req!r}")

    monkeypatch.setattr(article_image_generator.urllib.request, "urlopen", fake_urlopen)

    data = article_image_generator._generate_with_minimax(
        "inline prompt",
        {
            "minimax_api_key": "minimax-key",
            "minimax_base_url": "https://api.minimaxi.com/v1/image_generation",
            "minimax_image_model": "image-01",
        },
    )

    assert data == b"inline-image"
    assert calls[0][0] == "https://api.minimaxi.com/v1/image_generation"


def test_article_minimax_generation_default_base_url_uses_current_official_host(monkeypatch):
    from scripts import article_image_generator

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            encoded = base64.b64encode(b"inline-image").decode("ascii")
            return f'{{"base_resp":{{"status_code":0}},"data":{{"image_base64s":["{encoded}"]}}}}'.encode("utf-8")

    def fake_urlopen(req, timeout=None):
        assert req.full_url == "https://api.minimaxi.com/v1/image_generation"
        return FakeResponse()

    monkeypatch.setattr(article_image_generator.urllib.request, "urlopen", fake_urlopen)

    assert (
        article_image_generator._generate_with_minimax(
            "inline prompt",
            {"minimax_api_key": "minimax-key"},
        )
        == b"inline-image"
    )


def test_article_minimax_generation_rejects_metadata_failed_count(monkeypatch):
    from scripts import article_image_generator

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return (
                b'{"base_resp":{"status_code":0},'
                b'"metadata":{"failed_count":"1","success_count":"0"},'
                b'"data":{"image_base64s":[]}}'
            )

    monkeypatch.setattr(article_image_generator.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    assert (
        article_image_generator._generate_with_minimax(
            "inline prompt",
            {
                "minimax_api_key": "minimax-key",
                "minimax_base_url": "https://api.minimaxi.com/v1/image_generation",
            },
        )
        is None
    )


def test_article_openai_generation_accepts_gpt_image_base64(monkeypatch):
    from scripts import article_image_generator

    class FakeResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(req, timeout=None):
        assert req.full_url == "https://api.openai.com/v1/images/generations"
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == "gpt-image-2"
        assert payload["output_format"] == "png"
        assert payload["quality"] == "medium"
        assert "response_format" not in payload
        encoded = base64.b64encode(b"openai-image").decode("ascii")
        return FakeResponse(json.dumps({"data": [{"b64_json": encoded}]}).encode("utf-8"))

    monkeypatch.setattr(article_image_generator.urllib.request, "urlopen", fake_urlopen)

    data = article_image_generator._generate_with_openai(
        "inline prompt",
        {
            "openai_api_key": "openai-key",
            "openai_base_url": "https://api.openai.com/v1",
            "openai_image_model": "gpt-image-2",
            "openai_image_quality": "medium",
        },
    )

    assert data == b"openai-image"


def test_article_openai_generation_can_inherit_official_llm_credentials(monkeypatch):
    from scripts import article_image_generator

    class FakeResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(req, timeout=None):
        assert req.full_url == "https://api.openai.com/v1/images/generations"
        assert dict(req.header_items())["Authorization"] == "Bearer llm-openai-key"
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["model"] == "gpt-image-2"
        encoded = base64.b64encode(b"inherited-openai-image").decode("ascii")
        return FakeResponse(json.dumps({"data": [{"b64_json": encoded}]}).encode("utf-8"))

    monkeypatch.setattr(article_image_generator.urllib.request, "urlopen", fake_urlopen)

    assert article_image_generator._generate_with_openai(
        "inline prompt",
        {
            "llm_provider": "openai",
            "llm_api_key": "llm-openai-key",
            "llm_base_url": "https://api.openai.com/v1",
            "openai_api_key": "",
            "openai_base_url": "",
            "openai_image_model": "gpt-image-2",
        },
    ) == b"inherited-openai-image"


def test_article_openai_generation_rejects_gpt_image_compatible_endpoint(monkeypatch):
    from scripts import article_image_generator

    monkeypatch.setattr(
        article_image_generator.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("invalid gpt-image endpoint should not be called"),
    )

    assert (
        article_image_generator._generate_with_openai(
            "inline prompt",
            {
                "openai_api_key": "openai-key",
                "openai_base_url": "https://integrate.api.nvidia.com/v1",
                "openai_image_model": "gpt-image-2",
            },
        )
        is None
    )


def test_article_inline_images_try_selected_provider_before_fallback(monkeypatch):
    from scripts import article_image_generator

    calls: list[str] = []

    def fake_openai(_prompt, _cfg):
        calls.append("openai")
        return b"\x89PNG\r\n\x1a\nopenai"

    def fake_minimax(_prompt, _cfg):
        calls.append("minimax")
        return b"\x89PNG\r\n\x1a\nminimax"

    monkeypatch.setattr(article_image_generator, "_generate_with_openai", fake_openai)
    monkeypatch.setattr(article_image_generator, "_generate_with_minimax", fake_minimax)

    data = article_image_generator._generate_image(
        "inline prompt",
        {
            "image_generation_provider": "openai",
            "image_generation_fallback_order": "minimax,openai,gemini",
            "openai_api_key": "openai-key",
        },
    )

    assert data == b"\x89PNG\r\n\x1a\nopenai"
    assert calls == ["openai"]


def test_article_illustrations_use_actual_image_suffix(monkeypatch, tmp_path):
    from scripts import article_image_generator

    monkeypatch.setattr(
        article_image_generator,
        "_analyze_illustration_plan",
        lambda *_args, **_kwargs: [
            article_image_generator.ImagePlan(position=2, prompt="inline", caption="配图")
        ],
    )
    monkeypatch.setattr(
        article_image_generator,
        "_generate_image",
        lambda *_args, **_kwargs: b"\xff\xd8\xffjpeg",
    )

    body, image_paths = article_image_generator.generate_illustrations(
        "正文" * 200,
        "标题",
        tmp_path,
        {},
    )

    assert image_paths == ["images/img_001.jpg"]
    assert "images/img_001.jpg" in body
    assert (tmp_path / "images" / "img_001.jpg").read_bytes() == b"\xff\xd8\xffjpeg"


def test_article_illustrations_fallback_plan_runs_provider_when_llm_plan_empty(monkeypatch, tmp_path):
    from scripts import article_image_generator

    monkeypatch.setattr(article_image_generator, "_analyze_illustration_plan", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(article_image_generator, "_generate_image", lambda *_args, **_kwargs: b"\x89PNG\r\n\x1a\npng")

    body, image_paths = article_image_generator.generate_illustrations(
        "## 第一节\n\n正文" * 180,
        "标题",
        tmp_path,
        {"article_prefer_video_keyframes": False},
    )

    assert image_paths
    assert "![第一节]" in body
    assert (tmp_path / image_paths[0]).is_file()


def test_article_illustration_insertions_snap_to_paragraph_boundaries(monkeypatch, tmp_path):
    from scripts import article_image_generator

    monkeypatch.setattr(
        article_image_generator,
        "_analyze_illustration_plan",
        lambda *_args, **_kwargs: [
            article_image_generator.ImagePlan(position=6, prompt="inline", caption="配图")
        ],
    )
    monkeypatch.setattr(article_image_generator, "_generate_image", lambda *_args, **_kwargs: b"\x89PNG\r\n\x1a\npng")

    source_body = "第一段文字不能被图片截断。" + ("补充内容" * 80) + "\n\n第二段继续。"

    body, image_paths = article_image_generator.generate_illustrations(
        source_body,
        "标题",
        tmp_path,
        {"article_prefer_video_keyframes": False},
    )

    assert image_paths == ["images/img_001.png"]
    assert "补充内容\n\n![配图](images/img_001.png)" in body
    assert "![配图](images/img_001.png)\n\n第二段继续。" in body


def test_article_video_keyframes_are_inserted_before_ai_generation(monkeypatch, tmp_path):
    from scripts import article_image_generator

    monkeypatch.setattr(
        article_image_generator,
        "_extract_video_keyframes",
        lambda *_args, **_kwargs: [(0, "关键帧", "images/keyframes/keyframe_001.jpg")],
    )
    monkeypatch.setattr(
        article_image_generator,
        "_analyze_illustration_plan",
        lambda *_args, **_kwargs: pytest.fail("AI drawing plan should not run when keyframes are available"),
    )

    body, image_paths = article_image_generator.generate_illustrations(
        "正文" * 200,
        "标题",
        tmp_path,
        {},
        source_type="video",
        video_path=tmp_path / "source.mp4",
    )

    assert image_paths == ["images/keyframes/keyframe_001.jpg"]
    assert body.startswith("![关键帧](images/keyframes/keyframe_001.jpg)")


def test_article_pipeline_resolves_relative_output_dir_from_project_root(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    cwd = tmp_path / "other-cwd"
    cwd.mkdir()
    state = {
        "task": {
            "task_id": "article_contract",
            "monitor_video_id": None,
            "video_id": "contract-video",
            "video_url": "https://www.youtube.com/watch?v=contract-video",
            "video_title": "Contract Video",
            "target_lang": "zh-Hans",
            "auto_translate": True,
            "status": "pending",
            "stages": {},
        }
    }
    audio_path = tmp_path / "source.webm"
    audio_path.write_bytes(b"fake audio")

    def update_task(_task_id, **kwargs):
        task = state["task"]
        for key, value in kwargs.items():
            if key == "stages":
                task["stages"] = value
            elif value is not monitor_db._UNSET:
                task[key] = value

    monkeypatch.chdir(cwd)
    monkeypatch.setattr(article_generator, "_PROJECT_ROOT", project_root)
    monkeypatch.setattr(article_generator.db, "get_article_task", lambda _task_id: state["task"])
    monkeypatch.setattr(article_generator.db, "update_article_task", update_task)
    monkeypatch.setattr(article_generator.db, "now_iso", lambda: "2026-04-30T12:00:00+08:00")
    monkeypatch.setattr(
        article_generator,
        "_download_subtitles",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            article_generator.SubtitleDownloadError("This video has no subtitles")
        ),
    )
    monkeypatch.setattr(article_generator, "_download_audio_for_whisper", lambda *_args, **_kwargs: str(audio_path))
    monkeypatch.setattr(article_generator, "_local_whisper", lambda *_args, **_kwargs: "project-root transcript")
    monkeypatch.setattr(article_generator, "_remote_whisper", lambda *_args, **_kwargs: None)

    result = article_generator.ArticleGenerationPipeline(
        "article_contract",
        cfg={
            "article_output_dir": "output/articles",
            "whisper_provider": "local",
            "llm_base_url": "",
        },
    ).run()

    expected_dir = project_root / "output" / "articles" / "article_contract"
    assert Path(result["output_dir"]) == expected_dir.resolve()
    assert Path(result["draft_path"]) == (expected_dir / "draft.md").resolve()
    assert Path(result["draft_path"]).is_file()
    assert not (cwd / "output" / "articles" / "article_contract").exists()


def test_article_local_whisper_failure_keeps_compute_error_in_stage(tmp_path, monkeypatch):
    state = {
        "task": {
            "task_id": "article_contract",
            "monitor_video_id": None,
            "video_id": "contract-video",
            "video_url": "https://www.youtube.com/watch?v=contract-video",
            "video_title": "Contract Video",
            "target_lang": "zh-Hans",
            "auto_translate": True,
            "status": "pending",
            "stages": {},
        }
    }
    audio_path = tmp_path / "source.webm"
    audio_path.write_bytes(b"fake audio")

    def update_task(_task_id, **kwargs):
        task = state["task"]
        for key, value in kwargs.items():
            if key == "stages":
                task["stages"] = value
            elif value is not monitor_db._UNSET:
                task[key] = value

    def fail_local_whisper(*_args, **kwargs):
        progress = kwargs.get("progress")
        if progress:
            progress("本地 Whisper 转写失败，已尝试 compute_type=float16, float32；最后错误：float32: backend down")
        return None

    monkeypatch.setattr(article_generator.db, "get_article_task", lambda _task_id: state["task"])
    monkeypatch.setattr(article_generator.db, "update_article_task", update_task)
    monkeypatch.setattr(article_generator.db, "now_iso", lambda: "2026-04-30T12:00:00+08:00")
    monkeypatch.setattr(article_generator, "_download_subtitles", lambda *_args, **_kwargs: ("", {}))
    monkeypatch.setattr(article_generator, "_download_audio_for_whisper", lambda *_args, **_kwargs: str(audio_path))
    monkeypatch.setattr(article_generator, "_local_whisper", fail_local_whisper)

    result = article_generator.ArticleGenerationPipeline(
        "article_contract",
        cfg={
            "article_output_dir": str(tmp_path / "articles"),
            "whisper_provider": "local",
            "llm_base_url": "",
        },
    ).run()

    assert result["status"] == "error"
    assert result["stages"]["whisper"]["status"] == "error"
    assert "compute_type=float16, float32" in result["stages"]["whisper"]["message"]
    assert "backend down" in result["stages"]["whisper"]["message"]


def test_article_auto_wechat_publish_runs_before_terminal_done(tmp_path, monkeypatch):
    state = {
        "task": {
            "task_id": "article_contract",
            "source_type": "wechat_article",
            "article_text": "这是一篇用于生成的公众号原文。",
            "source_title": "公众号原文",
            "target_lang": "zh-Hans",
            "auto_translate": False,
            "status": "pending",
            "stages": {},
        }
    }
    observed: dict[str, str] = {}

    def update_task(_task_id, **kwargs):
        task = state["task"]
        for key, value in kwargs.items():
            if key == "stages":
                task["stages"] = value
            elif value is not monitor_db._UNSET:
                task[key] = value

    import monitor.wechat_publisher as wechat_publisher

    class FakePublisher:
        def __init__(self, **_kwargs):
            pass

        def save_to_draft(self, **_kwargs):
            observed["status_during_publish"] = state["task"]["status"]
            observed["stage_during_publish"] = state["task"].get("current_stage", "")
            return SimpleNamespace(success=True, wx_article_id="media-1", wx_url=None)

    monkeypatch.setattr(article_generator.db, "get_article_task", lambda _task_id: state["task"])
    monkeypatch.setattr(article_generator.db, "update_article_task", update_task)
    monkeypatch.setattr(article_generator.db, "now_iso", lambda: "2026-04-30T12:00:00+08:00")
    monkeypatch.setattr(wechat_publisher, "WechatPublisher", FakePublisher)
    def fake_render(path, **_kwargs):
        observed["render_path"] = Path(path).name
        return SimpleNamespace(
            title="公众号原文",
            content="<p>正文</p>",
            author=None,
            digest="摘要",
        )

    monkeypatch.setattr(wechat_publisher, "render_md_to_html_for_wechat", fake_render)
    monkeypatch.setattr(wechat_publisher, "validate_wechat_article_payload", lambda **_kwargs: [])

    result = article_generator.ArticleGenerationPipeline(
        "article_contract",
        cfg={
            "article_output_dir": str(tmp_path / "articles"),
            "llm_base_url": "",
            "wechat_app_id": "wx123",
            "wechat_app_secret": "secret",
        },
    ).run()

    assert observed == {
        "render_path": "wechat_publish.md",
        "status_during_publish": "running",
        "stage_during_publish": "wechat",
    }
    assert result["status"] == "done"
    assert result["current_stage"] == "done"
    assert result["stages"]["wechat"]["status"] == "done"
    assert result["result"]["wx_article_id"] == "media-1"
    assert result["result"]["article_publish_markdown_path"].endswith("wechat_publish.md")


def test_article_pipeline_scores_and_selects_revised_wechat_candidate(tmp_path, monkeypatch):
    state = {
        "task": {
            "task_id": "article_contract",
            "source_type": "wechat_article",
            "article_text": "原文第一段：AI 工具正在改变内容生产。\n\n原文第二段：团队需要把流程做成可验证闭环。",
            "source_title": "AI 创作流程",
            "target_lang": "zh-Hans",
            "auto_translate": True,
            "status": "pending",
            "stages": {},
        }
    }

    def update_task(_task_id, **kwargs):
        task = state["task"]
        for key, value in kwargs.items():
            if key == "stages":
                task["stages"] = value
            elif value is not monitor_db._UNSET:
                task[key] = value

    class FakeClient:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def call_with_retry(self, prompt, input_data, **_kwargs):
            payload = str(input_data)
            self.calls.append((prompt, payload))
            if "可继续加工的中文公众号文章素材" in prompt:
                return "## 整理素材\n\nAI 工具正在改变内容生产，团队需要可验证闭环。"
            if "二次创作风格画像" in prompt:
                return "## 风格画像\n\n短段落，高信息密度。\n\n## 结构模式\n\n判断 -> 方法 -> 行动。"
            if "公众号发布前可用的摘要素材" in prompt:
                return "一句话摘要：AI 创作需要闭环。\n\n- 关键要点：流程、验证、复用。"
            if "二次创作为" in prompt:
                return "## 初稿\n\nAI 工具正在改变内容生产。"
            if "根据质量评估意见修订候选稿" in prompt:
                return "## 修订后正文\n\nAI 工具正在改变内容生产，关键不是更快生成，而是把提示词、素材和评分做成闭环。"
            if "评估候选稿" in prompt and "修订后正文" in payload:
                return json.dumps(
                    {
                        "score": 8.4,
                        "rationale": "修订稿补足了闭环方法",
                        "strengths": ["结构更完整"],
                        "risks": [],
                        "revision_instructions": "",
                    },
                    ensure_ascii=False,
                )
            if "评估候选稿" in prompt:
                return json.dumps(
                    {
                        "score": 5.5,
                        "rationale": "初稿缺少方法层",
                        "strengths": ["事实未偏离"],
                        "risks": ["内容过短"],
                        "revision_instructions": "补充流程闭环和行动建议",
                    },
                    ensure_ascii=False,
                )
            raise AssertionError(f"unexpected prompt: {prompt[:80]}")

    fake_client = FakeClient()
    monkeypatch.setattr(article_generator.db, "get_article_task", lambda _task_id: state["task"])
    monkeypatch.setattr(article_generator.db, "update_article_task", update_task)
    monkeypatch.setattr(article_generator.db, "now_iso", lambda: "2026-05-01T12:00:00+08:00")
    monkeypatch.setattr(article_generator, "create_llm_client", lambda **_kwargs: fake_client)

    result = article_generator.ArticleGenerationPipeline(
        "article_contract",
        cfg={
            "article_output_dir": str(tmp_path / "articles"),
            "llm_base_url": "http://llm.invalid/v1",
            "llm_model": "fake-model",
            "article_llm_min_score": 7.0,
        },
    ).run()

    assert result["status"] == "done"
    draft = Path(result["draft_path"]).read_text(encoding="utf-8")
    assert "修订后正文" in draft
    metadata = result["result"]
    assert metadata["article_prompt_pipeline_version"] == "wechat-style-score-v1"
    assert metadata["article_revision_applied"] is True
    assert metadata["article_quality_score"] == 8.4
    assert Path(metadata["article_style_profile_path"]).is_file()
    assert Path(metadata["article_final_body_path"]).read_text(encoding="utf-8").startswith("## 修订后正文")

    evaluation_record = json.loads(Path(metadata["article_evaluation_path"]).read_text(encoding="utf-8"))
    assert evaluation_record["selected"] == "revision"
    assert evaluation_record["initial"]["score"] == 5.5
    assert evaluation_record["revision"]["score"] == 8.4
    assert result["stages"]["quality_review"]["status"] == "done"
    assert result["stages"]["revision"]["status"] == "done"
    assert any("二次创作风格画像" in prompt for prompt, _payload in fake_client.calls)
    assert any("评估候选稿" in prompt for prompt, _payload in fake_client.calls)


def test_article_pipeline_marks_improved_revision_below_threshold(tmp_path, monkeypatch):
    state = {
        "task": {
            "task_id": "article_contract",
            "source_type": "wechat_article",
            "article_text": "原文：AI 创作要有提示词、素材处理和质量评估。",
            "source_title": "AI 创作流程",
            "target_lang": "zh-Hans",
            "auto_translate": True,
            "status": "pending",
            "stages": {},
        }
    }

    def update_task(_task_id, **kwargs):
        task = state["task"]
        for key, value in kwargs.items():
            if key == "stages":
                task["stages"] = value
            elif value is not monitor_db._UNSET:
                task[key] = value

    class FakeClient:
        def call_with_retry(self, prompt, input_data, **_kwargs):
            payload = str(input_data)
            if "可继续加工的中文公众号文章素材" in prompt:
                return "## 素材\n\nAI 创作要形成闭环。"
            if "二次创作风格画像" in prompt:
                return "## 风格画像\n\n短段落。"
            if "公众号发布前可用的摘要素材" in prompt:
                return "一句话摘要：AI 创作要闭环。"
            if "二次创作为" in prompt:
                return "## 初稿\n\nAI 创作要有提示词。"
            if "根据质量评估意见修订候选稿" in prompt:
                return "## 修订稿\n\nAI 创作要把提示词、素材处理和质量评估连起来。"
            if "评估候选稿" in prompt and "修订稿" in payload:
                return json.dumps({"score": 6.5, "rationale": "有所改善但仍不够完整"}, ensure_ascii=False)
            if "评估候选稿" in prompt:
                return json.dumps(
                    {"score": 5.5, "rationale": "初稿过短", "revision_instructions": "补充闭环"},
                    ensure_ascii=False,
                )
            raise AssertionError(f"unexpected prompt: {prompt[:80]}")

    monkeypatch.setattr(article_generator.db, "get_article_task", lambda _task_id: state["task"])
    monkeypatch.setattr(article_generator.db, "update_article_task", update_task)
    monkeypatch.setattr(article_generator.db, "now_iso", lambda: "2026-05-01T12:00:00+08:00")
    monkeypatch.setattr(article_generator, "create_llm_client", lambda **_kwargs: FakeClient())

    result = article_generator.ArticleGenerationPipeline(
        "article_contract",
        cfg={
            "article_output_dir": str(tmp_path / "articles"),
            "llm_base_url": "http://llm.invalid/v1",
            "llm_model": "fake-model",
            "article_llm_min_score": 7.0,
        },
    ).run()

    metadata = result["result"]
    evaluation_record = json.loads(Path(metadata["article_evaluation_path"]).read_text(encoding="utf-8"))

    assert result["status"] == "done"
    assert metadata["article_revision_applied"] is True
    assert metadata["article_quality_score"] == 6.5
    assert metadata["article_quality_passed"] is False
    assert metadata["article_quality_selection_status"] == "revision_improved_but_below_threshold"
    assert evaluation_record["selected"] == "revision"
    assert evaluation_record["selected_passes_threshold"] is False
    assert "仍低于阈值" in result["stages"]["revision"]["message"]


def test_local_whisper_model_path_resolves_huggingface_snapshot(tmp_path):
    model_root = tmp_path / "models--Systran--faster-distil-whisper-large-v2"
    snapshot = model_root / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "model.bin").write_bytes(b"model")

    assert article_generator._resolve_local_whisper_model_path(str(model_root)) == str(snapshot)


def test_local_whisper_model_alias_is_left_for_faster_whisper_loader():
    assert article_generator._resolve_local_whisper_model_path("base") == "base"
    assert article_generator._resolve_local_whisper_model_path("Systran/faster-whisper-base") == "Systran/faster-whisper-base"


def test_local_whisper_normalizes_configured_source_language():
    assert article_generator._normalize_local_whisper_language("auto") is None
    assert article_generator._normalize_local_whisper_language("zh-Hans") == "zh"
    assert article_generator._normalize_local_whisper_language("en") == "en"


def test_local_whisper_clamps_chunk_seconds_to_safe_window():
    assert article_generator._local_whisper_chunk_seconds({}) == 45
    assert article_generator._local_whisper_chunk_seconds({}, low_vram_gpu=True) == 30
    assert article_generator._local_whisper_chunk_seconds({"whisper_chunk_seconds": "10"}) == 30
    assert article_generator._local_whisper_chunk_seconds({"whisper_chunk_seconds": 45}) == 45
    assert article_generator._local_whisper_chunk_seconds({"whisper_chunk_seconds": 90}) == 60


def _treat_local_whisper_test_audio_as_short(monkeypatch):
    monkeypatch.setattr(article_generator, "_probe_media_duration_seconds", lambda _path: 25.0)


def test_split_audio_for_whisper_uses_ffmpeg_segment_output(monkeypatch, tmp_path):
    source = tmp_path / "source.webm"
    source.write_bytes(b"fake audio")
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        Path(str(command[-1]).replace("%04d", "0000")).write_bytes(b"chunk")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(article_generator.shutil, "which", lambda name: f"{name}.exe")
    monkeypatch.setattr(article_generator.subprocess, "run", fake_run)

    chunks = article_generator._split_audio_for_whisper(source, tmp_path / "chunks", 45)

    assert [chunk.name for chunk in chunks] == ["chunk_0000.wav"]
    command = commands[0]
    assert command[0] == "ffmpeg.exe"
    assert command[command.index("-segment_time") + 1] == "45"
    assert command[command.index("-ar") + 1] == "16000"
    assert command[command.index("-segment_format") + 1] == "wav"
    assert command[-1].endswith("chunk_%04d.wav")


def test_local_whisper_splits_long_audio_before_transcribing(monkeypatch, tmp_path):
    video_path = tmp_path / "source.webm"
    video_path.write_bytes(b"fake audio")
    split_calls: list[tuple[Path, int]] = []
    transcribed_names: list[str] = []
    messages: list[str] = []

    def fake_split(path, output_dir, chunk_seconds):
        split_calls.append((Path(path), chunk_seconds))
        chunk_dir = Path(output_dir)
        chunks = []
        for index in range(3):
            chunk = chunk_dir / f"chunk_{index:04d}.wav"
            chunk.write_bytes(b"chunk")
            chunks.append(chunk)
        return chunks

    class FakeWhisperModel:
        def __init__(self, **_kwargs):
            pass

        def transcribe(self, path, language=None):
            assert language is None
            transcribed_names.append(Path(path).name)
            return [SimpleNamespace(text=Path(path).stem, end=10.0)], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    monkeypatch.setattr(article_generator, "_probe_media_duration_seconds", lambda _path: 125.0)
    monkeypatch.setattr(article_generator, "_split_audio_for_whisper", fake_split)

    result = article_generator._local_whisper(
        str(video_path),
        {"whisper_model": str(tmp_path), "whisper_chunk_seconds": 45},
        progress=messages.append,
    )

    assert result == "chunk_0000 chunk_0001 chunk_0002"
    assert split_calls == [(video_path, 45)]
    assert transcribed_names == ["chunk_0000.wav", "chunk_0001.wav", "chunk_0002.wav"]
    assert not list(tmp_path.glob(".whisper_chunks_*"))
    assert any("Whisper 音频分片完成：3 段" in message for message in messages)
    assert any("正在转写分片 1/3" in message for message in messages)


def test_local_whisper_unknown_duration_splits_before_transcribing(monkeypatch, tmp_path):
    video_path = tmp_path / "source.webm"
    video_path.write_bytes(b"fake audio")
    split_calls: list[tuple[Path, int]] = []
    transcribed_names: list[str] = []

    def fake_split(path, output_dir, chunk_seconds):
        split_calls.append((Path(path), chunk_seconds))
        chunk = Path(output_dir) / "chunk_0000.wav"
        chunk.write_bytes(b"chunk")
        return [chunk]

    class FakeWhisperModel:
        def __init__(self, **_kwargs):
            pass

        def transcribe(self, path, language=None):
            assert language is None
            transcribed_names.append(Path(path).name)
            return [SimpleNamespace(text="whole")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    monkeypatch.setattr(article_generator, "_probe_media_duration_seconds", lambda _path: None)
    monkeypatch.setattr(article_generator, "_split_audio_for_whisper", fake_split)

    assert (
        article_generator._local_whisper(
            str(video_path),
            {"whisper_model": str(tmp_path), "whisper_chunk_seconds": 45},
        )
        == "whole"
    )
    assert split_calls == [(video_path, 45)]
    assert transcribed_names == ["chunk_0000.wav"]


def test_local_whisper_short_audio_does_not_split(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")

    class FakeWhisperModel:
        def __init__(self, **_kwargs):
            pass

        def transcribe(self, path, language=None):
            assert path == str(video_path)
            assert language is None
            return [SimpleNamespace(text="short"), SimpleNamespace(text="audio")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    monkeypatch.setattr(article_generator, "_probe_media_duration_seconds", lambda _path: 25.0)
    monkeypatch.setattr(
        article_generator,
        "_split_audio_for_whisper",
        lambda *_args, **_kwargs: pytest.fail("short audio should not be split"),
    )

    assert (
        article_generator._local_whisper(
            str(video_path),
            {"whisper_model": str(tmp_path), "whisper_chunk_seconds": 45},
        )
        == "short audio"
    )


def test_local_whisper_passes_low_resource_transcribe_options_and_language(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    _treat_local_whisper_test_audio_as_short(monkeypatch)
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, **_kwargs):
            pass

        def transcribe(self, path, **kwargs):
            assert path == str(video_path)
            captured.update(kwargs)
            return [SimpleNamespace(text="你好")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    assert (
        article_generator._local_whisper(
            str(video_path),
            {"whisper_model": str(tmp_path), "whisper_language": "zh-Hans"},
        )
        == "你好"
    )
    assert captured == {
        "language": "zh",
        "beam_size": 1,
        "best_of": 1,
        "condition_on_previous_text": False,
    }


def test_local_whisper_split_failure_does_not_transcribe_whole_file(monkeypatch, tmp_path):
    video_path = tmp_path / "source.webm"
    video_path.write_bytes(b"fake audio")
    model_inits: list[object] = []
    transcribed_names: list[str] = []
    messages: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            model_inits.append(kwargs)

        def transcribe(self, path, language=None):
            assert language is None
            transcribed_names.append(Path(path).name)
            return [SimpleNamespace(text="whole file")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    monkeypatch.setattr(article_generator, "_probe_media_duration_seconds", lambda _path: 90.0)
    monkeypatch.setattr(
        article_generator,
        "_split_audio_for_whisper",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ffmpeg unavailable")),
    )

    result = article_generator._local_whisper(
        str(video_path),
        {"whisper_model": str(tmp_path), "whisper_chunk_seconds": 45},
        progress=messages.append,
    )

    assert result is None
    assert model_inits == []
    assert transcribed_names == []
    assert any("音频分片失败，已停止整文件转写" in message for message in messages)


def test_local_whisper_cleans_chunks_after_transcription_failure(monkeypatch, tmp_path):
    video_path = tmp_path / "source.webm"
    video_path.write_bytes(b"fake audio")

    def fake_split(_path, output_dir, _chunk_seconds):
        chunk = Path(output_dir) / "chunk_0000.wav"
        chunk.write_bytes(b"chunk")
        return [chunk]

    class FakeWhisperModel:
        def __init__(self, **_kwargs):
            pass

        def transcribe(self, _path, language=None):
            assert language is None
            raise RuntimeError("transcribe failed")

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    monkeypatch.setattr(article_generator, "_probe_media_duration_seconds", lambda _path: 90.0)
    monkeypatch.setattr(article_generator, "_split_audio_for_whisper", fake_split)

    result = article_generator._local_whisper(
        str(video_path),
        {"whisper_model": str(tmp_path), "whisper_compute_type": "int8"},
    )

    assert result is None
    assert not list(tmp_path.glob(".whisper_chunks_*"))


def test_local_whisper_uses_plain_model_instance(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    _treat_local_whisper_test_audio_as_short(monkeypatch)

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            assert kwargs["device"] == "cpu"
            assert kwargs["compute_type"] == "int8"

        def transcribe(self, path, language=None):
            assert path == str(video_path)
            assert language is None
            return [SimpleNamespace(text="hello"), SimpleNamespace(text="world")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    assert article_generator._local_whisper(str(video_path), {"whisper_model": str(tmp_path)}) == "hello world"


def test_local_whisper_auto_starts_with_cpu_friendly_int8(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    _treat_local_whisper_test_audio_as_short(monkeypatch)
    attempts: list[tuple[str, str]] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            attempts.append((kwargs["device"], kwargs["compute_type"]))

        def transcribe(self, path, language=None):
            assert path == str(video_path)
            assert language is None
            return [SimpleNamespace(text="fallback"), SimpleNamespace(text="ok")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    assert article_generator._local_whisper(str(video_path), {"whisper_model": str(tmp_path)}) == "fallback ok"
    assert attempts == [("cpu", "int8")]


def test_local_whisper_reports_compute_retry_progress(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    _treat_local_whisper_test_audio_as_short(monkeypatch)
    messages: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            if kwargs["compute_type"] == "int8":
                raise RuntimeError("int8 unavailable")

        def transcribe(self, path, language=None):
            assert path == str(video_path)
            assert language is None
            return [SimpleNamespace(text="fallback"), SimpleNamespace(text="ok")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    result = article_generator._local_whisper(
        str(video_path),
        {"whisper_model": str(tmp_path)},
        progress=messages.append,
    )

    assert result == "fallback ok"
    assert any("本地 Whisper 候选：int8(cpu) -> int8_float32(cpu) -> float32(cpu)" in message for message in messages)
    assert any("compute_type=int8" in message and "失败" in message for message in messages)
    assert any("compute_type=int8_float32" in message and "转写完成" in message for message in messages)


def test_local_whisper_reports_segment_progress_for_long_transcription(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    _treat_local_whisper_test_audio_as_short(monkeypatch)
    messages: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **_kwargs):
            pass

        def transcribe(self, path, language=None):
            assert path == str(video_path)
            assert language is None
            segments = [SimpleNamespace(text=f"part {index}", end=float(index * 10)) for index in range(1, 10)]
            return segments, object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    result = article_generator._local_whisper(
        str(video_path),
        {"whisper_model": str(tmp_path)},
        progress=messages.append,
    )

    assert result is not None
    assert "part 9" in result
    assert any("转写中：已处理约 80s" in message for message in messages)


def test_local_whisper_explicit_float16_falls_back_to_supported_cpu_float32(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    _treat_local_whisper_test_audio_as_short(monkeypatch)
    attempts: list[tuple[str, str]] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            compute_type = kwargs["compute_type"]
            attempts.append((kwargs["device"], compute_type))
            if compute_type == "float16":
                raise RuntimeError(
                    "Requested float16 compute type, but the target device or backend "
                    "do not support efficient float16 computation."
                )

        def transcribe(self, path, language=None):
            assert path == str(video_path)
            assert language is None
            return [SimpleNamespace(text="float32"), SimpleNamespace(text="fallback")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    result = article_generator._local_whisper(
        str(video_path),
        {"whisper_model": str(tmp_path), "whisper_compute_type": "float16"},
    )

    assert result == "float32 fallback"
    assert attempts == [("cpu", "float32")]


def test_local_whisper_auto_compute_can_fall_back_to_float32(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    _treat_local_whisper_test_audio_as_short(monkeypatch)
    attempts: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            compute_type = kwargs["compute_type"]
            attempts.append(compute_type)
            if compute_type in {"int8", "int8_float32"}:
                raise RuntimeError(f"{compute_type} unavailable")

        def transcribe(self, path, language=None):
            assert path == str(video_path)
            assert language is None
            return [SimpleNamespace(text="float32"), SimpleNamespace(text="ok")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    assert article_generator._local_whisper(str(video_path), {"whisper_model": str(tmp_path)}) == "float32 ok"
    assert attempts == ["int8", "int8_float32", "float32"]


def test_local_whisper_respects_configured_float32_compute_type(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    _treat_local_whisper_test_audio_as_short(monkeypatch)
    attempts: list[tuple[str, str]] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            attempts.append((kwargs["device"], kwargs["compute_type"]))

        def transcribe(self, path, language=None):
            assert path == str(video_path)
            assert language is None
            return [SimpleNamespace(text="float32"), SimpleNamespace(text="only")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    result = article_generator._local_whisper(
        str(video_path),
        {"whisper_model": str(tmp_path), "whisper_compute_type": "flout32"},
    )

    assert result == "float32 only"
    assert attempts == [("cpu", "float32")]


def test_local_whisper_current_float32_config_prefers_low_vram_cuda_plan():
    plan = article_generator._local_whisper_candidate_plan(
        {"whisper_compute_type": "float32"},
        cuda_available=True,
        cuda_supported_compute_types={"int8", "int8_float32", "float32"},
        cpu_supported_compute_types={"int8", "int8_float32", "float32"},
        gpu_total_mb=2048,
        gpu_free_mb=1360,
    )

    assert plan == [
        ("int8", "cuda"),
        ("int8_float32", "cuda"),
        ("int8", "cpu"),
        ("int8_float32", "cpu"),
        ("float32", "cpu"),
    ]


def test_local_whisper_uses_low_vram_cuda_before_cpu_fallback(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    _treat_local_whisper_test_audio_as_short(monkeypatch)
    monkeypatch.setattr(article_generator, "_local_whisper_cuda_available", lambda: True)
    monkeypatch.setattr(article_generator, "_local_whisper_gpu_memory_mb", lambda: (2048, 1360))
    monkeypatch.setattr(
        article_generator,
        "_local_whisper_supported_compute_types",
        lambda device: {"int8", "int8_float32", "float32"},
    )
    attempts: list[tuple[str, str]] = []
    messages: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            attempts.append((kwargs["device"], kwargs["compute_type"]))
            if kwargs["device"] == "cuda":
                raise RuntimeError("CUDA out of memory")

        def transcribe(self, path, language=None):
            assert path == str(video_path)
            assert language is None
            return [SimpleNamespace(text="cpu"), SimpleNamespace(text="fallback")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    result = article_generator._local_whisper(
        str(video_path),
        {"whisper_model": str(tmp_path), "whisper_compute_type": "float32"},
        progress=messages.append,
    )

    assert result == "cpu fallback"
    assert attempts == [
        ("cuda", "int8"),
        ("cuda", "int8_float32"),
        ("cpu", "int8"),
    ]
    assert any("检测到 CUDA" in message and "low_vram=true" in message for message in messages)
    assert any("int8(cuda) -> int8_float32(cuda) -> int8(cpu)" in message for message in messages)


def test_local_whisper_reports_final_failure_summary(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    _treat_local_whisper_test_audio_as_short(monkeypatch)
    messages: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            raise RuntimeError(f"{kwargs['compute_type']} unavailable")

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    result = article_generator._local_whisper(
        str(video_path),
        {"whisper_model": str(tmp_path)},
        progress=messages.append,
    )

    assert result is None
    assert any("已尝试 int8(cpu), int8_float32(cpu), float32(cpu)" in message for message in messages)
    assert any("最后错误" in message and "float32 unavailable" in message for message in messages)
