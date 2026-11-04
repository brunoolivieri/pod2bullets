"""Episode listing, multi-item queue trigger, direct LLM audio summarization, web reading & .txt export."""

import logging
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.llm.service import LLM_PROVIDERS, LLMService
from pod2bullets.models import EpisodeStatus
from pod2bullets.transcriber.registry import ModelRegistry

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


def _build_llm_select_options(llm_cfg: dict) -> str:
    """Build <option> tags for direct LLM summarization, remembering the last selected provider."""
    last_prov = llm_cfg["last_direct_provider"]
    registered = llm_cfg["registered_providers"]
    # If user has registered APIs, list registered ones first, then others
    options = []
    if registered:
        for p in registered:
            sel = "selected" if p["id"] == last_prov else ""
            options.append(
                f'<option value="{p["id"]}" {sel}>🤖 {p["name"]} ({p["model"]}) ✅</option>'
            )
        for pid, p in llm_cfg["providers"].items():
            if not p["has_key"]:
                sel = "selected" if pid == last_prov else ""
                options.append(f'<option value="{pid}" {sel}>{p["name"]} (Sem chave ⚠️)</option>')
    else:
        for pid, p in llm_cfg["providers"].items():
            sel = "selected" if pid == last_prov else ""
            options.append(f'<option value="{pid}" {sel}>{p["name"]} (Cadastrar chave ⚙️)</option>')
    return "".join(options)


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
    summaries = repo.list_episode_summaries(ep.id)
    llm_cfg = LLMService(repo).get_config()

    proc_time = (
        transcripts[0].duration_proc_seconds
        if transcripts
        else (summaries[0].duration_proc_seconds if summaries else None)
    )
    tx_model_id = transcripts[0].model_id if transcripts else settings.default_model_id
    latest_summary = summaries[0] if summaries else None

    active_job = repo.get_active_job_for_episode(episode_id)
    q_pos = repo.get_queue_position(active_job.id) if active_job else 1

    cur = conn.cursor()
    cur.execute(
        "SELECT id, job_type, progress_percent, status, model_id FROM jobs WHERE episode_id = ? ORDER BY id DESC LIMIT 1",
        (episode_id,),
    )
    job_row = cur.fetchone()
    job_id = int(job_row["id"]) if job_row else 0
    progress = float(job_row["progress_percent"]) if job_row else 0.0
    job_status = job_row["status"] if job_row else ""
    job_type = job_row["job_type"] if job_row else ""
    job_model = (job_row["model_id"] if job_row else None) or settings.default_model_id
    conn.close()

    cancel_inline_btn = (
        f'<button type="button" class="btn-cancel-inline" '
        f'hx-post="/queue/{job_id}/cancel?from_card=1" '
        f'hx-target="#ep-card-{ep.id}" hx-swap="outerHTML" '
        f'title="Cancelar este processamento">✖ Cancelar</button>'
        if job_id
        else ""
    )

    all_models = ModelRegistry().list_models()
    model_options_html = "".join(
        f'<option value="{m.id}" {"selected" if m.is_default else ""}>{m.name} {"(Instalado ✅)" if m.is_installed else "(Auto-instalar ⬇️)"}</option>'
        for m in all_models
    )
    llm_options_html = _build_llm_select_options(llm_cfg)

    dual_action_forms = f"""
    <div class="dual-actions-grid">
        <form hx-post="/episodes/{ep.id}/download" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML" class="action-box">
            <label class="action-box-label">🎙️ Transcrição Local (ASR)</label>
            <select name="model_id" class="select-inline-model">
                {model_options_html}
            </select>
            <button type="submit" class="btn-download">⬇️ Baixar e Transcrever</button>
        </form>

        <form hx-post="/episodes/{ep.id}/summarize-direct" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML" class="action-box action-box-llm">
            <label class="action-box-label">🤖 Resumir Direto via LLM</label>
            <select name="llm_provider" class="select-inline-model">
                {llm_options_html}
            </select>
            <button type="submit" class="btn-llm-direct">✨ Baixar e Resumir (LLM)</button>
        </form>
    </div>
    """

    status_html = ""
    if ep.status.value == "queued_download" and job_status == "pending":
        mode_lbl = (
            "Resumo Direto LLM" if job_type == "download_and_summarize_llm" else "Transcrição"
        )
        status_html = f"""
        <div class="status-box queued" hx-get="/episodes/card/{ep.id}" hx-trigger="every 1.5s" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                <span>🕒 Na fila (#{q_pos}) [{mode_lbl}] — <code>{job_model}</code></span>
                {cancel_inline_btn}
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: 8%; opacity: 0.6;"></div>
            </div>
        </div>
        """
    elif ep.status.value in ["queued_download", "downloading"]:
        status_html = f"""
        <div class="status-box downloading" hx-get="/episodes/card/{ep.id}" hx-trigger="every 1.2s" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                <span><span class="hourglass-icon">⏳</span> Baixando/Preparando ({progress:.0f}%)...</span>
                {cancel_inline_btn}
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: {max(progress, 12)}%;"></div>
            </div>
        </div>
        """
    elif ep.status.value == "summarizing_llm":
        prov_label = LLM_PROVIDERS.get(job_model, {}).get("name", job_model)
        status_html = f"""
        <div class="status-box transcribing" hx-get="/episodes/card/{ep.id}" hx-trigger="every 1.2s" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                <span><span class="hourglass-icon">⏳</span> Resumindo via {prov_label} ({progress:.0f}%)...</span>
                {cancel_inline_btn}
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill transcribe" style="width: {max(progress, 55)}%;"></div>
            </div>
        </div>
        """
    elif ep.status.value in ["queued_transcription", "transcribing"]:
        status_html = f"""
        <div class="status-box transcribing" hx-get="/episodes/card/{ep.id}" hx-trigger="every 1.2s" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                <span><span class="hourglass-icon">⏳</span> Transcrevendo com {job_model} ({progress:.0f}%)...</span>
                {cancel_inline_btn}
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill transcribe" style="width: {max(progress, 50)}%;"></div>
            </div>
        </div>
        """
    elif ep.status.value == "completed":
        proc_html = (
            f'<span class="proc-time-label" style="font-size: 0.78rem; color: #94a3b8;">'
            f"⏱️ Tempo: {proc_time}s | 🧹 MP3 removido</span>"
            if proc_time is not None
            else '<span class="proc-time-label" style="font-size: 0.78rem; color: #94a3b8;">🧹 MP3 removido</span>'
        )
        tx_buttons = ""
        if transcripts:
            tx_buttons = f"""
                <a href="/view/{ep.id}" class="btn-view">📖 Ler na Íntegra</a>
                <a href="/episodes/{ep.id}/transcripts/{tx_model_id}/download" class="btn-txt">💾 Exportar .TXT</a>
            """
        sum_buttons = ""
        if latest_summary:
            sum_buttons = f"""
                <a href="/view/{ep.id}#resumo-ia" class="btn-copy">📑 Ler Resumo Online</a>
                <a href="/llm/summaries/{latest_summary.id}/download" class="btn-txt" style="background: #0d9488;">💾 Baixar Resumo (.TXT)</a>
            """
        elif transcripts:
            sum_buttons = f"""
                <a href="/view/{ep.id}#resumo-ia" class="btn-copy">✨ Resumir (LLM)</a>
            """

        status_html = f"""
        <div class="completed-actions">
            <span class="badge-completed">✅ Processado</span>
            {proc_html}
            <div style="display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end;">
                {tx_buttons}
                {sum_buttons}
            </div>
            <div style="display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; justify-content: flex-end; width: 100%;">
                <form hx-post="/episodes/{ep.id}/download" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML" style="display: flex; gap: 4px; flex: 1;">
                    <select name="model_id" class="select-inline-model" style="margin-bottom: 0; padding: 5px; font-size: 0.75rem;">
                        {model_options_html}
                    </select>
                    <button type="submit" class="btn-reprocess" title="Baixar novamente o áudio e transcrever localmente">
                        🔄 Reprocessar ASR
                    </button>
                </form>
                <form hx-post="/episodes/{ep.id}/summarize-direct" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML" style="display: flex; gap: 4px; flex: 1;">
                    <select name="llm_provider" class="select-inline-model" style="margin-bottom: 0; padding: 5px; font-size: 0.75rem;">
                        {llm_options_html}
                    </select>
                    <button type="submit" class="btn-reprocess" style="border-color: #6366f1;" title="Baixar áudio e resumir direto via API de LLM">
                        🤖 Resumir Direto
                    </button>
                </form>
            </div>
        </div>
        """
    elif ep.status.value == "failed":
        err_msg = (ep.error_message or "Erro desconhecido")[:120]
        status_html = f"""
        <div class="completed-actions">
            <span style="color: #ef4444; font-size: 0.8rem; font-weight: 600;" title="{err_msg}">❌ Falhou: {err_msg}</span>
            {dual_action_forms}
        </div>
        """
    else:
        status_html = dual_action_forms

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
    """User clicked to queue download and local ASR transcription."""
    conn = get_db_connection()
    repo = Repository(conn)
    ep = repo.get_episode(episode_id)
    if not ep:
        conn.close()
        raise HTTPException(status_code=404, detail="Episódio não encontrado")

    chosen_model = model_id or settings.default_model_id

    active_job = repo.get_active_job_for_episode(episode_id)
    if active_job:
        q_pos = repo.get_queue_position(active_job.id)
        conn.close()
        if request.headers.get("hx-request"):
            return get_episode_card(episode_id)
        return {
            "status": "already_queued",
            "job_id": active_job.id,
            "queue_position": q_pos,
            "model_id": active_job.model_id or chosen_model,
        }

    repo.update_episode_status(episode_id, EpisodeStatus.QUEUED_DOWNLOAD)
    job = repo.create_job(
        job_type="download_and_transcribe",
        episode_id=episode_id,
        model_id=chosen_model,
    )
    q_pos = repo.get_queue_position(job.id)
    conn.close()
    logger.info(
        f"[QUEUE] Episódio #{episode_id} '{ep.title}' adicionado à fila de transcrição "
        f"(Job #{job.id}, Posição na fila: #{q_pos}, Modelo: '{chosen_model}')"
    )
    if request.headers.get("hx-request"):
        return get_episode_card(episode_id)
    return {
        "status": "queued",
        "job_id": job.id,
        "queue_position": q_pos,
        "model_id": chosen_model,
    }


@router.post("/{episode_id}/summarize-direct")
def trigger_download_and_summarize_direct(
    episode_id: int,
    request: Request,
    llm_provider: str | None = Form(None),
):
    """User clicked to download audio and summarize directly via a registered LLM API."""
    conn = get_db_connection()
    repo = Repository(conn)
    ep = repo.get_episode(episode_id)
    if not ep:
        conn.close()
        raise HTTPException(status_code=404, detail="Episódio não encontrado")

    llm_svc = LLMService(repo)
    cfg = llm_svc.get_config()
    chosen_provider = llm_provider or cfg["last_direct_provider"]
    if chosen_provider not in LLM_PROVIDERS:
        chosen_provider = cfg["active_provider"]

    # Always remember the user's last selected LLM option!
    llm_svc.set_last_direct_provider(chosen_provider)

    # Check if API key is configured for this provider
    prov_info = cfg["providers"].get(chosen_provider, {})
    if not prov_info.get("has_key"):
        err_msg = (
            f"Cadastre a API Key de {prov_info.get('name', chosen_provider)} em "
            "'🤖 Resumo LLM / Prompt' antes de resumir."
        )
        repo.update_episode_status(episode_id, EpisodeStatus.FAILED, error_message=err_msg)
        conn.close()
        if request.headers.get("hx-request"):
            return get_episode_card(episode_id)
        raise HTTPException(status_code=400, detail=err_msg)

    active_job = repo.get_active_job_for_episode(episode_id)
    if active_job:
        q_pos = repo.get_queue_position(active_job.id)
        conn.close()
        if request.headers.get("hx-request"):
            return get_episode_card(episode_id)
        return {
            "status": "already_queued",
            "job_id": active_job.id,
            "queue_position": q_pos,
            "llm_provider": chosen_provider,
        }

    repo.update_episode_status(episode_id, EpisodeStatus.QUEUED_DOWNLOAD)
    job = repo.create_job(
        job_type="download_and_summarize_llm",
        episode_id=episode_id,
        model_id=chosen_provider,
    )
    q_pos = repo.get_queue_position(job.id)
    conn.close()
    logger.info(
        f"[QUEUE] Episódio #{episode_id} '{ep.title}' adicionado à fila de RESUMO DIRETO LLM "
        f"(Job #{job.id}, Posição: #{q_pos}, Provedor: '{chosen_provider}')"
    )
    if request.headers.get("hx-request"):
        return get_episode_card(episode_id)
    return {
        "status": "queued",
        "job_id": job.id,
        "queue_position": q_pos,
        "llm_provider": chosen_provider,
    }


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
