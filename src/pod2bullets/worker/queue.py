"""Background worker for 100% Local Audio Transcription -> Audio Cleanup -> Optional LLM Text Summarization."""

import json
import logging
import threading
import time
from dataclasses import asdict
from pathlib import Path

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.downloader.service import DownloaderService
from pod2bullets.llm.service import LLM_PROVIDERS, LLMService
from pod2bullets.models import (
    Episode,
    EpisodeStatus,
    Job,
    JobCancelError,
    JobStatus,
)
from pod2bullets.naming import slugify
from pod2bullets.transcriber.base import TranscriberEngine, TranscriptionResult
from pod2bullets.transcriber.registry import CATALOG, ModelRegistry

logger = logging.getLogger("pod2bullets.worker")


def parse_job_models(raw_model_field: str | None) -> tuple[str, str | None]:
    """Split a job's model_id field ('<asr_model>|<llm_provider>') into (asr_model_id, llm_provider)."""
    if not raw_model_field:
        return settings.default_model_id, None
    if "|" in raw_model_field:
        asr_part, llm_part = raw_model_field.split("|", 1)
        asr_model = asr_part.strip() or settings.default_model_id
        llm_prov = llm_part.strip()
        if llm_prov in ("", "none"):
            return asr_model, None
        return asr_model, llm_prov
    return raw_model_field.strip(), None


class BackgroundWorker:
    def __init__(self, db_path: Path | None = None, registry: ModelRegistry | None = None):
        self.db_path = db_path or settings.db_path
        self.registry = registry or ModelRegistry()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, name="pod2bullets-worker", daemon=True
        )
        self._thread.start()
        logger.info("[WORKER] BackgroundWorker iniciado e monitorando fila de jobs.")

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("[WORKER] BackgroundWorker parado.")

    def _run_loop(self):
        while self._running:
            try:
                processed = self.process_next_job()
                if not processed:
                    time.sleep(0.8)
            except Exception as e:
                logger.error(f"[WORKER] Erro inesperado no loop do worker: {e}", exc_info=True)
                time.sleep(2.0)

    def process_next_job(self) -> bool:
        """Fetch and execute next pending job: Download -> Auto Model Install -> Local ASR -> Delete MP3 -> Optional LLM Text Summary."""
        conn = get_db_connection(self.db_path)
        repo = Repository(conn)
        job: Job = repo.get_next_pending_job()
        if not job:
            conn.close()
            return False

        repo.update_job_status(job.id, JobStatus.RUNNING, progress_percent=0.0)
        audio_path: Path | None = None

        def _check_cancelled() -> None:
            if repo.is_job_cancelled(job.id):
                raise JobCancelError(f"Job #{job.id} cancelado pelo usuário.")

        try:
            episode: Episode = repo.get_episode(job.episode_id)
            if not episode:
                raise ValueError(f"Episódio {job.episode_id} não encontrado")

            feed = repo.get_feed(episode.feed_id)
            asr_model_id, llm_provider = parse_job_models(job.model_id)
            llm_info_str = (
                f" + Resumo LLM ({llm_provider})" if llm_provider else " (Apenas Transcrição Local)"
            )
            logger.info(
                f"[WORKER] === Iniciando Job #{job.id} | "
                f"Podcast: '{feed.title if feed else '?'}' | "
                f"Episódio #{episode.id}: '{episode.title}' | "
                f"ASR Local: {asr_model_id}{llm_info_str} ==="
            )
            _check_cancelled()

            # 0. Auto-install local ASR model if not yet installed
            if asr_model_id in CATALOG and not self.registry.is_model_installed(asr_model_id):
                logger.info(
                    f"[WORKER] Modelo '{asr_model_id}' ainda não está instalado. "
                    f"Instalando automaticamente para executar o Job #{job.id}..."
                )
                self.registry.install_model(asr_model_id)
                _check_cancelled()

            # 1. Download phase (0% -> 100% matching bash)
            last_dl_pct = [-1.0]

            if episode.local_audio_path and Path(episode.local_audio_path).exists():
                audio_path = Path(episode.local_audio_path)
                logger.info(f"[WORKER] Áudio já presente em disco: {audio_path}")
            else:
                downloader = DownloaderService(repo)

                def on_dl_progress(p: float):
                    _check_cancelled()
                    step_5 = float(int(p // 5) * 5)
                    if step_5 != last_dl_pct[0] or p >= 99.5:
                        last_dl_pct[0] = step_5
                        repo.update_job_status(
                            job.id, JobStatus.RUNNING, progress_percent=min(100.0, step_5)
                        )

                audio_path = downloader.download_episode(
                    episode.id, progress_callback=on_dl_progress
                )
            _check_cancelled()

            # 2. Local ASR Transcription flow (0% -> 100% matching bash 5% by 5%)
            logger.info(
                f"[WORKER] Iniciando transcrição local do episódio #{episode.id} "
                f"com modelo '{asr_model_id}'..."
            )
            repo.update_episode_status(episode.id, EpisodeStatus.TRANSCRIBING)
            repo.update_job_status(job.id, JobStatus.RUNNING, progress_percent=0.0)

            engine: TranscriberEngine = self.registry.get_engine(asr_model_id)
            last_tx_pct = [-1.0]

            def on_transcribe_progress(p: float):
                _check_cancelled()
                step_val = float(int(p // 5) * 5)
                if step_val != last_tx_pct[0]:
                    last_tx_pct[0] = step_val
                    repo.update_job_status(
                        job.id, JobStatus.RUNNING, progress_percent=min(100.0, step_val)
                    )

            result: TranscriptionResult = engine.transcribe(
                audio_path=audio_path,
                progress_callback=on_transcribe_progress,
            )
            _check_cancelled()

            # 3. Save .txt and .meta.json files in data/podcasts/<feed>/<ep>/transcripts/
            transcripts_dir = audio_path.parent / "transcripts"
            transcripts_dir.mkdir(parents=True, exist_ok=True)

            txt_filename = f"{slugify(episode.title)}__{asr_model_id}.txt"
            meta_filename = f"{slugify(episode.title)}__{asr_model_id}.meta.json"

            txt_path = transcripts_dir / txt_filename
            meta_path = transcripts_dir / meta_filename

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(result.plain_text)

            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "episode_id": episode.id,
                        "model_id": asr_model_id,
                        "engine_name": result.engine_name,
                        "language": result.language,
                        "duration_proc_seconds": result.duration_proc_seconds,
                        "char_count": len(result.plain_text),
                        "word_count": len(result.plain_text.split()),
                        "segments": [asdict(s) for s in result.segments],
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

            repo.record_transcript(
                episode_id=episode.id,
                model_id=asr_model_id,
                engine_name=result.engine_name,
                language=result.language,
                plain_text_path=str(txt_path),
                meta_json_path=str(meta_path),
                char_count=len(result.plain_text),
                word_count=len(result.plain_text.split()),
                duration_proc_seconds=result.duration_proc_seconds,
            )

            # 4. Delete the audio (.mp3/etc.) file immediately after local transcription
            if audio_path and audio_path.exists():
                audio_path.unlink(missing_ok=True)
                logger.info(
                    f"[WORKER] Arquivo de áudio apagado após transcrição concluída: {audio_path} "
                    "(pode ser reprocessado sob demanda a qualquer momento)"
                )

            # 5. If the user also selected an LLM provider alongside local transcription,
            # summarize the local .txt transcript now!
            llm_warning_msg = None
            if llm_provider and llm_provider in LLM_PROVIDERS:
                _check_cancelled()
                repo.update_episode_status(episode.id, EpisodeStatus.SUMMARIZING_LLM)
                repo.update_job_status(job.id, JobStatus.RUNNING, progress_percent=95.0)
                logger.info(
                    f"[WORKER] Transcrição local salva! Gerando resumo do texto via LLM ({llm_provider})..."
                )
                try:
                    llm_svc = LLMService(repo)
                    summary_rec = llm_svc.summarize_episode(
                        episode_id=episode.id,
                        provider=llm_provider,
                    )
                    logger.info(
                        f"[WORKER] Resumo da transcrição concluído via {llm_provider} ({summary_rec.model_name}) "
                        f"em {summary_rec.duration_proc_seconds}s!"
                    )
                except Exception as llm_exc:
                    llm_warning_msg = f"Transcrição local concluída, mas o resumo LLM ({llm_provider}) falhou: {llm_exc}"
                    logger.warning(f"[WORKER] ⚠️ {llm_warning_msg}")

            repo.update_episode_status(
                episode.id,
                EpisodeStatus.COMPLETED,
                local_audio_path="",
                error_message=llm_warning_msg,
            )
            repo.update_job_status(job.id, JobStatus.COMPLETED, progress_percent=100.0)
            logger.info(
                f"[WORKER] === Job #{job.id} CONCLUÍDO! Episódio #{episode.id} transcrito em "
                f"{result.duration_proc_seconds}s ({len(result.plain_text.split())} palavras) "
                f"-> {txt_path} ==="
            )

        except JobCancelError:
            logger.info(
                f"[WORKER] 🚫 Job #{job.id} (Episódio #{job.episode_id}) interrompido por cancelamento do usuário."
            )
            if audio_path and audio_path.exists():
                audio_path.unlink(missing_ok=True)
            repo.cancel_job(job.id)
        except Exception as e:
            logger.error(f"[WORKER] Falha ao executar job #{job.id}: {e}", exc_info=True)
            if audio_path and audio_path.exists():
                audio_path.unlink(missing_ok=True)
            repo.update_job_status(job.id, JobStatus.FAILED, error_message=str(e))
            repo.update_episode_status(
                job.episode_id,
                EpisodeStatus.FAILED,
                local_audio_path="",
                error_message=str(e),
            )
        finally:
            conn.close()

        return True
