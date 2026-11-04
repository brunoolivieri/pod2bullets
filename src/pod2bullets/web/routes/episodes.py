"""Episode listing, on-demand download trigger, web reading & .txt download routes."""

import logging
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.models import EpisodeStatus

logger = logging.getLogger("pod2bullets.web.episodes")

router = APIRouter(prefix="/episodes", tags=["episodes"])


@router.get("/")
def list_episodes(feed_id: int | None = None, status: str | None = None):
    conn = get_db_connection()
    repo = Repository(conn)
    ep_status = EpisodeStatus(status) if status else None
    eps = repo.list_episodes(feed_id=feed_id, status=ep_status)
    conn.close()
    return eps


@router.get("/card/{episode_id}")
def get_episode_card(episode_id: int):
    conn = get_db_connection()
    repo = Repository(conn)
    ep = repo.get_episode(episode_id)
    if not ep:
        conn.close()
        raise HTTPException(status_code=404, detail="Episódio não encontrado")

    f = repo.get_feed(ep.feed_id)
    feed_title = f.title if f else "Podcast"
    transcripts = repo.list_episode_transcripts(ep.id)
    proc_time = transcripts[0].duration_proc_seconds if transcripts else None
    tx_model_id = transcripts[0].model_id if transcripts else settings.default_model_id

    # Get active job progress if any
    cur = conn.cursor()
    cur.execute(
        "SELECT progress_percent FROM jobs WHERE episode_id = ? ORDER BY id DESC LIMIT 1",
        (episode_id,),
    )
    job_row = cur.fetchone()
    progress = job_row["progress_percent"] if job_row else 0.0
    conn.close()

    # Return partial card HTML for HTMX polling
    progress_bar = (
        f"""
    <div class="progress-bar-container">
        <div class="progress-bar-fill" style="width: {max(progress, 15)}%;"></div>
    </div>
    """
        if ep.status.value in ["queued_download", "downloading"]
        else f"""
    <div class="progress-bar-container">
        <div class="progress-bar-fill transcribe" style="width: {max(progress, 25)}%;"></div>
    </div>
    """
    )

    status_html = ""
    if ep.status.value in ["queued_download", "downloading"]:
        status_html = f"""
        <div class="status-box downloading" hx-get="/episodes/card/{ep.id}" hx-trigger="every 1s" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <div><span class="hourglass-icon">⏳</span> Baixando áudio sob demanda ({progress}%)...</div>
            {progress_bar}
        </div>
        """
    elif ep.status.value in ["queued_transcription", "transcribing"]:
        status_html = f"""
        <div class="status-box transcribing" hx-get="/episodes/card/{ep.id}" hx-trigger="every 1s" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <div><span class="hourglass-icon">⏳</span> Transcrevendo localmente com IA ({progress}%)...</div>
            {progress_bar}
        </div>
        """
    elif ep.status.value == "completed":
        proc_html = (
            f'<span class="proc-time-label" style="font-size: 0.78rem; color: #94a3b8;">'
            f"⏱️ Tempo: {proc_time}s</span>"
            if proc_time is not None
            else ""
        )
        status_html = f"""
        <div class="completed-actions">
            <span class="badge-completed">✅ Transcrito</span>
            {proc_html}
            <a href="/view/{ep.id}" class="btn-view">📖 Ler na Web</a>
            <a href="/episodes/{ep.id}/transcripts/{tx_model_id}/download" class="btn-txt">💾 Baixar .txt</a>
        </div>
        """
    elif ep.status.value == "failed":
        err_msg = (ep.error_message or "Erro desconhecido")[:120]
        status_html = f"""
        <div class="completed-actions">
            <span style="color: #ef4444; font-size: 0.8rem; font-weight: 600;" title="{err_msg}">❌ Falhou: {err_msg}</span>
            <form hx-post="/episodes/{ep.id}/download" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
                <button type="submit" class="btn-download">🔄 Tentar Novamente</button>
            </form>
        </div>
        """
    else:
        status_html = f"""
        <form hx-post="/episodes/{ep.id}/download" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <button type="submit" class="btn-download">⬇️ Baixar e Transcrever</button>
        </form>
        """

    cover_html = (
        f"""<img src="{ep.image_url}" alt="Capa" class="ep-cover-img" loading="lazy">"""
        if ep.image_url
        else """<div class="ep-cover-placeholder">🎙️</div>"""
    )

    dur_html = (
        f"<span>Duração: {ep.duration_seconds // 60} min</span>" if ep.duration_seconds else ""
    )

    return Response(
        content=f"""
        <div class="episode-card" id="ep-card-{ep.id}">
            <div class="ep-cover-col">
                {cover_html}
            </div>
            <div class="ep-info">
                <span class="ep-feed">{feed_title}</span>
                <h3 class="ep-title">{ep.title}</h3>
                <p class="ep-summary">{ep.summary[:200] if ep.summary else ""}</p>
                <div class="ep-meta">
                    <span>Publicado: {ep.published_at or "Desconhecido"}</span>
                    {dur_html}
                </div>
            </div>
            <div class="ep-actions">
                {status_html}
            </div>
        </div>
        """,
        media_type="text/html",
    )


@router.post("/{episode_id}/download")
def trigger_download_and_transcribe(
    episode_id: int,
    request: Request,
    model_id: str | None = Form(None),
):
    """User explicitly clicked to download and transcribe an episode."""
    conn = get_db_connection()
    repo = Repository(conn)
    ep = repo.get_episode(episode_id)
    if not ep:
        conn.close()
        raise HTTPException(status_code=404, detail="Episódio não encontrado")

    chosen_model = model_id or settings.default_model_id
    repo.update_episode_status(episode_id, EpisodeStatus.QUEUED_DOWNLOAD)
    job = repo.create_job(
        job_type="download_and_transcribe",
        episode_id=episode_id,
        model_id=chosen_model,
    )
    conn.close()
    logger.info(
        f"[QUEUE] Episódio #{episode_id} '{ep.title}' enfileirado para download + transcrição "
        f"(Job #{job.id}, modelo='{chosen_model}')"
    )
    if request.headers.get("hx-request"):
        return get_episode_card(episode_id)
    return {"status": "queued", "job_id": job.id, "model_id": chosen_model}


@router.get("/{episode_id}/transcripts/{model_id}/text")
def read_transcript_plain_text(episode_id: int, model_id: str):
    """Deliver plain text transcription for in-browser reading."""
    conn = get_db_connection()
    repo = Repository(conn)
    transcript = repo.get_transcript(episode_id, model_id)
    conn.close()

    if not transcript or not Path(transcript.plain_text_path).exists():
        raise HTTPException(status_code=404, detail="Transcrição não encontrada")

    text = Path(transcript.plain_text_path).read_text(encoding="utf-8")
    return Response(content=text, media_type="text/plain; charset=utf-8")


@router.get("/{episode_id}/transcripts/{model_id}/download")
def download_transcript_txt_file(episode_id: int, model_id: str):
    """Deliver .txt file attachment for direct user download."""
    conn = get_db_connection()
    repo = Repository(conn)
    ep = repo.get_episode(episode_id)
    transcript = repo.get_transcript(episode_id, model_id)
    conn.close()

    if not ep or not transcript or not Path(transcript.plain_text_path).exists():
        raise HTTPException(status_code=404, detail="Arquivo de transcrição não encontrado")

    content = Path(transcript.plain_text_path).read_bytes()
    filename = f"{ep.slug}__{model_id}.txt"

    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
