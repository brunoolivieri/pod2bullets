"""Transcriber protocol and result structures."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class TranscriptionSegment:
    start_sec: float
    end_sec: float
    text: str


@dataclass
class TranscriptionResult:
    plain_text: str
    segments: list[TranscriptionSegment] = field(default_factory=list)
    language: str = "pt"
    duration_proc_seconds: float = 0.0
    model_id: str = ""
    engine_name: str = ""


@runtime_checkable
class TranscriberEngine(Protocol):
    """Protocol for pluggable ASR engines."""

    model_id: str
    engine_name: str

    def is_available(self) -> bool:
        """Check if model weights and dependencies are ready."""
        ...

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        progress_callback: callable | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file and return text + segments."""
        ...
