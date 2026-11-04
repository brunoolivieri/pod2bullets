"""Faster-Whisper (CTranslate2) Engine implementation with verbose terminal logging."""

import logging
import time
from pathlib import Path

import faster_whisper
from faster_whisper import WhisperModel

from pod2bullets.config import settings
from pod2bullets.transcriber.audio import load_audio_to_pcm16_mono
from pod2bullets.transcriber.base import (
    TranscriberEngine,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger("pod2bullets.transcriber")


class FasterWhisperEngine(TranscriberEngine):
    def __init__(
        self,
        model_id: str = "whisper-large-v3-turbo",
        models_dir: Path | None = None,
        fw_name: str = "large-v3-turbo",
    ):
        self.model_id = model_id
        self.fw_name = fw_name
        self.engine_name = "faster-whisper"
        self.models_dir = models_dir or settings.models_dir
        self.model_dir = self.models_dir / self.model_id
        self._model: WhisperModel | None = None

    def is_available(self) -> bool:
        if not self.model_dir.exists():
            return False
        return any(self.model_dir.glob("*.bin")) or any(self.model_dir.glob("*.safetensors"))

    def _load_model(self) -> WhisperModel:
        if self._model is not None:
            return self._model

        if not self.is_available():
            self.model_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                f"[TRANSCRIBER] Modelo '{self.model_id}' ainda não instalado em disco. "
                f"Instalando automaticamente via faster-whisper ('{self.fw_name}') em {self.model_dir}..."
            )
            faster_whisper.download_model(self.fw_name, output_dir=str(self.model_dir))
            logger.info(f"[TRANSCRIBER] Pesos de '{self.model_id}' prontos em {self.model_dir}.")

        preferred_device = "cuda" if settings.device in ("cuda", "auto") else "cpu"
        if preferred_device == "cuda":
            try:
                logger.info(
                    f"[TRANSCRIBER] Carregando '{self.model_id}' na GPU (CUDA, int8_float16) de {self.model_dir}..."
                )
                self._model = WhisperModel(
                    str(self.model_dir),
                    device="cuda",
                    compute_type="int8_float16",
                )
                return self._model
            except Exception as e:
                logger.warning(
                    f"[TRANSCRIBER] Aviso ao inicializar CUDA ({e}); fazendo fallback automático para CPU (int8)..."
                )

        logger.info(
            f"[TRANSCRIBER] Carregando '{self.model_id}' na CPU (int8) de {self.model_dir}..."
        )
        self._model = WhisperModel(
            str(self.model_dir),
            device="cpu",
            compute_type="int8",
        )
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

        def _run_inference(mdl: WhisperModel):
            segments_raw, info = mdl.transcribe(
                audio_data,
                language=language,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            segs = []
            parts = []
            for s in segments_raw:
                text_clean = s.text.strip()
                if text_clean:
                    segs.append(
                        TranscriptionSegment(
                            start_sec=round(s.start, 2),
                            end_sec=round(s.end, 2),
                            text=text_clean,
                        )
                    )
                    parts.append(text_clean)
                    pct = min(99.0, round((s.end / duration) * 100, 1)) if duration > 0 else 50.0
                    logger.info(
                        f"[TRANSCRIBER] [{s.start:06.1f}s -> {s.end:06.1f}s] ({pct}%) {text_clean[:90]}"
                    )
                    if progress_callback and duration > 0:
                        progress_callback(pct)
            return segs, parts, info

        try:
            segments, full_text_parts, info = _run_inference(model)
        except Exception as e:
            logger.warning(
                f"[TRANSCRIBER] Falha durante inferência em GPU ({e}); recarregando em CPU (int8) e continuando..."
            )
            self._model = WhisperModel(str(self.model_dir), device="cpu", compute_type="int8")
            segments, full_text_parts, info = _run_inference(self._model)

        if progress_callback:
            progress_callback(100.0)

        elapsed = round(time.time() - start_t, 2)
        plain_text = " ".join(full_text_parts)
        detected_lang = getattr(info, "language", None) or language or "pt"
        logger.info(
            f"[TRANSCRIBER] Concluído '{self.model_id}' em {elapsed}s! "
            f"Idioma={detected_lang}, Segmentos={len(segments)}, Palavras={len(plain_text.split())}."
        )

        return TranscriptionResult(
            plain_text=plain_text,
            segments=segments,
            language=detected_lang,
            duration_proc_seconds=elapsed,
            model_id=self.model_id,
            engine_name=self.engine_name,
        )
