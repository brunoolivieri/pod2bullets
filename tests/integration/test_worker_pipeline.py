"""Integration test for the BackgroundWorker pipeline (Download -> Transcription -> .txt)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.models import EpisodeStatus, JobStatus
from pod2bullets.transcriber.fake_engine import FakeTranscriberEngine
from pod2bullets.transcriber.registry import ModelRegistry
from pod2bullets.worker.queue import BackgroundWorker


def test_worker_pipeline_e2e(tmp_path: Path, sample_wav: Path):
    db_file = tmp_path / "worker_test.sqlite"
    init_db(db_file)
    conn = get_db_connection(db_file)
    repo = Repository(conn)

    settings.podcasts_dir = tmp_path / "podcasts"
    settings.tmp_dir = tmp_path / "tmp"

    feed = repo.create_feed("Ciência Todo Dia", "ciencia-todo-dia", "http://example.com/rss")
    ep = repo.upsert_episode(
        feed_id=feed.id,
        guid="ep-ciencia-1",
        title="Buracos Negros Explicados",
        slug="buracos-negros-explicados",
        audio_url="http://example.com/audio/sample.wav",
        audio_ext="wav",
    )
    assert ep.status == EpisodeStatus.AVAILABLE

    # Registry with FakeTranscriberEngine
    mock_registry = ModelRegistry(models_dir=tmp_path / "models")
    fake_engine = FakeTranscriberEngine(
        "fake-engine", mock_text="O horizonte de eventos é fascinante."
    )
    mock_registry.get_engine = MagicMock(return_value=fake_engine)

    worker = BackgroundWorker(db_path=db_file, registry=mock_registry)

    # 1. User clicks "Baixar e Transcrever" -> Job is queued
    job = repo.create_job(
        job_type="download_and_transcribe", episode_id=ep.id, model_id="fake-engine"
    )
    assert job.status == JobStatus.PENDING

    # Mock audio HTTP streaming
    wav_bytes = sample_wav.read_bytes()

    def mock_transport(req: httpx.Request):
        return httpx.Response(
            200, content=wav_bytes, headers={"content-length": str(len(wav_bytes))}
        )

    with patch(
        "httpx.Client", return_value=httpx.Client(transport=httpx.MockTransport(mock_transport))
    ):
        processed = worker.process_next_job()
        assert processed is True

    # 2. Verify results
    updated_job = repo.get_job(job.id)
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.progress_percent == 100.0

    updated_ep = repo.get_episode(ep.id)
    assert updated_ep.status == EpisodeStatus.COMPLETED
    assert Path(updated_ep.local_audio_path).exists()

    # 3. Verify .txt file created and readable
    transcripts = repo.list_episode_transcripts(ep.id)
    assert len(transcripts) == 1
    t = transcripts[0]
    assert t.model_id == "fake-engine"
    assert Path(t.plain_text_path).exists()
    assert (
        Path(t.plain_text_path).read_text(encoding="utf-8")
        == "O horizonte de eventos é fascinante."
    )
    assert Path(t.meta_json_path).exists()

    conn.close()
