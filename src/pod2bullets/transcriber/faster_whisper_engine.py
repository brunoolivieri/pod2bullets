"""Faster-Whisper (CTranslate2) Engine implementation."""

import time
from pathlib import Path

from faster_whisper import WhisperModel

from pod2bullets.config import settings
from pod2bullets.transcriber.audio import load_audio_to_pcm16_mono
from pod2bullets.transcriber.base import (
    TranscriberEngine,
    TranscriptionResult,
    TranscriptionSegment,
)


class FasterWhisperEngine(TranscriberEngine):
    def __init__(self, model_id: str = "whisper-large-v3-turbo", models_dir: Path | None = None):
        self.model_id = model_id
        self.engine_name = "faster-whisper"
        self.models_dir = models_dir or settings.models_dir
        self.model_dir = self.models_dir / self.model_id
        self._model: WhisperModel | None = None

    def is_available(self) -> bool:
        if not self.model_dir.exists():
            return False
        # Needs model.bin or model.safetensors
        return any(self.model_dir.glob("*.bin")) or any(self.model_dir.glob("*.safetensors"))

    def _load_model(self) -> WhisperModel:
        if self._model is not None:
            return self._model

        # Auto-detect CUDA
        device = "cuda" if settings.device in ("cuda", "auto") else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

        # Check if local files exist, otherwise HuggingFace ID
        model_source = (
            str(self.model_dir) if self.is_available() else "Systran/faster-whisper-large-v3-turbo"
        )

        self._model = WhisperModel(
            model_source,
            device=device,
            compute_type=compute_type,
            download_root=str(self.model_dir),
        )
        return self._model

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        progress_callback: callable | None = None,
    ) -> TranscriptionResult:
        start_t = time.time()
        # Decode to 16kHz float32
        audio_data, duration = load_audio_to_pcm16_mono(audio_path)
        model = self._load_model()

        segments_raw, info = model.transcribe(
            audio_data,
            language=language or "pt",
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        segments = []
        full_text_parts = []
        for s in segments_raw:
            text_clean = s.text.strip()
            if text_clean:
                segments.append(
                    TranscriptionSegment(
                        start_sec=round(s.start, 2),
                        end_sec=round(s.end, 2),
                        text=text_clean,
                    )
                )
                full_text_parts.append(text_clean)
                if progress_callback and duration > 0:
                    percent = min(99.0, round((s.end / duration) * 100, 1))
                    progress_callback(percent)

        if progress_callback:
            progress_callback(100.0)

        elapsed = time.time() - start_t
        plain_text = " ".join(full_text_parts)

        return TranscriptionResult(
            plain_text=plain_text,
            segments=segments,
            language=info.language or "pt",
            duration_proc_seconds=round(elapsed, 2),
            model_id=self.model_id,
            engine_name=self.engine_name,
        )
