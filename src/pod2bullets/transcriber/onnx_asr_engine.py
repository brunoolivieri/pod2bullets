"""NVIDIA Parakeet-TDT via onnx-asr Engine implementation with verbose logging and chunking."""

import logging
import time
from pathlib import Path

from pod2bullets.config import settings
from pod2bullets.transcriber.audio import TARGET_SAMPLE_RATE, load_audio_to_pcm16_mono
from pod2bullets.transcriber.base import (
    TranscriberEngine,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger("pod2bullets.transcriber")


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

        self.model_dir.mkdir(parents=True, exist_ok=True)
        model_name = "nemo-parakeet-tdt-0.6b-v3"
        logger.info(
            f"[TRANSCRIBER] Carregando modelo ONNX '{model_name}' (quantization=int8) em {self.model_dir}..."
        )
        self._model = onnx_asr.load_model(model_name, path=self.model_dir, quantization="int8")
        logger.info(f"[TRANSCRIBER] Modelo '{self.model_id}' carregado com sucesso.")
        return self._model

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        progress_callback: callable | None = None,
    ) -> TranscriptionResult:
        start_t = time.time()
        logger.info(f"[TRANSCRIBER] Decodificando áudio via PyAV: {audio_path}...")
        audio_data, duration = load_audio_to_pcm16_mono(audio_path)
        logger.info(
            f"[TRANSCRIBER] Áudio decodificado: duração={duration:.1f}s ({len(audio_data)} amostras @ 16kHz)."
        )
        model = self._load_model()

        # Process in 30-second chunks for long podcast episodes + live progress reporting
        chunk_sec = 30.0
        chunk_samples = int(chunk_sec * TARGET_SAMPLE_RATE)
        total_samples = len(audio_data)

        if total_samples == 0:
            return TranscriptionResult(
                plain_text="",
                segments=[],
                language=language or "pt",
                duration_proc_seconds=0.0,
                model_id=self.model_id,
                engine_name=self.engine_name,
            )

        segments: list[TranscriptionSegment] = []
        text_parts: list[str] = []

        for offset in range(0, total_samples, chunk_samples):
            chunk = audio_data[offset : offset + chunk_samples]
            start_sec = round(offset / TARGET_SAMPLE_RATE, 2)
            end_sec = round(min(total_samples, offset + chunk_samples) / TARGET_SAMPLE_RATE, 2)

            raw_result = model.recognize(chunk, sample_rate=TARGET_SAMPLE_RATE)
            if isinstance(raw_result, str):
                chunk_text = raw_result.strip()
            elif hasattr(raw_result, "text"):
                chunk_text = raw_result.text.strip()
            else:
                chunk_text = str(raw_result).strip()

            pct = min(99.0, round((end_sec / max(duration, 0.1)) * 100, 1))
            if chunk_text:
                segments.append(
                    TranscriptionSegment(start_sec=start_sec, end_sec=end_sec, text=chunk_text)
                )
                text_parts.append(chunk_text)
                logger.info(
                    f"[TRANSCRIBER] [{start_sec:06.1f}s -> {end_sec:06.1f}s] ({pct}%) {chunk_text[:90]}"
                )

            if progress_callback:
                progress_callback(pct)

        elapsed = round(time.time() - start_t, 2)
        if progress_callback:
            progress_callback(100.0)

        full_text = " ".join(text_parts)
        logger.info(
            f"[TRANSCRIBER] Concluído '{self.model_id}' em {elapsed}s! Palavras={len(full_text.split())}."
        )

        return TranscriptionResult(
            plain_text=full_text,
            segments=segments,
            language=language or "pt",
            duration_proc_seconds=elapsed,
            model_id=self.model_id,
            engine_name=self.engine_name,
        )
