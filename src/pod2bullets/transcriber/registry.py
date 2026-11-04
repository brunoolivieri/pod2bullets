"""Model catalog, discovery and factory for pluggable ASR engines."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pod2bullets.config import settings
from pod2bullets.transcriber.base import TranscriberEngine


@dataclass
class ModelInfo:
    id: str
    name: str
    engine_name: str
    description: str
    size_mb: int
    is_installed: bool
    is_default: bool = False
    source_repo: str = ""


CATALOG = {
    "whisper-large-v3-turbo": {
        "name": "Whisper Large v3 Turbo",
        "engine": "faster-whisper",
        "desc": "OpenAI Large v3 Turbo (809M params). Rápido, multilíngue e estado da arte com VAD Silero.",
        "size_mb": 1600,
        "repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    },
    "parakeet-tdt-0.6b-v3": {
        "name": "NVIDIA Parakeet TDT 0.6B v3",
        "engine": "onnx-asr",
        "desc": "NVIDIA NeMo FastConformer-TDT (600M params). #1 no Open ASR Leaderboard em eficiência/WER.",
        "size_mb": 650,
        "repo": "istupakov/parakeet-tdt-0.6b-v3-onnx",
    },
}


class ModelRegistry:
    def __init__(self, models_dir: Path | None = None):
        self.models_dir = models_dir or settings.models_dir
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def is_model_installed(self, model_id: str) -> bool:
        model_path = self.models_dir / model_id
        if not model_path.exists() or not model_path.is_dir():
            return False
        # Check if dir has files
        return any(model_path.iterdir())

    def get_installed_size_mb(self, model_id: str) -> float:
        """Calculate real disk usage of the installed model in MB."""
        model_path = self.models_dir / model_id
        if not model_path.exists() or not model_path.is_dir():
            return 0.0
        total_bytes = sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file())
        return round(total_bytes / (1024 * 1024), 1)

    def uninstall_model(self, model_id: str) -> bool:
        """Remove model files from disk."""
        import shutil

        model_path = self.models_dir / model_id
        if model_path.exists() and model_path.is_dir():
            shutil.rmtree(model_path)
            return True
        return False

    def list_models(self, default_model_id: str | None = None) -> list[ModelInfo]:
        def_id = default_model_id or settings.default_model_id
        results = []
        for mid, meta in CATALOG.items():
            installed = self.is_model_installed(mid)
            real_size = self.get_installed_size_mb(mid) if installed else meta["size_mb"]
            results.append(
                ModelInfo(
                    id=mid,
                    name=meta["name"],
                    engine_name=meta["engine"],
                    description=meta["desc"],
                    size_mb=int(real_size),
                    is_installed=installed,
                    is_default=(mid == def_id),
                    source_repo=meta["repo"],
                )
            )
        return results

    def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        meta = CATALOG.get(model_id)
        if not meta:
            return None
        return ModelInfo(
            id=model_id,
            name=meta["name"],
            engine_name=meta["engine"],
            description=meta["desc"],
            size_mb=meta["size_mb"],
            is_installed=self.is_model_installed(model_id),
            is_default=(model_id == settings.default_model_id),
            source_repo=meta["repo"],
        )

    def get_engine(self, model_id: str) -> TranscriberEngine:
        """Instantiate the engine for the chosen model."""
        if model_id == "fake-engine":
            from pod2bullets.transcriber.fake_engine import FakeTranscriberEngine

            return FakeTranscriberEngine(model_id)

        meta = CATALOG.get(model_id)
        if not meta:
            raise ValueError(f"Modelo desconhecido: {model_id}")

        if meta["engine"] == "faster-whisper":
            from pod2bullets.transcriber.faster_whisper_engine import FasterWhisperEngine

            return FasterWhisperEngine(model_id, models_dir=self.models_dir)
        elif meta["engine"] == "onnx-asr":
            from pod2bullets.transcriber.onnx_asr_engine import OnnxAsrEngine

            return OnnxAsrEngine(model_id, models_dir=self.models_dir)
        else:
            raise ValueError(f"Engine desconhecida: {meta['engine']}")
