"""Feeds management and sync routes (ZERO audio download)."""

from fastapi import APIRouter, Form, HTTPException

from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.feeds.service import FeedService

router = APIRouter(prefix="/feeds", tags=["feeds"])


@router.get("/")
def get_feeds(list_id: int | None = None):
    conn = get_db_connection()
    repo = Repository(conn)
    feeds = repo.list_feeds(list_id=list_id)
    conn.close()
    return feeds


@router.post("/")
def add_feed(rss_url: str = Form(...), list_id: int | None = Form(None)):
    conn = get_db_connection()
    repo = Repository(conn)
    service = FeedService(repo)
    list_ids = [list_id] if list_id else []
    try:
        feed = service.add_subscription(rss_url, list_ids=list_ids)
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Erro ao adicionar podcast: {e}")
    conn.close()
    return feed


@router.post("/{feed_id}/sync")
def sync_feed(feed_id: int):
    """Sync RSS metadata ONLY (Zero audio downloaded)."""
    conn = get_db_connection()
    repo = Repository(conn)
    service = FeedService(repo)
    try:
        count = service.sync_feed(feed_id)
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Erro ao sincronizar: {e}")
    conn.close()
    return {"synced_episodes": count}


@router.delete("/{feed_id}")
def delete_feed(feed_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Podcast não encontrado")
    return {"ok": True}
