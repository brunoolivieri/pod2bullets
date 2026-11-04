"""FastAPI application factory, lifespan worker and HTML UI rendering."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.transcriber.registry import ModelRegistry
from pod2bullets.web.routes import episodes, feeds, lists, models
from pod2bullets.worker.queue import BackgroundWorker

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.init_dirs()
    init_db()

    worker = BackgroundWorker()
    worker.start()
    app.state.worker = worker
    app.state.registry = ModelRegistry()

    yield

    worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="pod2bullets", lifespan=lifespan)

    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # API Routes
    app.include_router(lists.router)
    app.include_router(feeds.router)
    app.include_router(models.router)
    app.include_router(episodes.router)

    # Web UI Pages
    @app.get("/", response_class=HTMLResponse)
    def index_page(request: Request, list_id: int | None = None, feed_id: int | None = None):
        conn = get_db_connection()
        repo = Repository(conn)
        sub_lists = repo.list_all_lists()
        all_feeds = repo.list_feeds(list_id=list_id)
        all_models = ModelRegistry().list_models()

        # Get all episodes ordered chronologically (no 100 limit!)
        raw_eps = repo.list_episodes(feed_id=feed_id)
        episodes_with_feed = []
        for ep in raw_eps:
            f = repo.get_feed(ep.feed_id)
            d = ep.model_dump()
            d["feed_title"] = f.title if f else "Podcast"
            # Get transcript duration if completed
            transcripts = repo.list_episode_transcripts(ep.id)
            d["proc_time"] = transcripts[0].duration_proc_seconds if transcripts else None
            episodes_with_feed.append(d)

        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "lists": sub_lists,
                "all_feeds": all_feeds,
                "current_list_id": list_id,
                "current_feed_id": feed_id,
                "models": all_models,
                "episodes": episodes_with_feed,
            },
        )

    @app.get("/feeds/manage", response_class=HTMLResponse)
    def manage_feeds_page(request: Request):
        conn = get_db_connection()
        repo = Repository(conn)
        sub_lists = repo.list_all_lists()
        all_feeds = repo.list_feeds()
        all_models = ModelRegistry().list_models()
        conn.close()

        return templates.TemplateResponse(
            request=request,
            name="feeds_manage.html",
            context={
                "lists": sub_lists,
                "all_feeds": all_feeds,
                "models": all_models,
            },
        )

    @app.get("/models/manage", response_class=HTMLResponse)
    def manage_models_page(request: Request):
        conn = get_db_connection()
        repo = Repository(conn)
        sub_lists = repo.list_all_lists()
        all_feeds = repo.list_feeds()
        all_models = ModelRegistry().list_models()
        conn.close()

        return templates.TemplateResponse(
            request=request,
            name="models.html",
            context={
                "lists": sub_lists,
                "all_feeds": all_feeds,
                "models": all_models,
            },
        )

    @app.get("/view/{episode_id}", response_class=HTMLResponse)
    def view_transcript_page(request: Request, episode_id: int):
        conn = get_db_connection()
        repo = Repository(conn)
        ep = repo.get_episode(episode_id)
        transcripts = repo.list_episode_transcripts(episode_id)
        sub_lists = repo.list_all_lists()
        all_feeds = repo.list_feeds()
        all_models = ModelRegistry().list_models()

        plain_text = ""
        if transcripts:
            t_path = Path(transcripts[0].plain_text_path)
            if t_path.exists():
                plain_text = t_path.read_text(encoding="utf-8")

        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="view_transcript.html",
            context={
                "lists": sub_lists,
                "all_feeds": all_feeds,
                "models": all_models,
                "episode": ep,
                "transcripts": transcripts,
                "plain_text": plain_text,
            },
        )

    return app


app = create_app()
