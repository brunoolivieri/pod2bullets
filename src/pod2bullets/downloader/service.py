"""On-demand audio download service with atomic file operations and progress tracking."""

import hashlib
import json
import logging
from pathlib import Path

import httpx

from pod2bullets.config import settings
from pod2bullets.db.repository import Repository
from pod2bullets.models import Episode, EpisodeStatus

logger = logging.getLogger("pod2bullets.downloader")


class DownloaderService:
    def __init__(self, repo: Repository, client: httpx.Client | None = None):
        self.repo = repo
        self.client = client or httpx.Client(timeout=60.0, follow_redirects=True)

    def download_episode(
        self,
        episode_id: int,
        progress_callback: callable | None = None,
    ) -> Path:
        """Download podcast episode audio strictly on-demand."""
        episode: Episode = self.repo.get_episode(episode_id)
        if not episode:
            raise ValueError(f"Episódio {episode_id} não encontrado")

        feed = self.repo.get_feed(episode.feed_id)
        if not feed:
            raise ValueError(f"Feed {episode.feed_id} não encontrado")

        # Destination structure: data/podcasts/<podcast-slug>/<episode-slug>/
        episode_dir = settings.podcasts_dir / feed.slug / episode.slug
        episode_dir.mkdir(parents=True, exist_ok=True)
        final_audio_path = episode_dir / f"audio.{episode.audio_ext}"
        temp_audio_path = settings.tmp_dir / f"ep_{episode.id}.part"
        settings.tmp_dir.mkdir(parents=True, exist_ok=True)

        self.repo.update_episode_status(episode.id, EpisodeStatus.DOWNLOADING)
        logger.info(
            f"[DOWNLOAD] Iniciando download sob demanda do episódio #{episode.id} "
            f"'{episode.title}' -> {final_audio_path}"
        )
        logger.info(f"[DOWNLOAD] URL de origem: {episode.audio_url}")

        hasher = hashlib.sha256()
        total_downloaded = 0
        last_logged_bucket = 0

        try:
            with self.client.stream("GET", episode.audio_url) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get("content-length", 0))
                if total_size > 0:
                    logger.info(f"[DOWNLOAD] Tamanho esperado: {total_size / (1024 * 1024):.2f} MB")

                with open(temp_audio_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        if not chunk:
                            continue
                        f.write(chunk)
                        hasher.update(chunk)
                        total_downloaded += len(chunk)
                        if total_size > 0:
                            percent = round((total_downloaded / total_size) * 100, 1)
                            if progress_callback:
                                progress_callback(percent)
                            bucket = int(percent // 5) * 5
                            if bucket >= last_logged_bucket + 5 and bucket <= 100:
                                last_logged_bucket = bucket
                                logger.info(
                                    f"[DOWNLOAD] Episódio #{episode.id}: {bucket}% "
                                    f"({total_downloaded / (1024 * 1024):.1f} / "
                                    f"{total_size / (1024 * 1024):.1f} MB)"
                                )

            # Move atomically to final location
            temp_audio_path.replace(final_audio_path)
            sha256_hash = hasher.hexdigest()
            logger.info(
                f"[DOWNLOAD] Concluído episódio #{episode.id} "
                f"({total_downloaded / (1024 * 1024):.2f} MB, SHA256={sha256_hash[:12]}...)"
            )

            # Save metadata alongside the audio
            meta_path = episode_dir / "episode.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "id": episode.id,
                        "title": episode.title,
                        "guid": episode.guid,
                        "audio_url": episode.audio_url,
                        "sha256": sha256_hash,
                        "size_bytes": total_downloaded,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

            self.repo.update_episode_status(
                episode.id,
                EpisodeStatus.DOWNLOADED,
                local_audio_path=str(final_audio_path),
                file_size_bytes=total_downloaded,
                sha256=sha256_hash,
            )
            return final_audio_path

        except Exception as e:
            logger.error(
                f"[DOWNLOAD] Erro ao baixar episódio #{episode.id} '{episode.title}': {e}",
                exc_info=True,
            )
            if temp_audio_path.exists():
                temp_audio_path.unlink()
            self.repo.update_episode_status(
                episode.id,
                EpisodeStatus.FAILED,
                error_message=str(e),
            )
            raise
