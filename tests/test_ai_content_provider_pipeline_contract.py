"""Regression tests for AI content provider adapters and persisted task options."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db
from scripts import article_generator
from scripts.video_gen_pipeline import VideoGenerationPipeline, _generated_file_url


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
    assert "transcript from whisper" in Path(result["draft_path"]).read_text(encoding="utf-8")
    assert "已切换 Whisper" in result["stages"]["subtitles"]["message"]


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
    monkeypatch.setattr(
        wechat_publisher,
        "render_md_to_html_for_wechat",
        lambda *_args, **_kwargs: SimpleNamespace(
            title="公众号原文",
            content="<p>正文</p>",
            author=None,
            digest="摘要",
        ),
    )
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

    assert observed == {"status_during_publish": "running", "stage_during_publish": "wechat"}
    assert result["status"] == "done"
    assert result["current_stage"] == "done"
    assert result["stages"]["wechat"]["status"] == "done"
    assert result["result"]["wx_article_id"] == "media-1"


def test_local_whisper_model_path_resolves_huggingface_snapshot(tmp_path):
    model_root = tmp_path / "models--Systran--faster-distil-whisper-large-v2"
    snapshot = model_root / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "model.bin").write_bytes(b"model")

    assert article_generator._resolve_local_whisper_model_path(str(model_root)) == str(snapshot)


def test_local_whisper_uses_plain_model_instance(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")

    class FakeWhisperModel:
        def __init__(self, **_kwargs):
            pass

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


def test_local_whisper_retries_float32_when_float16_is_unsupported(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    attempts: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            compute_type = kwargs["compute_type"]
            attempts.append(compute_type)
            if compute_type == "float16":
                raise RuntimeError(
                    "Requested float16 compute type, but the target device or backend "
                    "do not support efficient float16 computation."
                )

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
    assert attempts == ["float16", "float32"]


def test_local_whisper_reports_compute_retry_progress(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    messages: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            if kwargs["compute_type"] == "float16":
                raise RuntimeError(
                    "Requested float16 compute type, but the target device or backend "
                    "do not support efficient float16 computation."
                )

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
    assert any("compute_type=float16" in message and "失败" in message for message in messages)
    assert any("compute_type=float32" in message and "转写完成" in message for message in messages)


def test_local_whisper_explicit_float16_still_retries_float32(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    attempts: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            compute_type = kwargs["compute_type"]
            attempts.append(compute_type)
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
    assert attempts == ["float16", "float32"]


def test_local_whisper_auto_compute_can_fall_back_to_int8(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    attempts: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            compute_type = kwargs["compute_type"]
            attempts.append(compute_type)
            if compute_type in {"float16", "float32"}:
                raise RuntimeError(f"{compute_type} unavailable")

        def transcribe(self, path, language=None):
            assert path == str(video_path)
            assert language is None
            return [SimpleNamespace(text="int8"), SimpleNamespace(text="ok")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    assert article_generator._local_whisper(str(video_path), {"whisper_model": str(tmp_path)}) == "int8 ok"
    assert attempts == ["float16", "float32", "int8"]


def test_local_whisper_respects_configured_float32_compute_type(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
    attempts: list[str] = []

    class FakeWhisperModel:
        def __init__(self, **kwargs):
            attempts.append(kwargs["compute_type"])

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
    assert attempts == ["float32"]


def test_local_whisper_reports_final_failure_summary(monkeypatch, tmp_path):
    video_path = tmp_path / "source.wav"
    video_path.write_bytes(b"fake audio")
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
    assert any("compute_type=float16, float32, int8" in message for message in messages)
    assert any("最后错误" in message and "int8 unavailable" in message for message in messages)
