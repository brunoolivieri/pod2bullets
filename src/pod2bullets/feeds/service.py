"""Feed synchronization service — ZERO automatic audio download."""

import logging

import httpx

from pod2bullets.db.repository import Repository
from pod2bullets.feeds.parser import parse_podcast_feed
from pod2bullets.models import PodcastFeed
from pod2bullets.naming import slugify
from pod2bullets.system_status import activity_tracker

logger = logging.getLogger("pod2bullets.feeds")


class FeedService:
    def __init__(self, repo: Repository, client: httpx.Client | None = None):
        self.repo = repo
        self.client = client or httpx.Client(timeout=15.0, follow_redirects=True)

    def add_subscription(
        self,
        rss_url: str,
        list_ids: list[int] | None = None,
    ) -> PodcastFeed:
        """Add a podcast subscription and sync its episode catalog (metadata only!)."""
        task_id = f"add_feed:{rss_url}"
        activity_tracker.start(task_id, f"Sincronizando novo feed RSS: {rss_url}")
        logger.info(f"[RSS] Buscando XML de novo podcast: {rss_url} (zero download de áudio)")
        try:
            resp = self.client.get(rss_url)
            resp.raise_for_status()
            feed_data = parse_podcast_feed(resp.text)

            slug = slugify(feed_data["title"])
            existing = self.repo.get_feed_by_rss(rss_url)
            if existing:
                feed = existing
                logger.info(f"[RSS] Podcast já existente: '{feed.title}' (ID={feed.id})")
            else:
                feed = self.repo.create_feed(
                    title=feed_data["title"],
                    slug=slug,
                    rss_url=rss_url,
                    site_url=feed_data.get("site_url"),
                    description=feed_data.get("description"),
                    image_url=feed_data.get("image_url"),
                )
                logger.info(f"[RSS] Podcast cadastrado: '{feed.title}' (ID={feed.id})")

            if list_ids:
                for lid in list_ids:
                    self.repo.add_feed_to_list(feed.id, lid)

            ep_count = len(feed_data["episodes"])
            logger.info(
                f"[RSS] Indexando {ep_count} episódios de '{feed.title}' no SQLite "
                "(apenas metadados)..."
            )
            for ep_data in feed_data["episodes"]:
                ep_slug = slugify(ep_data["title"])
                self.repo.upsert_episode(
                    feed_id=feed.id,
                    guid=ep_data["guid"],
                    title=ep_data["title"],
                    slug=ep_slug,
                    audio_url=ep_data["audio_url"],
                    audio_ext=ep_data["audio_ext"],
                    image_url=ep_data.get("image_url"),
                    published_at=ep_data.get("published_at"),
                    duration_seconds=ep_data.get("duration_seconds"),
                    summary=ep_data.get("summary"),
                )

            logger.info(f"[RSS] Concluído: '{feed.title}' ({ep_count} episódios disponíveis).")
            return feed
        finally:
            activity_tracker.finish(task_id)

    def sync_feed(self, feed_id: int) -> int:
        """Fetch latest XML and add new episodes (zero audio download)."""
        feed = self.repo.get_feed(feed_id)
        if not feed:
            raise ValueError(f"Feed {feed_id} não encontrado")

        task_id = f"sync_feed:{feed_id}"
        activity_tracker.start(task_id, f"Atualizando feed '{feed.title}'")
        logger.info(f"[RSS] Sincronizando feed #{feed.id} '{feed.title}' ({feed.rss_url})...")
        try:
            resp = self.client.get(feed.rss_url)
            resp.raise_for_status()
            feed_data = parse_podcast_feed(resp.text)

            count = 0
            for ep_data in feed_data["episodes"]:
                ep_slug = slugify(ep_data["title"])
                self.repo.upsert_episode(
                    feed_id=feed.id,
                    guid=ep_data["guid"],
                    title=ep_data["title"],
                    slug=ep_slug,
                    audio_url=ep_data["audio_url"],
                    audio_ext=ep_data["audio_ext"],
                    image_url=ep_data.get("image_url"),
                    published_at=ep_data.get("published_at"),
                    duration_seconds=ep_data.get("duration_seconds"),
                    summary=ep_data.get("summary"),
                )
                count += 1
            logger.info(
                f"[RSS] Feed '{feed.title}' atualizado com sucesso ({count} episódios no XML)."
            )
            return count
        finally:
            activity_tracker.finish(task_id)
