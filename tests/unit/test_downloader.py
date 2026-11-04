"""Test on-demand downloader service."""

from pathlib import Path

import httpx

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.downloader.service import DownloaderService
from pod2bullets.models import EpisodeStatus


def test_on_demand_download_success(tmp_path: Path, sample_wav: Path):
    db_file = tmp_path / "dl_test.sqlite"
    init_db(db_file)
    conn = get_db_connection(db_file)
    repo = Repository(conn)

    # Set temporary test directories
    settings.podcasts_dir = tmp_path / "podcasts"
    settings.tmp_dir = tmp_path / "tmp"

    feed = repo.create_feed("Tech Talk", "tech-talk", "http://example.com/rss")
    ep = repo.upsert_episode(
        feed_id=feed.id,
        guid="ep-wav-1",
        title="Episódio Áudio Real",
        slug="episodio-audio-real",
        audio_url="http://example.com/audio/sample.wav",
        audio_ext="wav",
    )
    assert ep.status == EpisodeStatus.AVAILABLE

    # Mock server delivering the sample WAV
    wav_bytes = sample_wav.read_bytes()

    def mock_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=wav_bytes, headers={"content-length": str(len(wav_bytes))}
        )

    client = httpx.Client(transport=httpx.MockTransport(mock_transport))
    downloader = DownloaderService(repo, client=client)

    progress_log = []

    def on_progress(p: float):
        progress_log.append(p)

    final_path = downloader.download_episode(ep.id, progress_callback=on_progress)

    assert final_path.exists()
    assert final_path.name == "audio.wav"
    assert len(progress_log) > 0
    assert 100.0 in progress_log

    # Check repository update
    updated_ep = repo.get_episode(ep.id)
    assert updated_ep.status == EpisodeStatus.DOWNLOADED
    assert updated_ep.local_audio_path == str(final_path)
    assert updated_ep.file_size_bytes == len(wav_bytes)
    assert updated_ep.sha256 is not None

    # Check episode.json metadata
    meta_json = final_path.parent / "episode.json"
    assert meta_json.exists()

    conn.close()
