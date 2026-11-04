"""Fake transcriber engine for fast, reproducible tests."""

import time
from pathlib import Path

from pod2bullets.transcriber.audio import load_audio_to_pcm16_mono
from pod2bullets.transcriber.base import (
    TranscriberEngine,
    TranscriptionResult,
    TranscriptionSegment,
)


class FakeTranscriberEngine(TranscriberEngine):
    def __init__(
        self, model_id: str = "fake-engine", mock_text: str = "Transcrição de teste simulada."
    ):
        self.model_id = model_id
        self.engine_name = "fake"
        self.mock_text = mock_text

    def is_available(self) -> bool:
        return True

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        progress_callback: callable | None = None,
    ) -> TranscriptionResult:
        start_t = time.time()
        # Decode audio to verify valid format
        _, duration = load_audio_to_pcm16_mono(audio_path)
        if progress_callback:
            progress_callback(50.0)
            progress_callback(100.0)

        elapsed = time.time() - start_t
        segments = [TranscriptionSegment(start_sec=0.0, end_sec=duration, text=self.mock_text)]
        return TranscriptionResult(
            plain_text=self.mock_text,
            segments=segments,
            language=language or "pt",
            duration_proc_seconds=round(elapsed, 3),
            model_id=self.model_id,
            engine_name=self.engine_name,
        )
