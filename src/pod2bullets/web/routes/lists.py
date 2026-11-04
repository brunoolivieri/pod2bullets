"""Subscription lists routes (Categories & OPML)."""

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.feeds.opml import generate_opml, parse_opml
from pod2bullets.feeds.service import FeedService
from pod2bullets.naming import slugify
from pod2bullets.system_status import activity_tracker

logger = logging.getLogger("pod2bullets.web.lists")

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
    logger.info(f"[LISTS] Nova lista criada: '{name}' (ID={sub_list.id})")
    return sub_list


@router.delete("/{list_id}")
def delete_list(list_id: int):
    conn = get_db_connection()
    repo = Repository(conn)
    deleted = repo.delete_list(list_id)
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Lista não encontrada")
    logger.info(f"[LISTS] Lista #{list_id} removida.")
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
    logger.info(f"[OPML] Exportando OPML com {len(items)} feeds.")
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="pod2bullets_subscriptions.opml"'},
    )


@router.post("/opml/import")
async def import_opml(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8")
    items = parse_opml(content)
    logger.info(f"[OPML] Iniciando importação de arquivo OPML ({len(items)} feeds encontrados)...")
    task_id = "opml_import"
    activity_tracker.start(task_id, f"Importando OPML ({len(items)} podcasts)")

    conn = get_db_connection()
    repo = Repository(conn)
    service = FeedService(repo)

    imported = 0
    try:
        for idx, it in enumerate(items, start=1):
            activity_tracker.update(
                task_id,
                description=f"Importando OPML ({idx}/{len(items)}): {it.get('title') or it['rss_url']}",
            )
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
            except Exception as e:
                logger.warning(f"[OPML] Falha ao importar feed {it.get('rss_url')}: {e}")
    finally:
        activity_tracker.finish(task_id)
        conn.close()

    logger.info(f"[OPML] Importação concluída: {imported}/{len(items)} podcasts importados.")
    return {"imported": imported}
