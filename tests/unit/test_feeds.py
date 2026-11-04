"""Test feed parser, OPML, and FeedService guaranteeing ZERO automatic audio download."""

from pathlib import Path

import httpx

from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.feeds.opml import generate_opml, parse_opml
from pod2bullets.feeds.service import FeedService
from pod2bullets.models import EpisodeStatus


def test_feed_service_zero_audio_download(tmp_path: Path, sample_rss_content: str):
    db_file = tmp_path / "feeds_test.sqlite"
    init_db(db_file)
    conn = get_db_connection(db_file)
    repo = Repository(conn)

    requested_urls = []

    def mock_transport(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        requested_urls.append(url_str)
        if "rss.xml" in url_str:
            return httpx.Response(200, text=sample_rss_content)
        # Any audio download attempt should fail this test
        return httpx.Response(404, text="Not Found")

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_transport))
    service = FeedService(repo, client=mock_client)

    # 1. Create list and add subscription
    tech_list = repo.create_list("Notícias", "noticias")
    feed = service.add_subscription("http://example.com/rss.xml", list_ids=[tech_list.id])

    assert feed.title == "Podcast de Teste"
    # CRITICAL CHECK: Exactly 1 request made, to the RSS XML only. ZERO requests to audio URLs!
    assert len(requested_urls) == 1
    assert requested_urls[0] == "http://example.com/rss.xml"
    assert not any(url.endswith(".mp3") for url in requested_urls)

    # Verify episodes in database have status AVAILABLE and no local audio path
    episodes = repo.list_episodes(feed_id=feed.id)
    assert len(episodes) == 2
    for ep in episodes:
        assert ep.status == EpisodeStatus.AVAILABLE
        assert ep.local_audio_path is None

    conn.close()


def test_opml_roundtrip():
    feeds = [
        {"title": "Dev Cast", "rss_url": "https://devcast.com/rss", "category": "Tecnologia"},
        {"title": "História Geral", "rss_url": "https://historia.com/rss", "category": "História"},
        {"title": "Geral News", "rss_url": "https://geral.com/rss", "category": None},
    ]
    xml = generate_opml(feeds)
    parsed = parse_opml(xml)
    assert len(parsed) == 3
    cat_map = {item["title"]: item["category"] for item in parsed}
    assert cat_map["Dev Cast"] == "Tecnologia"
    assert cat_map["História Geral"] == "História"
    assert cat_map["Geral News"] is None
