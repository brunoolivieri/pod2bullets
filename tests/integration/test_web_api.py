"""Test FastAPI web API routes."""

from pathlib import Path

from fastapi.testclient import TestClient

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.models import EpisodeStatus
from pod2bullets.web.app import create_app


def test_web_api_routes(tmp_path: Path):
    db_file = tmp_path / "api_test.sqlite"
    init_db(db_file)
    settings.db_path = db_file

    app = create_app()
    client = TestClient(app)

    # 1. Lists routes
    res = client.post("/lists/", data={"name": "Tecnologia", "description": "Dev & AI"})
    assert res.status_code == 200
    list_data = res.json()
    assert list_data["slug"] == "tecnologia"

    res = client.get("/lists/")
    assert len(res.json()) == 1

    # 2. Models routes
    res = client.get("/models/")
    assert res.status_code == 200
    models = res.json()
    assert any(m["id"] == "whisper-large-v3-turbo" for m in models)

    # 3. Create dummy episode & transcript in DB to test web reading & download
    conn = get_db_connection(db_file)
    repo = Repository(conn)
    feed = repo.create_feed("Podcast Web", "pod-web", "http://example.com/rss")
    ep = repo.upsert_episode(
        feed_id=feed.id,
        guid="ep-web-1",
        title="Episódio Web",
        slug="episodio-web",
        audio_url="http://example.com/audio.mp3",
    )
    # Write fake transcript file
    txt_file = tmp_path / "transcripts" / "episodio-web__whisper-large-v3-turbo.txt"
    txt_file.parent.mkdir(parents=True, exist_ok=True)
    txt_file.write_text("Conteúdo de transcrição em texto puro para a Web.", encoding="utf-8")

    repo.record_transcript(
        episode_id=ep.id,
        model_id="whisper-large-v3-turbo",
        engine_name="faster-whisper",
        plain_text_path=str(txt_file),
    )
    repo.update_episode_status(ep.id, EpisodeStatus.COMPLETED)
    conn.close()

    # 4. Trigger download endpoint
    res = client.post(f"/episodes/{ep.id}/download", data={"model_id": "whisper-large-v3-turbo"})
    assert res.status_code == 200
    assert res.json()["status"] == "queued"

    # 5. Read text in web route
    res = client.get(f"/episodes/{ep.id}/transcripts/whisper-large-v3-turbo/text")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    assert res.text == "Conteúdo de transcrição em texto puro para a Web."

    # 6. Download .txt file route
    res = client.get(f"/episodes/{ep.id}/transcripts/whisper-large-v3-turbo/download")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    assert "episodio-web__whisper-large-v3-turbo.txt" in res.headers["content-disposition"]
    assert res.text == "Conteúdo de transcrição em texto puro para a Web."
