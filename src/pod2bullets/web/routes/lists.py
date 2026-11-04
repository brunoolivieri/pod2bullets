"""Subscription lists routes (Categories & OPML)."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.feeds.opml import generate_opml, parse_opml
from pod2bullets.feeds.service import FeedService
from pod2bullets.naming import slugify

router = APIRouter(prefix="/lists", tags=["lists"])


@router.get("/")
def get_lists():
    conn = get_db_connection()
    repo = Repository(conn)
    lists = repo.list_all_lists()
    conn.close()
    return lists


@router.post("/")
def create_list(name: str = Form(...), description: str = Form(None)):
    conn = get_db_connection()
    repo = Repository(conn)
    slug = slugify(name)
    sub_list = repo.create_list(name=name, slug=slug, description=description)
    conn.close()
    return sub_list


@router.delete("/{list_id}")
def delete_list(list_id: int):
    conn = get_db_connection()
    repo = Repository(conn)
    deleted = repo.delete_list(list_id)
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Lista não encontrada")
    return {"ok": True}


@router.get("/opml/export")
def export_opml():
    conn = get_db_connection()
    repo = Repository(conn)
    all_feeds = repo.list_feeds()
    items = []
    for f in all_feeds:
        lists = repo.get_feed_lists(f.id)
        cat = lists[0].name if lists else None
        items.append(
            {
                "title": f.title,
                "rss_url": f.rss_url,
                "site_url": f.site_url,
                "category": cat,
            }
        )
    conn.close()
    xml = generate_opml(items)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="pod2bullets_subscriptions.opml"'},
    )


@router.post("/opml/import")
async def import_opml(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8")
    items = parse_opml(content)
    conn = get_db_connection()
    repo = Repository(conn)
    service = FeedService(repo)

    imported = 0
    for it in items:
        cat_id = None
        if it.get("category"):
            c_slug = slugify(it["category"])
            existing_cat = repo.get_list_by_slug(c_slug)
            if not existing_cat:
                existing_cat = repo.create_list(it["category"], c_slug)
            cat_id = existing_cat.id

        list_ids = [cat_id] if cat_id else []
        try:
            service.add_subscription(it["rss_url"], list_ids=list_ids)
            imported += 1
        except Exception:
            pass
    conn.close()
    return {"imported": imported}
