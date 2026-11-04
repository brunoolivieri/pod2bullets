"""Test Web UI HTML rendering."""

from pathlib import Path

from fastapi.testclient import TestClient

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.web.app import create_app


def test_web_ui_pages(tmp_path: Path):
    db_file = tmp_path / "ui_test.sqlite"
    init_db(db_file)
    settings.db_path = db_file

    conn = get_db_connection(db_file)
    repo = Repository(conn)
    repo.create_list("Tecnologia", "tecnologia")
    feed = repo.create_feed("Podcast Tech", "pod-tech", "http://example.com/rss")
    ep = repo.upsert_episode(
        feed_id=feed.id,
        guid="ep-1",
        title="Episódio Interface",
        slug="episodio-interface",
        audio_url="http://example.com/audio.mp3",
    )
    conn.close()

    app = create_app()
    client = TestClient(app)

    # 1. Main index page
    res = client.get("/")
    assert res.status_code == 200
    assert "pod2bullets" in res.text
    assert "Tecnologia" in res.text
    assert "Episódio Interface" in res.text
    assert "Baixar e Transcrever" in res.text

    # 2. View transcript page
    res = client.get(f"/view/{ep.id}")
    assert res.status_code == 200
    assert "Episódio Interface" in res.text
