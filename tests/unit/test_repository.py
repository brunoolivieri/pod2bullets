"""Test database repository operations."""

from pathlib import Path

from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.models import EpisodeStatus, JobStatus


def test_repository_flow(tmp_path: Path):
    db_file = tmp_path / "test.sqlite"
    init_db(db_file)
    conn = get_db_connection(db_file)
    repo = Repository(conn)

    # 1. Lists
    tech_list = repo.create_list("Tecnologia", "tecnologia", "Podcasts sobre dev e IA")
    assert tech_list.id is not None
    assert tech_list.slug == "tecnologia"

    all_lists = repo.list_all_lists()
    assert len(all_lists) == 1

    # 2. Feeds
    feed = repo.create_feed(
        title="AI News",
        slug="ai-news",
        rss_url="https://example.com/rss.xml",
        site_url="https://example.com",
    )
    assert feed.id is not None
    repo.add_feed_to_list(feed.id, tech_list.id)

    feeds_in_list = repo.list_feeds(list_id=tech_list.id)
    assert len(feeds_in_list) == 1
    assert feeds_in_list[0].slug == "ai-news"

    # 3. Episodes
    ep = repo.upsert_episode(
        feed_id=feed.id,
        guid="guid-001",
        title="Episódio 1",
        slug="episodio-1",
        audio_url="https://example.com/audio/ep1.mp3",
    )
    assert ep.id is not None
    assert ep.status == EpisodeStatus.AVAILABLE

    # 4. Transcripts
    transcript = repo.record_transcript(
        episode_id=ep.id,
        model_id="whisper-large-v3-turbo",
        engine_name="faster-whisper",
        plain_text_path="/path/to/transcript.txt",
        char_count=500,
        word_count=80,
    )
    assert transcript.id is not None
    assert transcript.word_count == 80

    # 5. Jobs
    job = repo.create_job(
        job_type="download_and_transcribe", episode_id=ep.id, model_id="whisper-large-v3-turbo"
    )
    assert job.status == JobStatus.PENDING

    next_job = repo.get_next_pending_job()
    assert next_job is not None
    assert next_job.id == job.id

    repo.update_job_status(job.id, status=JobStatus.COMPLETED, progress_percent=100.0)
    updated_job = repo.get_job(job.id)
    assert updated_job.status == JobStatus.COMPLETED

    conn.close()
