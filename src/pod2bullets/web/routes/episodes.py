"""Episode listing, multi-item queue trigger (100% local ASR + optional LLM text summary), web reading & .txt export."""

import html
import logging
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.llm.service import LLM_PROVIDERS, LLMService
from pod2bullets.models import EpisodeStatus
from pod2bullets.transcriber.registry import ModelRegistry
from pod2bullets.worker.queue import parse_job_models

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
    """Build <option> tags for choosing the LLM model/provider alongside local transcription."""
    last_prov = llm_cfg.get("last_direct_provider") or "none"
    none_sel = "selected" if last_prov == "none" else ""
    options = [
        f'<option value="none" {none_sel}>🚫 Apenas Transcrever Localmente (Sem LLM)</option>'
    ]
    for pid, p in llm_cfg["providers"].items():
        sel = "selected" if pid == last_prov else ""
        status_icon = "✅" if p["has_key"] else "⚠️ Sem chave"
        options.append(
            f'<option value="{pid}" {sel}>🤖 Resumir c/ {p["name"]} ({p["model"]}) [{status_icon}]</option>'
        )
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
    raw_job_model = (job_row["model_id"] if job_row else None) or settings.default_model_id
    asr_job_model, llm_job_prov = parse_job_models(raw_job_model)
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

    local_action_form = f"""
    <form hx-post="/episodes/{ep.id}/download" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML" class="action-box" style="min-width: 280px;">
        <label class="action-box-label">🎙️ Modelo de Transcrição Local (GPU/CPU):</label>
        <select name="model_id" class="select-inline-model">
            {model_options_html}
        </select>
        <label class="action-box-label" style="margin-top: 4px;">🤖 Modelo LLM p/ Resumir Texto (Opcional):</label>
        <select name="llm_provider" class="select-inline-model">
            {llm_options_html}
        </select>
        <button type="submit" class="btn-download" style="margin-top: 4px;">⬇️ Baixar e Transcrever</button>
    </form>
    """

    status_html = ""
    if ep.status.value == "queued_download" and job_status == "pending":
        llm_tag = f" + LLM ({llm_job_prov})" if llm_job_prov else ""
        status_html = f"""
        <div class="status-box queued" hx-get="/episodes/card/{ep.id}" hx-trigger="every 1.5s" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                <span>🕒 Na fila (#{q_pos}) — <code>{asr_job_model}{llm_tag}</code></span>
                {cancel_inline_btn}
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: 5%; opacity: 0.6;"></div>
            </div>
        </div>
        """
    elif ep.status.value in ["queued_download", "downloading"]:
        status_html = f"""
        <div class="status-box downloading" hx-get="/episodes/card/{ep.id}" hx-trigger="every 1.2s" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                <span><span class="hourglass-icon">⏳</span> Baixando áudio ({progress:.0f}%)...</span>
                {cancel_inline_btn}
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: {max(progress, 2):.0f}%;"></div>
            </div>
        </div>
        """
    elif ep.status.value == "summarizing_llm":
        prov_label = LLM_PROVIDERS.get(llm_job_prov or "", {}).get("name", llm_job_prov or "LLM")
        status_html = f"""
        <div class="status-box transcribing" hx-get="/episodes/card/{ep.id}" hx-trigger="every 1.2s" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                <span><span class="hourglass-icon">⏳</span> Resumindo transcrição via {prov_label}...</span>
                {cancel_inline_btn}
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill transcribe" style="width: 95%;"></div>
            </div>
        </div>
        """
    elif ep.status.value in ["queued_transcription", "transcribing"]:
        status_html = f"""
        <div class="status-box transcribing" hx-get="/episodes/card/{ep.id}" hx-trigger="every 1.2s" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                <span><span class="hourglass-icon">⏳</span> Transcrevendo com {asr_job_model} ({progress:.0f}%)...</span>
                {cancel_inline_btn}
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill transcribe" style="width: {max(progress, 2):.0f}%;"></div>
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
                <a href="/view/{ep.id}#resumo-ia" class="btn-copy">📑 Ler Resumo ({latest_summary.model_name})</a>
                <a href="/llm/summaries/{latest_summary.id}/download" class="btn-txt" style="background: #0d9488;">💾 Baixar Resumo (.TXT)</a>
            """
        elif transcripts:
            sum_buttons = f"""
                <a href="/view/{ep.id}#resumo-ia" class="btn-copy">✨ Resumir Texto (LLM)</a>
            """

        llm_warn_html = ""
        if ep.error_message:
            warn_esc = html.escape(ep.error_message[:180])
            llm_warn_html = f"""
            <div style="font-size: 0.75rem; color: #fbbf24; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 5px; padding: 5px 8px; max-width: 340px; text-align: right;" title="{html.escape(ep.error_message)}">
                ⚠️ {warn_esc}
            </div>
            """

        status_html = f"""
        <div class="completed-actions">
            <span class="badge-completed">✅ Transcrito Localmente</span>
            {proc_html}
            {llm_warn_html}
            <div style="display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end;">
                {tx_buttons}
                {sum_buttons}
            </div>
            <form hx-post="/episodes/{ep.id}/download" hx-target="#ep-card-{ep.id}" hx-swap="outerHTML" style="display: flex; flex-direction: column; gap: 4px; margin-top: 6px; width: 100%; max-width: 320px;">
                <div style="display: flex; gap: 4px;">
                    <select name="model_id" class="select-inline-model" style="margin-bottom: 0; padding: 5px; font-size: 0.74rem; flex: 1;">
                        {model_options_html}
                    </select>
                    <select name="llm_provider" class="select-inline-model" style="margin-bottom: 0; padding: 5px; font-size: 0.74rem; flex: 1;">
                        {llm_options_html}
                    </select>
                </div>
                <button type="submit" class="btn-reprocess" title="Baixar novamente o áudio e reprocessar localmente">
                    🔄 Reprocessar Transcrição Local
                </button>
            </form>
        </div>
        """
    elif ep.status.value == "failed":
        err_msg = html.escape((ep.error_message or "Erro desconhecido")[:140])
        status_html = f"""
        <div class="completed-actions">
            <span style="color: #ef4444; font-size: 0.8rem; font-weight: 600;" title="{err_msg}">❌ Falhou: {err_msg}</span>
            {local_action_form}
        </div>
        """
    else:
        status_html = local_action_form

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
    llm_provider: str | None = Form(None),
):
    """User clicked to queue download and 100% local ASR transcription (+ optional LLM text summary)."""
    conn = get_db_connection()
    repo = Repository(conn)
    ep = repo.get_episode(episode_id)
    if not ep:
        conn.close()
        raise HTTPException(status_code=404, detail="Episódio não encontrado")

    chosen_model = (model_id or settings.default_model_id).strip()
    chosen_llm = (llm_provider or "none").strip()

    # Remember the user's last LLM choice in settings
    if chosen_llm == "none" or chosen_llm in LLM_PROVIDERS:
        LLMService(repo).set_last_direct_provider(chosen_llm)

    combined_model_field = (
        f"{chosen_model}|{chosen_llm}"
        if chosen_llm and chosen_llm != "none" and chosen_llm in LLM_PROVIDERS
        else chosen_model
    )

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

    repo.update_episode_status(episode_id, EpisodeStatus.QUEUED_DOWNLOAD, error_message="")
    job = repo.create_job(
        job_type="download_and_transcribe",
        episode_id=episode_id,
        model_id=combined_model_field,
    )
    q_pos = repo.get_queue_position(job.id)
    conn.close()
    logger.info(
        f"[QUEUE] Episódio #{episode_id} '{ep.title}' adicionado à fila de transcrição local "
        f"(Job #{job.id}, Posição na fila: #{q_pos}, ASR: '{chosen_model}', LLM: '{chosen_llm}')"
    )
    if request.headers.get("hx-request"):
        return get_episode_card(episode_id)
    return {
        "status": "queued",
        "job_id": job.id,
        "queue_position": q_pos,
        "model_id": chosen_model,
        "llm_provider": chosen_llm,
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
