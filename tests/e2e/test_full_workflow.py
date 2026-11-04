"""End-to-End full workflow test covering:
1. Subscription lists creation
2. RSS catalog sync (asserting 0 automatic audio downloaded)
3. Explicit user on-demand download trigger
4. Background transcription pipeline with FakeTranscriberEngine
5. In-browser Web plain text reading
6. Direct .txt file download
7. Re-transcribing existing local audio with a 2nd model
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.models import EpisodeStatus, JobStatus
from pod2bullets.transcriber.fake_engine import FakeTranscriberEngine
from pod2bullets.transcriber.registry import ModelRegistry
from pod2bullets.web.app import create_app
from pod2bullets.worker.queue import BackgroundWorker


def test_full_user_journey_e2e(tmp_path: Path, sample_wav: Path, sample_rss_content: str):
    db_file = tmp_path / "e2e.sqlite"
    init_db(db_file)
    settings.db_path = db_file
    settings.podcasts_dir = tmp_path / "podcasts"
    settings.tmp_dir = tmp_path / "tmp"

    app = create_app()
    client = TestClient(app)

    # 1. Create subscription list "Tecnologia"
    res = client.post("/lists/", data={"name": "Tecnologia", "description": "IA e Dev"})
    assert res.status_code == 200
    list_id = res.json()["id"]

    # 2. Add Podcast RSS Feed & Verify ZERO automatic audio download
    requested_urls = []
    wav_bytes = sample_wav.read_bytes()

    def mock_transport(req: httpx.Request):
        url_str = str(req.url)
        requested_urls.append(url_str)
        if "rss.xml" in url_str:
            return httpx.Response(200, text=sample_rss_content)
        elif url_str.endswith(".mp3") or url_str.endswith(".wav"):
            return httpx.Response(
                200, content=wav_bytes, headers={"content-length": str(len(wav_bytes))}
            )
        return httpx.Response(404)

    with patch(
        "httpx.Client", return_value=httpx.Client(transport=httpx.MockTransport(mock_transport))
    ):
        res = client.post(
            "/feeds/", data={"rss_url": "http://example.com/rss.xml", "list_id": list_id}
        )
        assert res.status_code == 200
        feed_id = res.json()["id"]

    # Critical check: only the RSS was fetched, NO audio download occurred!
    assert "http://example.com/rss.xml" in requested_urls
    assert not any(u.endswith(".mp3") for u in requested_urls)

    conn = get_db_connection(db_file)
    repo = Repository(conn)
    episodes = repo.list_episodes(feed_id=feed_id)
    assert len(episodes) == 2
    target_ep = episodes[0]
    assert target_ep.status == EpisodeStatus.AVAILABLE
    assert target_ep.local_audio_path is None

    # 3. User explicitly triggers "Baixar e Transcrever" for target_ep with Model 1
    res = client.post(f"/episodes/{target_ep.id}/download", data={"model_id": "model-1"})
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    # 4. Background worker processes job: downloads audio and transcribes
    mock_registry = ModelRegistry(models_dir=tmp_path / "models")
    engine1 = FakeTranscriberEngine(
        "model-1", mock_text="Transcrição Modelo 1: Olá mundo dos podcasts."
    )
    engine2 = FakeTranscriberEngine(
        "model-2", mock_text="Transcrição Modelo 2: Olá mundo dos podcasts com alta precisão."
    )
    mock_registry.get_engine = MagicMock(
        side_effect=lambda mid: engine1 if mid == "model-1" else engine2
    )

    worker = BackgroundWorker(db_path=db_file, registry=mock_registry)
    with patch(
        "httpx.Client", return_value=httpx.Client(transport=httpx.MockTransport(mock_transport))
    ):
        processed = worker.process_next_job()
        assert processed is True

    job1 = repo.get_job(job_id)
    assert job1.status == JobStatus.COMPLETED
    ep_completed = repo.get_episode(target_ep.id)
    assert ep_completed.status == EpisodeStatus.COMPLETED
    assert Path(ep_completed.local_audio_path).exists()

    # 5. Read plain text in Web
    res = client.get(f"/episodes/{target_ep.id}/transcripts/model-1/text")
    assert res.status_code == 200
    assert res.text == "Transcrição Modelo 1: Olá mundo dos podcasts."

    # 6. Download .txt file
    res = client.get(f"/episodes/{target_ep.id}/transcripts/model-1/download")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    assert res.text == "Transcrição Modelo 1: Olá mundo dos podcasts."

    # 7. Switch to Model 2: re-transcribe existing local audio without re-downloading
    repo.create_job(job_type="download_and_transcribe", episode_id=target_ep.id, model_id="model-2")
    # Reset tracking
    requested_urls.clear()
    with patch(
        "httpx.Client", return_value=httpx.Client(transport=httpx.MockTransport(mock_transport))
    ):
        processed2 = worker.process_next_job()
        assert processed2 is True

    # Check that audio was NOT downloaded again
    assert len(requested_urls) == 0

    # Verify both models transcripts coexist!
    transcripts = repo.list_episode_transcripts(target_ep.id)
    assert len(transcripts) == 2
    model_ids = [t.model_id for t in transcripts]
    assert "model-1" in model_ids
    assert "model-2" in model_ids

    # Read Model 2 transcript in web
    res2 = client.get(f"/episodes/{target_ep.id}/transcripts/model-2/text")
    assert res2.status_code == 200
    assert res2.text == "Transcrição Modelo 2: Olá mundo dos podcasts com alta precisão."

    conn.close()
