"""Request/result dataclasses for speech synthesis and transcription."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SpeechSynthesisRequest:
    text: str
    output_dir: Path
    output_name: str = "narration"
    provider: str | None = None
    flow: str = "manual_voice"
    mode: str | None = None
    voice: str | None = None
    language: str | None = None
    model: str | None = None
    response_format: str = "wav"
    speed: float | None = None
    pitch: str | None = None
    volume: str | None = None
    style: str | None = None
    control_instruction: str | None = None
    reference_audio_path: str | None = None
    prompt_text: str | None = None
    normalize_text: bool | None = None
    denoise_reference: bool | None = None
    streaming: bool = False
    source: str = "manual"
    source_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.output_dir = Path(self.output_dir)


@dataclass
class SpeechSynthesisResult:
    provider: str
    path: Path
    mime_type: str
    duration_sec: float | None = None
    sample_rate: int | None = None
    metadata_path: Path | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.path = Path(self.path)
        if self.metadata_path is not None:
            self.metadata_path = Path(self.metadata_path)


@dataclass
class TranscriptSegment:
    start: float | None
    end: float | None
    text: str
    speaker: str | None = None


@dataclass
class TranscriptionRequest:
    media_path: str | Path
    output_dir: Path
    provider: str | None = None
    flow: str = "manual_voice"
    language_hint: str = "auto"
    hotwords: list[str] = field(default_factory=list)
    diarization: bool = False
    source: str = "manual"
    source_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.output_dir = Path(self.output_dir)


@dataclass
class TranscriptionResult:
    provider: str
    text: str
    language: str | None = None
    transcript_path: Path | None = None
    srt_path: Path | None = None
    raw_path: Path | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.transcript_path is not None:
            self.transcript_path = Path(self.transcript_path)
        if self.srt_path is not None:
            self.srt_path = Path(self.srt_path)
        if self.raw_path is not None:
            self.raw_path = Path(self.raw_path)
