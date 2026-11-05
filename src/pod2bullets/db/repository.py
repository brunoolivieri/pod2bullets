"""Repository layer for database CRUD operations."""

import sqlite3
from pathlib import Path
from typing import Optional

from pod2bullets.models import (
    Episode,
    EpisodeStatus,
    Job,
    JobStatus,
    PodcastFeed,
    SubscriptionList,
    Transcript,
    TranscriptSummary,
)


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Settings ---
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    # --- Subscription Lists ---
    def create_list(
        self, name: str, slug: str, description: Optional[str] = None
    ) -> SubscriptionList:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO subscription_lists (name, slug, description, created_at) VALUES (?, ?, ?, datetime('now'))",
            (name, slug, description),
        )
        list_id = cur.lastrowid
        self.conn.commit()
        return self.get_list(list_id)

    def get_list(self, list_id: int) -> Optional[SubscriptionList]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM subscription_lists WHERE id = ?", (list_id,))
        row = cur.fetchone()
        return SubscriptionList(**dict(row)) if row else None

    def get_list_by_slug(self, slug: str) -> Optional[SubscriptionList]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM subscription_lists WHERE slug = ?", (slug,))
        row = cur.fetchone()
        return SubscriptionList(**dict(row)) if row else None

    def list_all_lists(self) -> list[SubscriptionList]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM subscription_lists ORDER BY name ASC")
        return [SubscriptionList(**dict(r)) for r in cur.fetchall()]

    def delete_list(self, list_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM subscription_lists WHERE id = ?", (list_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # --- Feeds ---
    def create_feed(
        self,
        title: str,
        slug: str,
        rss_url: str,
        site_url: Optional[str] = None,
        description: Optional[str] = None,
        image_url: Optional[str] = None,
    ) -> PodcastFeed:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO feeds (title, slug, rss_url, site_url, description, image_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (title, slug, rss_url, site_url, description, image_url),
        )
        feed_id = cur.lastrowid
        self.conn.commit()
        return self.get_feed(feed_id)

    def get_feed(self, feed_id: int) -> Optional[PodcastFeed]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM feeds WHERE id = ?", (feed_id,))
        row = cur.fetchone()
        return PodcastFeed(**dict(row)) if row else None

    def get_feed_by_rss(self, rss_url: str) -> Optional[PodcastFeed]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM feeds WHERE rss_url = ?", (rss_url,))
        row = cur.fetchone()
        return PodcastFeed(**dict(row)) if row else None

    def list_feeds(self, list_id: Optional[int] = None) -> list[PodcastFeed]:
        cur = self.conn.cursor()
        if list_id is not None:
            cur.execute(
                """SELECT f.* FROM feeds f
                   JOIN feed_list_members m ON f.id = m.feed_id
                   WHERE m.list_id = ? ORDER BY f.title ASC""",
                (list_id,),
            )
        else:
            cur.execute("SELECT * FROM feeds ORDER BY title ASC")
        return [PodcastFeed(**dict(r)) for r in cur.fetchall()]

    def add_feed_to_list(self, feed_id: int, list_id: int) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO feed_list_members (feed_id, list_id) VALUES (?, ?)",
            (feed_id, list_id),
        )
        self.conn.commit()

    def remove_feed_from_list(self, feed_id: int, list_id: int) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM feed_list_members WHERE feed_id = ? AND list_id = ?",
            (feed_id, list_id),
        )
        self.conn.commit()

    def get_feed_lists(self, feed_id: int) -> list[SubscriptionList]:
        cur = self.conn.cursor()
        cur.execute(
            """SELECT l.* FROM subscription_lists l
               JOIN feed_list_members m ON l.id = m.list_id
               WHERE m.feed_id = ? ORDER BY l.name ASC""",
            (feed_id,),
        )
        return [SubscriptionList(**dict(r)) for r in cur.fetchall()]

    # --- Episodes ---
    def upsert_episode(
        self,
        feed_id: int,
        guid: str,
        title: str,
        slug: str,
        audio_url: str,
        audio_ext: str = "mp3",
        image_url: Optional[str] = None,
        published_at: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        summary: Optional[str] = None,
    ) -> Episode:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO episodes (feed_id, guid, title, slug, audio_url, audio_ext, image_url, published_at, duration_seconds, summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(feed_id, guid) DO UPDATE SET
                   title = excluded.title,
                   slug = excluded.slug,
                   audio_url = excluded.audio_url,
                   image_url = COALESCE(excluded.image_url, episodes.image_url),
                   published_at = COALESCE(excluded.published_at, episodes.published_at),
                   summary = excluded.summary
               RETURNING *""",
            (
                feed_id,
                guid,
                title,
                slug,
                audio_url,
                audio_ext,
                image_url,
                published_at,
                duration_seconds,
                summary,
            ),
        )
        row = cur.fetchone()
        self.conn.commit()
        return Episode(**dict(row))

    def get_episode(self, episode_id: int) -> Optional[Episode]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,))
        row = cur.fetchone()
        return Episode(**dict(row)) if row else None

    def list_episodes(
        self,
        feed_id: Optional[int] = None,
        status: Optional[EpisodeStatus] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[Episode]:
        cur = self.conn.cursor()
        query = "SELECT * FROM episodes WHERE 1=1"
        params = []
        if feed_id:
            query += " AND feed_id = ?"
            params.append(feed_id)
        if status:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY published_at DESC, id DESC"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        cur.execute(query, tuple(params))
        return [Episode(**dict(r)) for r in cur.fetchall()]

    def update_episode_status(
        self,
        episode_id: int,
        status: EpisodeStatus,
        local_audio_path: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        sha256: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        cur = self.conn.cursor()
        updates = ["status = ?"]
        params: list = [status.value]
        if local_audio_path is not None:
            updates.append("local_audio_path = ?")
            params.append(local_audio_path or None)
        if file_size_bytes is not None:
            updates.append("file_size_bytes = ?")
            params.append(file_size_bytes)
        if sha256 is not None:
            updates.append("sha256 = ?")
            params.append(sha256)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        params.append(episode_id)
        cur.execute(f"UPDATE episodes SET {', '.join(updates)} WHERE id = ?", tuple(params))
        self.conn.commit()

    # --- Transcripts ---
    def record_transcript(
        self,
        episode_id: int,
        model_id: str,
        engine_name: str,
        plain_text_path: str,
        meta_json_path: Optional[str] = None,
        char_count: int = 0,
        word_count: int = 0,
        duration_proc_seconds: Optional[float] = None,
        language: str = "pt",
    ) -> Transcript:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO transcripts (episode_id, model_id, engine_name, language, plain_text_path, meta_json_path, char_count, word_count, duration_proc_seconds, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(episode_id, model_id) DO UPDATE SET
                   plain_text_path = excluded.plain_text_path,
                   meta_json_path = excluded.meta_json_path,
                   char_count = excluded.char_count,
                   word_count = excluded.word_count,
                   duration_proc_seconds = excluded.duration_proc_seconds
               RETURNING *""",
            (
                episode_id,
                model_id,
                engine_name,
                language,
                plain_text_path,
                meta_json_path,
                char_count,
                word_count,
                duration_proc_seconds,
            ),
        )
        row = cur.fetchone()
        self.conn.commit()
        return Transcript(**dict(row))

    def get_transcript(self, episode_id: int, model_id: str) -> Optional[Transcript]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM transcripts WHERE episode_id = ? AND model_id = ?",
            (episode_id, model_id),
        )
        row = cur.fetchone()
        return Transcript(**dict(row)) if row else None

    def list_episode_transcripts(self, episode_id: int) -> list[Transcript]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM transcripts WHERE episode_id = ? ORDER BY created_at DESC", (episode_id,)
        )
        return [Transcript(**dict(r)) for r in cur.fetchall()]

    # --- Summaries (LLM) ---
    def record_summary(
        self,
        episode_id: int,
        provider: str,
        model_name: str,
        prompt_used: str,
        summary_text: str,
        transcript_id: Optional[int] = None,
        summary_path: Optional[str] = None,
        duration_proc_seconds: Optional[float] = None,
    ) -> TranscriptSummary:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO summaries (episode_id, transcript_id, provider, model_name, prompt_used, summary_text, summary_path, duration_proc_seconds, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               RETURNING *""",
            (
                episode_id,
                transcript_id,
                provider,
                model_name,
                prompt_used,
                summary_text,
                summary_path,
                duration_proc_seconds,
            ),
        )
        row = cur.fetchone()
        self.conn.commit()
        return TranscriptSummary(**dict(row))

    def list_episode_summaries(self, episode_id: int) -> list[TranscriptSummary]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM summaries WHERE episode_id = ? ORDER BY id DESC",
            (episode_id,),
        )
        return [TranscriptSummary(**dict(r)) for r in cur.fetchall()]

    def list_all_summaries(
        self,
        feed_id: Optional[int] = None,
        provider: Optional[str] = None,
    ) -> list[dict]:
        """List all summaries across podcasts/episodes with rich metadata for navigation."""
        query = """
            SELECT
                s.id, s.episode_id, s.transcript_id, s.provider, s.model_name,
                s.prompt_used, s.summary_text, s.summary_path, s.duration_proc_seconds,
                s.created_at,
                e.title AS episode_title, e.slug AS episode_slug,
                e.published_at AS episode_published_at, e.image_url AS episode_image_url,
                e.feed_id,
                f.title AS feed_title, f.slug AS feed_slug, f.image_url AS feed_image_url,
                t.model_id AS asr_model_id, t.engine_name AS asr_engine_name
            FROM summaries s
            JOIN episodes e ON e.id = s.episode_id
            JOIN feeds f ON f.id = e.feed_id
            LEFT JOIN transcripts t ON t.id = s.transcript_id
            WHERE 1=1
        """
        params: list = []
        if feed_id:
            query += " AND e.feed_id = ?"
            params.append(feed_id)
        if provider:
            query += " AND s.provider = ?"
            params.append(provider)

        query += " ORDER BY s.id DESC"
        cur = self.conn.cursor()
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]

    def delete_summary(self, summary_id: int) -> bool:
        """Delete a summary from DB and remove its file on disk if present."""
        summary = self.get_summary(summary_id)
        if not summary:
            return False
        if summary.summary_path:
            p = Path(summary.summary_path)
            if p.exists():
                p.unlink(missing_ok=True)
        cur = self.conn.cursor()
        cur.execute("DELETE FROM summaries WHERE id = ?", (summary_id,))
        self.conn.commit()
        return True

    def get_summary(self, summary_id: int) -> Optional[TranscriptSummary]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM summaries WHERE id = ?", (summary_id,))
        row = cur.fetchone()
        return TranscriptSummary(**dict(row)) if row else None

    # --- Jobs ---
    def create_job(self, job_type: str, episode_id: int, model_id: Optional[str] = None) -> Job:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO jobs (job_type, episode_id, model_id, status, progress_percent, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', 0.0, datetime('now'), datetime('now'))
               RETURNING *""",
            (job_type, episode_id, model_id),
        )
        row = cur.fetchone()
        self.conn.commit()
        return Job(**dict(row))

    def get_job(self, job_id: int) -> Optional[Job]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        return Job(**dict(row)) if row else None

    def get_active_job_for_episode(self, episode_id: int) -> Optional[Job]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM jobs WHERE episode_id = ? AND status IN ('pending', 'running') ORDER BY id DESC LIMIT 1",
            (episode_id,),
        )
        row = cur.fetchone()
        return Job(**dict(row)) if row else None

    def get_queue_position(self, job_id: int) -> int:
        """Return 1-based position in the pending/running queue."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM jobs WHERE status IN ('pending', 'running') AND id <= ?",
            (job_id,),
        )
        row = cur.fetchone()
        return int(row["cnt"]) if row else 1

    def get_next_pending_job(self) -> Optional[Job]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM jobs WHERE status = 'pending' ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        return Job(**dict(row)) if row else None

    def update_job_status(
        self,
        job_id: int,
        status: JobStatus,
        progress_percent: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> None:
        cur = self.conn.cursor()
        updates = ["status = ?", "updated_at = datetime('now')"]
        params: list = [status.value]
        if progress_percent is not None:
            updates.append("progress_percent = ?")
            params.append(progress_percent)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        params.append(job_id)
        cur.execute(
            f"UPDATE jobs SET {', '.join(updates)} WHERE id = ? AND status != 'cancelled'",
            tuple(params),
        )
        self.conn.commit()

    def is_job_cancelled(self, job_id: int) -> bool:
        """Check if a job has been marked as cancelled by the user."""
        cur = self.conn.cursor()
        cur.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        return bool(row and row["status"] == "cancelled")

    def list_queue_jobs(self, limit_history: int = 12) -> list[dict]:
        """List all running/pending jobs (in queue order) plus recent completed/cancelled/failed jobs."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT j.id, j.job_type, j.episode_id, j.model_id, j.status,
                   j.progress_percent, j.error_message, j.created_at, j.updated_at,
                   e.title AS episode_title, e.feed_id, e.status AS ep_status,
                   f.title AS feed_title
            FROM jobs j
            LEFT JOIN episodes e ON e.id = j.episode_id
            LEFT JOIN feeds f ON f.id = e.feed_id
            WHERE j.status IN ('running', 'pending')
            ORDER BY CASE WHEN j.status = 'running' THEN 0 ELSE 1 END, j.id ASC
            """
        )
        active = [dict(r) for r in cur.fetchall()]
        for idx, item in enumerate(active, start=1):
            item["queue_position"] = idx

        cur.execute(
            """
            SELECT j.id, j.job_type, j.episode_id, j.model_id, j.status,
                   j.progress_percent, j.error_message, j.created_at, j.updated_at,
                   e.title AS episode_title, e.feed_id, e.status AS ep_status,
                   f.title AS feed_title
            FROM jobs j
            LEFT JOIN episodes e ON e.id = j.episode_id
            LEFT JOIN feeds f ON f.id = e.feed_id
            WHERE j.status NOT IN ('running', 'pending')
            ORDER BY j.id DESC
            LIMIT ?
            """,
            (limit_history,),
        )
        history = [dict(r) for r in cur.fetchall()]
        for item in history:
            item["queue_position"] = None

        return active + history

    def cancel_job(self, job_id: int) -> Optional[Job]:
        """Cancel a pending or running job and restore episode status appropriately."""
        job = self.get_job(job_id)
        if not job:
            return None
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE jobs SET status = 'cancelled', error_message = 'Cancelado pelo usuário', updated_at = datetime('now') WHERE id = ?",
            (job_id,),
        )
        # Restore episode status: if it already has transcripts or summaries, mark COMPLETED; otherwise AVAILABLE
        has_tx = len(self.list_episode_transcripts(job.episode_id)) > 0
        has_sum = len(self.list_episode_summaries(job.episode_id)) > 0
        target_ep_status = (
            EpisodeStatus.COMPLETED if (has_tx or has_sum) else EpisodeStatus.AVAILABLE
        )
        cur.execute(
            "UPDATE episodes SET status = ?, error_message = NULL WHERE id = ?",
            (target_ep_status.value, job.episode_id),
        )
        self.conn.commit()
        return self.get_job(job_id)

    def cancel_all_active_jobs(self) -> int:
        """Cancel all pending and running jobs in the queue."""
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM jobs WHERE status IN ('pending', 'running')")
        ids = [r["id"] for r in cur.fetchall()]
        for jid in ids:
            self.cancel_job(jid)
        return len(ids)

    def clear_finished_jobs(self) -> int:
        """Remove completed, failed, and cancelled jobs from the queue history."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM jobs WHERE status IN ('completed', 'failed', 'cancelled')")
        count = cur.rowcount
        self.conn.commit()
        return count

    def reset_all_executions(self) -> dict[str, int]:
        """Wipe all previous execution history (jobs, transcripts, summaries) and reset episodes to available."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM jobs")
        jobs_del = cur.rowcount
        cur.execute("DELETE FROM summaries")
        sum_del = cur.rowcount
        cur.execute("DELETE FROM transcripts")
        tx_del = cur.rowcount
        cur.execute(
            """
            UPDATE episodes
            SET status = 'available',
                local_audio_path = NULL,
                file_size_bytes = NULL,
                sha256 = NULL,
                error_message = NULL
            WHERE status != 'available'
               OR local_audio_path IS NOT NULL
               OR error_message IS NOT NULL
            """
        )
        ep_reset = cur.rowcount
        self.conn.commit()
        return {
            "jobs_deleted": jobs_del,
            "transcripts_deleted": tx_del,
            "summaries_deleted": sum_del,
            "episodes_reset": ep_reset,
        }
