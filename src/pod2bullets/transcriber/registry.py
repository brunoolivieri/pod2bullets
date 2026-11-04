"""Model catalog, discovery, installation, uninstallation and factory for pluggable ASR engines."""

import logging
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pod2bullets.config import settings
from pod2bullets.system_status import activity_tracker
from pod2bullets.transcriber.base import TranscriberEngine

logger = logging.getLogger("pod2bullets.models")


@dataclass
class ModelInfo:
    id: str
    name: str
    engine_name: str
    description: str
    size_mb: int
    installed_size_mb: float
    is_installed: bool
    is_installing: bool = False
    is_default: bool = False
    source_repo: str = ""


CATALOG = {
    "whisper-large-v3-turbo": {
        "name": "Whisper Large v3 Turbo",
        "engine": "faster-whisper",
        "fw_name": "large-v3-turbo",
        "desc": "OpenAI Whisper Large v3 Turbo (809M params, CTranslate2). Estado da arte multilíngue (PT/EN) com VAD Silero.",
        "size_mb": 1550,
        "repo": "faster-whisper (large-v3-turbo)",
    },
    "parakeet-tdt-0.6b-v3": {
        "name": "NVIDIA Parakeet TDT 0.6B v3",
        "engine": "onnx-asr",
        "onnx_name": "nemo-parakeet-tdt-0.6b-v3",
        "desc": "NVIDIA FastConformer-TDT v3 (600M params, INT8 ONNX). Altíssima velocidade em GPU e CPU para 25 idiomas (incl. PT/EN).",
        "size_mb": 650,
        "repo": "onnx-asr (nemo-parakeet-tdt-0.6b-v3)",
    },
    "whisper-small": {
        "name": "Whisper Small (Leve / Rápido)",
        "engine": "faster-whisper",
        "fw_name": "small",
        "desc": "OpenAI Whisper Small (244M params, CTranslate2). Mais leve para testes rápidos e máquinas com pouca memória.",
        "size_mb": 465,
        "repo": "faster-whisper (small)",
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
        # Require actual weight files (.bin, .safetensors, or .onnx), not just temp folders
        has_weights = (
            any(model_path.glob("*.bin"))
            or any(model_path.glob("*.safetensors"))
            or any(model_path.glob("*.onnx"))
        )
        return has_weights

    def get_installed_size_mb(self, model_id: str) -> float:
        """Calculate real disk usage of the model directory in MB."""
        model_path = self.models_dir / model_id
        if not model_path.exists() or not model_path.is_dir():
            return 0.0
        total_bytes = sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file())
        return round(total_bytes / (1024 * 1024), 1)

    def install_model(self, model_id: str) -> Path:
        """Install model locally into data/models/<model_id> using native library loaders with verbose logs."""
        meta = CATALOG.get(model_id)
        if not meta:
            raise ValueError(f"Modelo desconhecido: {model_id}")

        dest_dir = self.models_dir / model_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        task_key = f"model_install_{model_id}"
        expected_mb = meta["size_mb"]

        stop_monitor = threading.Event()

        def _monitor_progress() -> None:
            while not stop_monitor.wait(2.0):
                curr_mb = self.get_installed_size_mb(model_id)
                pct = min(99, int((curr_mb / max(expected_mb, 1)) * 100))
                msg = f"Instalando {meta['name']}: {curr_mb:.1f} MB / ~{expected_mb} MB ({pct}%)"
                activity_tracker.set_task(task_key, msg)
                logger.info(f"[MODELS] {msg}")

        activity_tracker.set_task(
            task_key, f"Iniciando instalação de {meta['name']} (~{expected_mb} MB)..."
        )
        logger.info(
            f"[MODELS] === Iniciando instalação local do modelo '{model_id}' em {dest_dir} ==="
        )
        monitor_thread = threading.Thread(target=_monitor_progress, daemon=True)
        monitor_thread.start()
        t0 = time.time()

        try:
            if meta["engine"] == "faster-whisper":
                import faster_whisper

                fw_name = meta.get("fw_name", "large-v3-turbo")
                logger.info(
                    f"[MODELS] Chamando faster_whisper.download_model('{fw_name}', output_dir='{dest_dir}')..."
                )
                faster_whisper.download_model(fw_name, output_dir=str(dest_dir))
            elif meta["engine"] == "onnx-asr":
                import onnx_asr

                onnx_name = meta.get("onnx_name", "nemo-parakeet-tdt-0.6b-v3")
                logger.info(
                    f"[MODELS] Chamando onnx_asr.load_model('{onnx_name}', path='{dest_dir}', quantization='int8')..."
                )
                onnx_asr.load_model(onnx_name, path=dest_dir, quantization="int8")
            else:
                raise ValueError(f"Engine desconhecida: {meta['engine']}")

            elapsed = round(time.time() - t0, 1)
            final_mb = self.get_installed_size_mb(model_id)
            logger.info(
                f"[MODELS] === Modelo '{model_id}' instalado com sucesso! Tamanho em disco: {final_mb} MB (levou {elapsed}s) ==="
            )
            return dest_dir
        except Exception as e:
            logger.error(f"[MODELS] Erro ao instalar modelo '{model_id}': {e}", exc_info=True)
            raise
        finally:
            stop_monitor.set()
            activity_tracker.remove_task(task_key)

    def uninstall_model(self, model_id: str) -> bool:
        """Remove model files from disk."""
        model_path = self.models_dir / model_id
        if model_path.exists() and model_path.is_dir():
            freed_mb = self.get_installed_size_mb(model_id)
            logger.info(
                f"[MODELS] Desinstalando modelo '{model_id}' de {model_path} (liberando {freed_mb} MB)..."
            )
            shutil.rmtree(model_path)
            logger.info(f"[MODELS] Modelo '{model_id}' removido com sucesso.")
            return True
        return False

    def list_models(self, default_model_id: str | None = None) -> list[ModelInfo]:
        def_id = default_model_id or settings.default_model_id
        active_tasks = " ".join(activity_tracker.list_tasks())
        results = []
        for mid, meta in CATALOG.items():
            installed = self.is_model_installed(mid)
            disk_mb = self.get_installed_size_mb(mid)
            display_size = int(disk_mb) if (installed and disk_mb > 1) else meta["size_mb"]
            installing = (meta["name"] in active_tasks) or (mid in active_tasks)
            results.append(
                ModelInfo(
                    id=mid,
                    name=meta["name"],
                    engine_name=meta["engine"],
                    description=meta["desc"],
                    size_mb=display_size,
                    installed_size_mb=disk_mb,
                    is_installed=installed,
                    is_installing=installing,
                    is_default=(mid == def_id),
                    source_repo=meta["repo"],
                )
            )
        return results

    def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        for m in self.list_models():
            if m.id == model_id:
                return m
        return None

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

            return FasterWhisperEngine(
                model_id,
                models_dir=self.models_dir,
                fw_name=meta.get("fw_name", "large-v3-turbo"),
            )
        elif meta["engine"] == "onnx-asr":
            from pod2bullets.transcriber.onnx_asr_engine import OnnxAsrEngine

            return OnnxAsrEngine(model_id, models_dir=self.models_dir)
        else:
            raise ValueError(f"Engine desconhecida: {meta['engine']}")
