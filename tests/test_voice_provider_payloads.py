from __future__ import annotations

import json

from monitor.voice.schemas import SpeechSynthesisRequest
from monitor.voice.synthesis import (
    MiniMaxSpeechProvider,
    OpenAiSpeechProvider,
    VibeVoiceRealtimeProvider,
    VoxCpmHttpProvider,
    VoxCpmOpenAiSpeechProvider,
)


class FakeHttpResponse:
    def __init__(self, data: bytes = b"audio", content_type: str = "audio/wav"):
        self._data = data
        self.headers = {"Content-Type": content_type}
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._data


def _request(tmp_path, **overrides):
    payload = {
        "text": "payload contract",
        "output_dir": tmp_path,
        "flow": "manual_voice",
        "source": "manual_voice",
        "source_task_id": "payload_1",
        "response_format": "wav",
    }
    payload.update(overrides)
    return SpeechSynthesisRequest(**payload)


def _capture_request(monkeypatch, response=None):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return response or FakeHttpResponse()

    monkeypatch.setattr("monitor.voice.synthesis.urllib.request.urlopen", fake_urlopen)
    return calls


def test_openai_payload_matches_audio_speech_contract(monkeypatch, tmp_path):
    calls = _capture_request(monkeypatch)

    OpenAiSpeechProvider().synthesize(
        _request(
            tmp_path,
            provider="openai_speech",
            voice="coral",
            model="gpt-4o-mini-tts",
            response_format="wav",
            speed=1.25,
            control_instruction="Speak calmly.",
        ),
        {
            "openai_speech_api_key": "sk-test",
            "openai_speech_base_url": "https://api.openai.com/v1/",
        },
    )

    request, _timeout = calls[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.openai.com/v1/audio/speech"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert payload == {
        "model": "gpt-4o-mini-tts",
        "input": "payload contract",
        "voice": "coral",
        "response_format": "wav",
        "speed": 1.25,
        "instructions": "Speak calmly.",
    }


def test_minimax_payload_matches_t2a_v2_contract(monkeypatch, tmp_path):
    response = FakeHttpResponse(
        json.dumps(
            {
                "data": {"audio": b"audio".hex(), "status": 2},
                "extra_info": {"audio_format": "wav"},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            }
        ).encode("utf-8"),
        "application/json",
    )
    calls = _capture_request(monkeypatch, response)

    MiniMaxSpeechProvider().synthesize(
        _request(
            tmp_path,
            provider="minimax_speech",
            voice="English_expressive_narrator",
            model="speech-2.8-hd",
            speed=1.1,
            pitch="+2",
            volume="0.8",
            language="en",
        ),
        {
            "minimax_speech_api_key": "minimax-key",
            "minimax_speech_base_url": "https://api.minimax.io/",
        },
    )

    request, _timeout = calls[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.minimax.io/v1/t2a_v2"
    assert request.headers["Authorization"] == "Bearer minimax-key"
    assert payload["model"] == "speech-2.8-hd"
    assert payload["text"] == "payload contract"
    assert payload["stream"] is False
    assert payload["output_format"] == "hex"
    assert payload["language_boost"] == "English"
    assert payload["voice_setting"] == {
        "voice_id": "English_expressive_narrator",
        "speed": 1.1,
        "vol": 0.8,
        "pitch": 2,
    }
    assert payload["audio_setting"]["format"] == "wav"


def test_minimax_voice_design_uses_design_endpoint(monkeypatch, tmp_path):
    response = FakeHttpResponse(
        json.dumps(
            {
                "trial_audio": b"designed-audio".hex(),
                "voice_id": "ttv-voice-designed",
                "base_resp": {"status_code": 0, "status_msg": "success"},
            }
        ).encode("utf-8"),
        "application/json",
    )
    calls = _capture_request(monkeypatch, response)

    result = MiniMaxSpeechProvider().synthesize(
        _request(
            tmp_path,
            provider="minimax_speech",
            mode="voice_design",
            control_instruction="Warm documentary narrator",
            response_format="wav",
        ),
        {
            "minimax_speech_api_key": "minimax-key",
            "minimax_speech_base_url": "https://api.minimax.io",
        },
    )

    request, _timeout = calls[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.minimax.io/v1/voice_design"
    assert payload == {
        "prompt": "Warm documentary narrator",
        "preview_text": "payload contract",
    }
    assert result.path.read_bytes() == b"designed-audio"
    assert result.raw_metadata["voice_id"] == "ttv-voice-designed"


def test_minimax_reference_clone_uploads_then_synthesizes(monkeypatch, tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference-audio")
    responses = iter(
        [
            FakeHttpResponse(
                json.dumps(
                    {
                        "file": {"file_id": 12345},
                        "base_resp": {"status_code": 0, "status_msg": "success"},
                    }
                ).encode("utf-8"),
                "application/json",
            ),
            FakeHttpResponse(
                json.dumps(
                    {
                        "base_resp": {"status_code": 0, "status_msg": "success"},
                        "input_sensitive": False,
                    }
                ).encode("utf-8"),
                "application/json",
            ),
            FakeHttpResponse(
                json.dumps(
                    {
                        "data": {"audio": b"cloned-audio".hex(), "status": 2},
                        "extra_info": {"audio_format": "wav"},
                        "base_resp": {"status_code": 0, "status_msg": "success"},
                    }
                ).encode("utf-8"),
                "application/json",
            ),
        ]
    )
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return next(responses)

    monkeypatch.setattr("monitor.voice.synthesis.urllib.request.urlopen", fake_urlopen)

    result = MiniMaxSpeechProvider().synthesize(
        _request(
            tmp_path,
            provider="minimax_speech",
            mode="reference_clone",
            reference_audio_path=str(reference),
            voice="VoiceClone001",
        ),
        {
            "minimax_speech_api_key": "minimax-key",
            "minimax_speech_base_url": "https://api.minimax.io",
            "voice_allow_reference_clone": True,
            "voice_output_dir": str(tmp_path),
        },
    )

    assert [request.full_url for request, _timeout in calls] == [
        "https://api.minimax.io/v1/files/upload",
        "https://api.minimax.io/v1/voice_clone",
        "https://api.minimax.io/v1/t2a_v2",
    ]
    upload_request = calls[0][0]
    assert b'name="purpose"\r\n\r\nvoice_clone' in upload_request.data
    clone_payload = json.loads(calls[1][0].data.decode("utf-8"))
    assert clone_payload["file_id"] == 12345
    assert clone_payload["voice_id"] == "VoiceClone001"
    assert "text" not in clone_payload
    t2a_payload = json.loads(calls[2][0].data.decode("utf-8"))
    assert t2a_payload["voice_setting"]["voice_id"] == "VoiceClone001"
    assert result.path.read_bytes() == b"cloned-audio"


def test_voxcpm_openai_payload_uses_official_compatible_shape(monkeypatch, tmp_path):
    calls = _capture_request(monkeypatch)

    VoxCpmOpenAiSpeechProvider().synthesize(
        _request(tmp_path, provider="voxcpm_openai_speech", voice="default"),
        {
            "voxcpm_base_url": "http://127.0.0.1:8000/v1",
            "voxcpm_model": "openbmb/VoxCPM2",
            "voxcpm_api_key": "local-key",
        },
    )

    request, _timeout = calls[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "http://127.0.0.1:8000/v1/audio/speech"
    assert request.headers["Authorization"] == "Bearer local-key"
    assert payload == {
        "model": "openbmb/VoxCPM2",
        "input": "payload contract",
        "voice": "default",
        "response_format": "wav",
    }


def test_voxcpm_generic_payload_keeps_advanced_fields_behind_generic_contract(monkeypatch, tmp_path):
    calls = _capture_request(monkeypatch)

    VoxCpmHttpProvider().synthesize(
        _request(
            tmp_path,
            provider="voxcpm_http",
            mode="voice_design",
            control_instruction="warm narrator",
            normalize_text=True,
            denoise_reference=False,
        ),
        {
            "voxcpm_base_url": "http://127.0.0.1:8808",
            "voxcpm_model": "openbmb/VoxCPM2",
            "voice_allow_reference_clone": False,
            "voice_allow_prompt_transcript_clone": False,
        },
    )

    request, _timeout = calls[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "http://127.0.0.1:8808/tts"
    assert payload["mode"] == "voice_design"
    assert payload["control_instruction"] == "warm narrator"
    assert payload["normalize_text"] is True
    assert payload["denoise_reference"] is False
    assert "reference_audio_path" not in payload
    assert "prompt_text" not in payload


def test_vibevoice_realtime_payload_marks_streaming_without_websocket_dependency(monkeypatch, tmp_path):
    calls = _capture_request(monkeypatch)

    VibeVoiceRealtimeProvider().synthesize(
        _request(tmp_path, provider="vibevoice_realtime", streaming=True, voice="Carter"),
        {
            "vibevoice_tts_base_url": "http://127.0.0.1:8810",
            "vibevoice_tts_model": "microsoft/VibeVoice-Realtime-0.5B",
        },
    )

    request, _timeout = calls[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "http://127.0.0.1:8810/tts"
    assert payload["streaming"] is True
    assert payload["model"] == "microsoft/VibeVoice-Realtime-0.5B"
    assert payload["voice"] == "Carter"
