"""FastAPI application factory, lifespan worker and HTML UI rendering."""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.logging_config import setup_verbose_logging
from pod2bullets.system_status import get_system_status
from pod2bullets.transcriber.registry import ModelRegistry
from pod2bullets.web.routes import episodes, feeds, lists, models
from pod2bullets.worker.queue import BackgroundWorker

setup_verbose_logging()
logger = logging.getLogger("pod2bullets.web")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_verbose_logging()
    logger.info("[STARTUP] Inicializando diretórios e banco SQLite...")
    settings.init_dirs()
    init_db()

    worker = BackgroundWorker()
    worker.start()
    app.state.worker = worker
    app.state.registry = ModelRegistry()
    logger.info(f"[STARTUP] Servidor pod2bullets pronto em http://{settings.host}:{settings.port}")

    yield

    logger.info("[SHUTDOWN] Encerrando BackgroundWorker...")
    worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="pod2bullets", lifespan=lifespan)

    @app.middleware("http")
    async def verbose_request_logger(request: Request, call_next):
        start_t = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start_t) * 1000
        path = request.url.path
        # Avoid spamming terminal with the 1.5s status poll unless an error occurs
        if path != "/system/status" or response.status_code >= 400:
            query = f"?{request.url.query}" if request.url.query else ""
            logger.info(
                f"[HTTP] {request.method} {path}{query} -> {response.status_code} ({elapsed_ms:.1f}ms)"
            )
        return response

    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # API Routes
    app.include_router(lists.router)
    app.include_router(feeds.router)
    app.include_router(models.router)
    app.include_router(episodes.router)

    @app.get("/system/status", response_class=HTMLResponse)
    def system_status_badge():
        """Return live hourglass indicator when background tasks or jobs are running."""
        status = get_system_status()
        if status["is_busy"]:
            count_badge = (
                f'<span class="busy-count">+{status["count"] - 1}</span>'
                if status["count"] > 1
                else ""
            )
            return Response(
                content=f"""
                <div class="system-status busy" title="Processando em background">
                    <span class="hourglass-icon">⏳</span>
                    <span class="busy-text">Sistema Ocupado: {status["primary"]}</span>
                    {count_badge}
                </div>
                """,
                media_type="text/html",
            )
        return Response(
            content="""
            <div class="system-status idle" title="Nenhuma tarefa pendente em segundo plano">
                <span class="idle-dot">●</span>
                <span class="idle-text">Sistema Livre</span>
            </div>
            """,
            media_type="text/html",
        )

    # Web UI Pages
    @app.get("/", response_class=HTMLResponse)
    def index_page(request: Request, list_id: int | None = None, feed_id: int | None = None):
        conn = get_db_connection()
        repo = Repository(conn)
        sub_lists = repo.list_all_lists()
        all_feeds = repo.list_feeds(list_id=list_id)
        all_models = ModelRegistry().list_models()

        selected_feed = repo.get_feed(feed_id) if feed_id is not None else None
        episodes_with_feed = []

        # Only load episodes when a specific podcast is selected in the left sidebar!
        if selected_feed is not None:
            raw_eps = repo.list_episodes(feed_id=selected_feed.id)
            for ep in raw_eps:
                d = ep.model_dump()
                d["feed_title"] = selected_feed.title
                transcripts = repo.list_episode_transcripts(ep.id)
                d["proc_time"] = transcripts[0].duration_proc_seconds if transcripts else None
                d["tx_model_id"] = (
                    transcripts[0].model_id if transcripts else settings.default_model_id
                )
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
                "selected_feed": selected_feed,
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
                "current_feed_id": ep.feed_id if ep else None,
                "models": all_models,
                "episode": ep,
                "transcripts": transcripts,
                "plain_text": plain_text,
            },
        )

    return app


app = create_app()
