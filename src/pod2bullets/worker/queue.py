"""Background worker for automated Download -> Transcription pipeline."""

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
from pod2bullets.models import Episode, EpisodeStatus, Job, JobStatus
from pod2bullets.naming import slugify
from pod2bullets.transcriber.base import TranscriberEngine, TranscriptionResult
from pod2bullets.transcriber.registry import ModelRegistry

logger = logging.getLogger("pod2bullets.worker")


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
                    time.sleep(1.0)
            except Exception as e:
                logger.error(f"[WORKER] Erro inesperado no loop do worker: {e}", exc_info=True)
                time.sleep(2.0)

    def process_next_job(self) -> bool:
        """Fetch and execute next pending job in queue."""
        conn = get_db_connection(self.db_path)
        repo = Repository(conn)
        job: Job = repo.get_next_pending_job()
        if not job:
            conn.close()
            return False

        repo.update_job_status(job.id, JobStatus.RUNNING, progress_percent=5.0)

        try:
            episode: Episode = repo.get_episode(job.episode_id)
            if not episode:
                raise ValueError(f"Episódio {job.episode_id} não encontrado")

            feed = repo.get_feed(episode.feed_id)
            model_id = job.model_id or settings.default_model_id
            logger.info(
                f"[WORKER] === Iniciando Job #{job.id} ({job.job_type.value}) | "
                f"Podcast: '{feed.title if feed else '?'}' | "
                f"Episódio #{episode.id}: '{episode.title}' | Modelo: {model_id} ==="
            )

            # 1. Download phase (if audio not downloaded yet)
            audio_path: Path
            if episode.local_audio_path and Path(episode.local_audio_path).exists():
                audio_path = Path(episode.local_audio_path)
                logger.info(f"[WORKER] Áudio já presente em disco: {audio_path}")
            else:
                downloader = DownloaderService(repo)

                def on_dl_progress(p: float):
                    # 0% - 50% of the job is download
                    repo.update_job_status(
                        job.id, JobStatus.RUNNING, progress_percent=round(p * 0.5, 1)
                    )

                audio_path = downloader.download_episode(
                    episode.id, progress_callback=on_dl_progress
                )

            # 2. Automatic transcription phase
            logger.info(
                f"[WORKER] Iniciando transcrição automática do episódio #{episode.id} "
                f"com modelo '{model_id}'..."
            )
            repo.update_episode_status(episode.id, EpisodeStatus.TRANSCRIBING)
            repo.update_job_status(job.id, JobStatus.RUNNING, progress_percent=50.0)

            engine: TranscriberEngine = self.registry.get_engine(model_id)

            def on_transcribe_progress(p: float):
                # 50% - 100% of the job is transcription
                repo.update_job_status(
                    job.id, JobStatus.RUNNING, progress_percent=round(50.0 + (p * 0.5), 1)
                )

            result: TranscriptionResult = engine.transcribe(
                audio_path=audio_path,
                progress_callback=on_transcribe_progress,
            )

            # 3. Save .txt and .meta.json files in data/podcasts/<feed>/<ep>/transcripts/
            transcripts_dir = audio_path.parent / "transcripts"
            transcripts_dir.mkdir(parents=True, exist_ok=True)

            txt_filename = f"{slugify(episode.title)}__{model_id}.txt"
            meta_filename = f"{slugify(episode.title)}__{model_id}.meta.json"

            txt_path = transcripts_dir / txt_filename
            meta_path = transcripts_dir / meta_filename

            # Save plain text
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(result.plain_text)

            # Save metadata and segments
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "episode_id": episode.id,
                        "model_id": model_id,
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

            # Record transcript in SQLite
            repo.record_transcript(
                episode_id=episode.id,
                model_id=model_id,
                engine_name=result.engine_name,
                language=result.language,
                plain_text_path=str(txt_path),
                meta_json_path=str(meta_path),
                char_count=len(result.plain_text),
                word_count=len(result.plain_text.split()),
                duration_proc_seconds=result.duration_proc_seconds,
            )

            repo.update_episode_status(episode.id, EpisodeStatus.COMPLETED)
            repo.update_job_status(job.id, JobStatus.COMPLETED, progress_percent=100.0)
            logger.info(
                f"[WORKER] === Job #{job.id} CONCLUÍDO! Episódio #{episode.id} transcrito em "
                f"{result.duration_proc_seconds}s ({len(result.plain_text.split())} palavras) "
                f"-> {txt_path} ==="
            )

        except Exception as e:
            logger.error(f"[WORKER] Falha ao executar job #{job.id}: {e}", exc_info=True)
            repo.update_job_status(job.id, JobStatus.FAILED, error_message=str(e))
            repo.update_episode_status(job.episode_id, EpisodeStatus.FAILED, error_message=str(e))
        finally:
            conn.close()

        return True
