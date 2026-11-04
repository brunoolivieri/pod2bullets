"""NVIDIA Parakeet-TDT via onnx-asr Engine implementation."""

import time
from pathlib import Path

from pod2bullets.config import settings
from pod2bullets.transcriber.audio import load_audio_to_pcm16_mono
from pod2bullets.transcriber.base import (
    TranscriberEngine,
    TranscriptionResult,
    TranscriptionSegment,
)


class OnnxAsrEngine(TranscriberEngine):
    def __init__(self, model_id: str = "parakeet-tdt-0.6b-v3", models_dir: Path | None = None):
        self.model_id = model_id
        self.engine_name = "onnx-asr"
        self.models_dir = models_dir or settings.models_dir
        self.model_dir = self.models_dir / self.model_id
        self._model = None

    def is_available(self) -> bool:
        if not self.model_dir.exists():
            return False
        return any(self.model_dir.glob("*.onnx"))

    def _load_model(self):
        if self._model is not None:
            return self._model
        import onnx_asr

        # Try loading from local dir or HF model
        model_name = "nemo-parakeet-tdt-0.6b-v3"
        try:
            self._model = onnx_asr.load_model(model_name, cache_dir=str(self.model_dir))
        except Exception:
            # Fallback direct HF
            self._model = onnx_asr.load_model("parakeet-tdt-0.6b-v3")
        return self._model

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        progress_callback: callable | None = None,
    ) -> TranscriptionResult:
        start_t = time.time()
        audio_data, duration = load_audio_to_pcm16_mono(audio_path)
        model = self._load_model()

        if progress_callback:
            progress_callback(30.0)

        # Transcribe audio array
        raw_result = model.recognize(audio_data, sample_rate=16000)

        if progress_callback:
            progress_callback(90.0)

        text = ""
        if isinstance(raw_result, str):
            text = raw_result.strip()
        elif hasattr(raw_result, "text"):
            text = raw_result.text.strip()
        else:
            text = str(raw_result).strip()

        elapsed = time.time() - start_t
        if progress_callback:
            progress_callback(100.0)

        segments = (
            [TranscriptionSegment(start_sec=0.0, end_sec=duration, text=text)] if text else []
        )

        return TranscriptionResult(
            plain_text=text,
            segments=segments,
            language=language or "pt",
            duration_proc_seconds=round(elapsed, 2),
            model_id=self.model_id,
            engine_name=self.engine_name,
        )
