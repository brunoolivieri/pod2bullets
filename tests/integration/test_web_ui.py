"""Test Web UI HTML rendering, podcast filtering, and system busy indicator."""

from pathlib import Path

from fastapi.testclient import TestClient

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.system_status import activity_tracker
from pod2bullets.web.app import create_app


def test_web_ui_pages(tmp_path: Path):
    db_file = tmp_path / "ui_test.sqlite"
    init_db(db_file)
    settings.db_path = db_file

    conn = get_db_connection(db_file)
    repo = Repository(conn)
    repo.create_list("Tecnologia", "tecnologia")
    feed1 = repo.create_feed("Podcast Tech", "pod-tech", "http://example.com/rss")
    feed2 = repo.create_feed("Podcast Ciência", "pod-ciencia", "http://example.com/rss2")
    ep1 = repo.upsert_episode(
        feed_id=feed1.id,
        guid="ep-1",
        title="Episódio Interface Tech",
        slug="episodio-interface-tech",
        audio_url="http://example.com/audio1.mp3",
    )
    repo.upsert_episode(
        feed_id=feed2.id,
        guid="ep-2",
        title="Episódio Exclusivo Ciência",
        slug="episodio-exclusivo-ciencia",
        audio_url="http://example.com/audio2.mp3",
    )
    conn.close()

    app = create_app()
    client = TestClient(app)

    # 1. Main index page without feed_id: must NOT show all episodes mixed together
    res = client.get("/")
    assert res.status_code == 200
    assert "pod2bullets" in res.text
    assert "Podcast Tech" in res.text
    assert "Podcast Ciência" in res.text
    assert "Selecione um Podcast no Menu à Esquerda" in res.text
    assert "Episódio Interface Tech" not in res.text
    assert "Episódio Exclusivo Ciência" not in res.text

    # 2. Selecting a specific podcast in the left menu lists ONLY its episodes
    res_feed1 = client.get(f"/?feed_id={feed1.id}")
    assert res_feed1.status_code == 200
    assert "Episódio Interface Tech" in res_feed1.text
    assert "Baixar e Transcrever" in res_feed1.text
    assert "Episódio Exclusivo Ciência" not in res_feed1.text

    # 3. System status badge (idle vs busy hourglass)
    res_idle = client.get("/system/status")
    assert res_idle.status_code == 200
    assert "Sistema Livre" in res_idle.text

    activity_tracker.start("test_task", "Transcrevendo episódio teste")
    try:
        res_busy = client.get("/system/status")
        assert res_busy.status_code == 200
        assert "⏳" in res_busy.text
        assert "Sistema Ocupado" in res_busy.text
        assert "Transcrevendo episódio teste" in res_busy.text
    finally:
        activity_tracker.finish("test_task")

    # 4. Models & Feeds management pages
    assert client.get("/models/manage").status_code == 200
    assert client.get("/feeds/manage").status_code == 200

    # 5. View transcript page
    res_view = client.get(f"/view/{ep1.id}")
    assert res_view.status_code == 200
    assert "Episódio Interface Tech" in res_view.text
