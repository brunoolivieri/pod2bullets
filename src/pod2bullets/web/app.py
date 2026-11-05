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
from pod2bullets.llm.service import LLMService
from pod2bullets.logging_config import (
    SUPPRESSED_POLLING_PATHS,
    get_active_log_paths,
    setup_verbose_logging,
)
from pod2bullets.system_status import get_system_status
from pod2bullets.transcriber.cuda_env import ensure_cuda_libraries_loaded
from pod2bullets.transcriber.registry import ModelRegistry
from pod2bullets.web.routes import episodes, feeds, lists, llm, logs, models, queue, summaries
from pod2bullets.worker.queue import BackgroundWorker

setup_verbose_logging()
ensure_cuda_libraries_loaded()
logger = logging.getLogger("pod2bullets.web")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_verbose_logging()
    logger.info("[STARTUP] Inicializando diretórios, logs e banco SQLite...")
    settings.init_dirs()
    init_db()

    worker = BackgroundWorker()
    worker.start()
    app.state.worker = worker
    app.state.registry = ModelRegistry()
    log_paths = get_active_log_paths()
    logger.info(
        f"[STARTUP] Logs ativos -> APP: {log_paths['app'].name} | "
        f"Transcrição: {log_paths['transcricao'].name}"
    )
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
        # Suppress 200 OK logs for high-frequency polling routes (Item 12)
        if any(path.startswith(p) for p in SUPPRESSED_POLLING_PATHS) and response.status_code < 400:
            return response

        query = f"?{request.url.query}" if request.url.query else ""
        logger.info(
            f"[HTTP] {request.method} {path}{query} -> {response.status_code} ({elapsed_ms:.1f}ms)"
        )
        return response

    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.state.templates = templates

    # API Routes
    app.include_router(lists.router)
    app.include_router(feeds.router)
    app.include_router(models.router)
    app.include_router(episodes.router)
    app.include_router(llm.router)
    app.include_router(logs.router)
    app.include_router(queue.router)
    app.include_router(summaries.router)

    @app.get("/system/status", response_class=HTMLResponse)
    def system_status_badge():
        """Return live hourglass indicator ONLY when busy; return empty when idle so nothing blinks (Item 1)."""
        status = get_system_status()
        if status["is_busy"]:
            count_badge = (
                f'<span class="busy-count">+{status["count"] - 1} na fila</span>'
                if status["count"] > 1
                else ""
            )
            return Response(
                content=f"""
                <a href="/queue/manage" class="system-status busy" style="text-decoration: none;" title="Clique para ver a fila e cancelar itens">
                    <span class="hourglass-icon">⏳</span>
                    <span class="busy-text">Sistema Ocupado: {status["primary"]}</span>
                    {count_badge}
                </a>
                """,
                media_type="text/html",
            )
        # Return empty string when idle so there is zero visual blinking on polling
        return Response(content="", media_type="text/html")

    # Web UI Pages
    @app.get("/", response_class=HTMLResponse)
    def index_page(request: Request, list_id: int | None = None, feed_id: int | None = None):
        conn = get_db_connection()
        repo = Repository(conn)
        sub_lists = repo.list_all_lists()
        all_feeds = repo.list_feeds(list_id=list_id)
        all_models = ModelRegistry().list_models()
        llm_cfg = LLMService(repo).get_config()

        selected_feed = repo.get_feed(feed_id) if feed_id is not None else None
        episodes_with_feed = []

        # Only load episodes when a specific podcast is selected in the left sidebar!
        if selected_feed is not None:
            raw_eps = repo.list_episodes(feed_id=selected_feed.id)
            for ep in raw_eps:
                d = ep.model_dump()
                d["feed_title"] = selected_feed.title
                transcripts = repo.list_episode_transcripts(ep.id)
                summaries = repo.list_episode_summaries(ep.id)
                d["has_transcript"] = len(transcripts) > 0
                d["has_summary"] = len(summaries) > 0
                d["summaries"] = [s.model_dump() for s in summaries]
                d["latest_summary_id"] = summaries[0].id if summaries else None
                d["proc_time"] = (
                    transcripts[0].duration_proc_seconds
                    if transcripts
                    else (summaries[0].duration_proc_seconds if summaries else None)
                )
                d["tx_model_id"] = (
                    transcripts[0].model_id if transcripts else settings.default_model_id
                )
                active_job = repo.get_active_job_for_episode(ep.id)
                d["job_id"] = active_job.id if active_job else 0
                d["job_status"] = active_job.status.value if active_job else ""
                d["job_type"] = active_job.job_type.value if active_job else ""
                d["job_model"] = active_job.model_id if active_job else ""
                d["progress"] = active_job.progress_percent if active_job else 0.0
                d["q_pos"] = repo.get_queue_position(active_job.id) if active_job else 1
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
                "llm_cfg": llm_cfg,
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

    @app.get("/queue/manage", response_class=HTMLResponse)
    def manage_queue_page(request: Request):
        conn = get_db_connection()
        repo = Repository(conn)
        sub_lists = repo.list_all_lists()
        all_feeds = repo.list_feeds()
        all_models = ModelRegistry().list_models()
        conn.close()

        return templates.TemplateResponse(
            request=request,
            name="queue.html",
            context={
                "lists": sub_lists,
                "all_feeds": all_feeds,
                "models": all_models,
                "queue_panel_html": queue._render_queue_panel_html(),
            },
        )

    @app.get("/llm/settings", response_class=HTMLResponse)
    def llm_settings_page(request: Request):
        conn = get_db_connection()
        repo = Repository(conn)
        sub_lists = repo.list_all_lists()
        all_feeds = repo.list_feeds()
        all_models = ModelRegistry().list_models()
        llm_cfg = LLMService(repo).get_config()
        conn.close()

        return templates.TemplateResponse(
            request=request,
            name="llm_settings.html",
            context={
                "lists": sub_lists,
                "all_feeds": all_feeds,
                "models": all_models,
                "llm_cfg": llm_cfg,
            },
        )

    @app.get("/logs/viewer", response_class=HTMLResponse)
    def log_viewer_page(request: Request):
        log_paths = get_active_log_paths()
        return templates.TemplateResponse(
            request=request,
            name="log_viewer.html",
            context={
                "app_log_name": log_paths["app"].name,
                "tx_log_name": log_paths["transcricao"].name,
            },
        )

    @app.get("/view/{episode_id}", response_class=HTMLResponse)
    def view_transcript_page(request: Request, episode_id: int, model_id: str | None = None):
        conn = get_db_connection()
        repo = Repository(conn)
        ep = repo.get_episode(episode_id)
        transcripts = repo.list_episode_transcripts(episode_id)
        summaries = repo.list_episode_summaries(episode_id)
        llm_cfg = LLMService(repo).get_config()
        sub_lists = repo.list_all_lists()
        all_feeds = repo.list_feeds()
        all_models = ModelRegistry().list_models()

        active_transcript = None
        if transcripts:
            if model_id:
                active_transcript = next((t for t in transcripts if t.model_id == model_id), None)
            if not active_transcript:
                active_transcript = transcripts[0]

        plain_text = ""
        if active_transcript:
            t_path = Path(active_transcript.plain_text_path)
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
                "active_transcript": active_transcript,
                "plain_text": plain_text,
                "summaries": summaries,
                "llm_cfg": llm_cfg,
            },
        )

    return app


app = create_app()
