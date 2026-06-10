from __future__ import annotations

import base64
import json

import pytest

from monitor.voice.schemas import SpeechSynthesisRequest
from monitor.voice.synthesis import (
    AzureSpeechProvider,
    MiniMaxSpeechProvider,
    OpenAiSpeechProvider,
    VibeVoiceRealtimeProvider,
    VibeVoiceTtsProvider,
    VoxCpmHttpProvider,
    VoxCpmOpenAiSpeechProvider,
    build_synthesis_registry,
)


class FakeHttpResponse:
    def __init__(self, data: bytes, content_type: str = "audio/wav", status: int = 200):
        self._data = data
        self.headers = {"Content-Type": content_type}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._data


def _request(tmp_path, **overrides):
    payload = {
        "text": "hello external voice",
        "output_dir": tmp_path,
        "provider": "openai_speech",
        "flow": "manual_voice",
        "source": "manual_voice",
        "source_task_id": "voice_external_1",
        "response_format": "wav",
    }
    payload.update(overrides)
    return SpeechSynthesisRequest(**payload)


def test_build_registry_registers_external_synthesis_providers():
    registry = build_synthesis_registry()

    assert isinstance(registry.get("openai_speech"), OpenAiSpeechProvider)
    assert isinstance(registry.get("azure_speech"), AzureSpeechProvider)
    assert isinstance(registry.get("minimax_speech"), MiniMaxSpeechProvider)
    assert isinstance(registry.get("voxcpm_openai_speech"), VoxCpmOpenAiSpeechProvider)
    assert isinstance(registry.get("voxcpm_http"), VoxCpmHttpProvider)
    assert isinstance(registry.get("vibevoice_tts"), VibeVoiceTtsProvider)
    assert isinstance(registry.get("vibevoice_realtime"), VibeVoiceRealtimeProvider)


def test_external_providers_do_not_advertise_unimplemented_streaming_capability():
    from monitor.voice.capabilities import STREAMING_SYNTHESIS

    registry = build_synthesis_registry()
    for provider_id in ("openai_speech", "voxcpm_openai_speech", "voxcpm_http", "vibevoice_realtime"):
        assert STREAMING_SYNTHESIS not in registry.require(provider_id).info().capabilities


def test_openai_provider_writes_raw_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(b"openai-audio", "audio/wav"),
    )

    result = OpenAiSpeechProvider().synthesize(
        _request(tmp_path, provider="openai_speech"),
        {
            "openai_speech_api_key": "sk-test",
            "openai_speech_base_url": "https://api.openai.com/v1",
        },
    )

    assert result.provider == "openai_speech"
    assert result.path.read_bytes() == b"openai-audio"
    assert result.mime_type == "audio/wav"
    assert "sk-test" not in result.metadata_path.read_text(encoding="utf-8")


def test_azure_provider_posts_ssml_and_writes_raw_audio(monkeypatch, tmp_path):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeHttpResponse(b"azure-audio", "audio/wav")

    monkeypatch.setattr("monitor.voice.synthesis.urllib.request.urlopen", fake_urlopen)

    result = AzureSpeechProvider().synthesize(
        _request(
            tmp_path,
            provider="azure_speech",
            text='hello <voice> & "friends"',
            language="en-US",
            voice="en-US-AvaMultilingualNeural",
            speed=1.1,
            pitch="+5%",
            volume="+2dB",
            style="cheerful",
        ),
        {
            "azure_speech_api_key": "azure-secret",
            "azure_speech_region": "eastus",
            "azure_speech_output_format": "riff-24khz-16bit-mono-pcm",
        },
    )

    request, timeout = requests[0]
    body = request.data.decode("utf-8")
    assert request.full_url == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    assert request.headers["Ocp-apim-subscription-key"] == "azure-secret"
    assert request.headers["X-microsoft-outputformat"] == "riff-24khz-16bit-mono-pcm"
    assert "<mstts:express-as" in body
    assert "hello &lt;voice&gt; &amp; \"friends\"" in body
    assert result.path.read_bytes() == b"azure-audio"
    assert timeout == 300


def test_minimax_provider_decodes_hex_audio(monkeypatch, tmp_path):
    response = {
        "data": {"audio": b"minimax-audio".hex(), "status": 2},
        "extra_info": {"audio_format": "mp3", "audio_length": 1234},
        "trace_id": "trace-1",
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(
            json.dumps(response).encode("utf-8"),
            "application/json",
        ),
    )

    result = MiniMaxSpeechProvider().synthesize(
        _request(tmp_path, provider="minimax_speech", response_format="mp3"),
        {
            "minimax_speech_api_key": "minimax-secret",
            "minimax_speech_base_url": "https://api.minimax.io",
            "minimax_speech_model": "speech-2.8-hd",
            "minimax_speech_voice": "English_expressive_narrator",
        },
    )

    assert result.path.read_bytes() == b"minimax-audio"
    assert result.path.suffix == ".mp3"
    assert result.raw_metadata["trace_id"] == "trace-1"


@pytest.mark.parametrize(
    ("provider_cls", "provider_id", "base_url_key", "base_url"),
    [
        (VoxCpmHttpProvider, "voxcpm_http", "voxcpm_base_url", "http://127.0.0.1:8808"),
        (VibeVoiceTtsProvider, "vibevoice_tts", "vibevoice_tts_base_url", "http://127.0.0.1:8810"),
        (
            VibeVoiceRealtimeProvider,
            "vibevoice_realtime",
            "vibevoice_tts_base_url",
            "http://127.0.0.1:8810",
        ),
    ],
)
def test_generic_http_providers_accept_base64_audio(
    monkeypatch,
    tmp_path,
    provider_cls,
    provider_id,
    base_url_key,
    base_url,
):
    response = {
        "audio_base64": base64.b64encode(b"generic-audio").decode("ascii"),
        "format": "wav",
    }
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(
            json.dumps(response).encode("utf-8"),
            "application/json",
        ),
    )

    result = provider_cls().synthesize(
        _request(tmp_path, provider=provider_id),
        {base_url_key: base_url},
    )

    assert result.provider == provider_id
    assert result.path.read_bytes() == b"generic-audio"


def test_voxcpm_openai_compatible_provider_writes_raw_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(b"voxcpm-audio", "audio/wav"),
    )

    result = VoxCpmOpenAiSpeechProvider().synthesize(
        _request(tmp_path, provider="voxcpm_openai_speech"),
        {"voxcpm_base_url": "http://127.0.0.1:8000", "voxcpm_model": "openbmb/VoxCPM2"},
    )

    assert result.provider == "voxcpm_openai_speech"
    assert result.path.read_bytes() == b"voxcpm-audio"


def test_external_provider_requires_its_configuration(tmp_path):
    with pytest.raises(ValueError, match="openai_speech_api_key"):
        OpenAiSpeechProvider().synthesize(_request(tmp_path), {})


def test_external_provider_strips_signed_audio_url_from_metadata(monkeypatch, tmp_path):
    responses = iter(
        [
            FakeHttpResponse(
                json.dumps(
                    {
                        "audio_url": "https://cdn.example/audio.wav?token=signed-secret",
                        "format": "wav",
                    }
                ).encode("utf-8"),
                "application/json",
            ),
        ]
    )
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: next(responses),
    )
    monkeypatch.setattr(
        "monitor.voice.synthesis._urlopen_audio",
        lambda *_args, **_kwargs: FakeHttpResponse(b"downloaded-audio", "audio/wav"),
    )

    result = VibeVoiceTtsProvider().synthesize(
        _request(tmp_path, provider="vibevoice_tts"),
        {"vibevoice_tts_base_url": "https://cdn.example"},
    )

    metadata = result.metadata_path.read_text(encoding="utf-8")
    assert "signed-secret" not in metadata
    assert "https://cdn.example/audio.wav" in metadata


def test_external_provider_rejects_cross_origin_audio_download(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(
            json.dumps(
                {
                    "audio_url": "https://cdn.example/audio.wav",
                    "format": "wav",
                }
            ).encode("utf-8"),
            "application/json",
        ),
    )

    with pytest.raises(RuntimeError, match="outside provider origin"):
        VibeVoiceTtsProvider().synthesize(
            _request(tmp_path, provider="vibevoice_tts"),
            {"vibevoice_tts_base_url": "https://voice.example"},
        )


def test_external_provider_rejects_link_local_audio_download(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(
            json.dumps(
                {
                    "audio_url": "http://169.254.169.254/latest/meta-data",
                    "format": "wav",
                }
            ).encode("utf-8"),
            "application/json",
        ),
    )

    with pytest.raises(RuntimeError, match="outside provider origin"):
        VibeVoiceTtsProvider().synthesize(
            _request(tmp_path, provider="vibevoice_tts"),
            {"vibevoice_tts_base_url": "https://voice.example"},
        )


def test_external_provider_rejects_dns_private_audio_download(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(
            json.dumps(
                {
                    "audio_url": "http://audio.example/internal.wav",
                    "format": "wav",
                }
            ).encode("utf-8"),
            "application/json",
        ),
    )
    monkeypatch.setattr(
        "monitor.voice.synthesis.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, "", ("127.0.0.1", 0))],
    )

    with pytest.raises(RuntimeError, match="outside provider origin"):
        VibeVoiceTtsProvider().synthesize(
            _request(tmp_path, provider="vibevoice_tts"),
            {"vibevoice_tts_base_url": "https://voice.example"},
        )


def test_provider_response_size_is_limited(monkeypatch, tmp_path):
    monkeypatch.setattr("monitor.voice.synthesis._MAX_PROVIDER_RESPONSE_BYTES", 4)
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(b"too-large", "audio/wav"),
    )

    with pytest.raises(RuntimeError, match="size limit"):
        OpenAiSpeechProvider().synthesize(
            _request(tmp_path, provider="openai_speech"),
            {"openai_speech_api_key": "sk-test"},
        )


def test_provider_returned_local_audio_path_is_size_limited(monkeypatch, tmp_path):
    audio_path = tmp_path / "provider-output.wav"
    audio_path.write_bytes(b"too-large")
    monkeypatch.setattr("monitor.voice.synthesis._MAX_PROVIDER_RESPONSE_BYTES", 4)
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(
            json.dumps({"audio_path": str(audio_path), "format": "wav"}).encode("utf-8"),
            "application/json",
        ),
    )

    with pytest.raises(RuntimeError, match="size limit"):
        VibeVoiceTtsProvider().synthesize(
            _request(tmp_path, provider="vibevoice_tts"),
            {"vibevoice_tts_base_url": "https://voice.example"},
        )
