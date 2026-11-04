"""Queue visualization, live progress monitoring, and job cancellation routes."""

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.system_status import activity_tracker
from pod2bullets.worker.queue import parse_job_models

logger = logging.getLogger("pod2bullets.web.queue")

router = APIRouter(prefix="/queue", tags=["queue"])


def _render_queue_panel_html() -> str:
    conn = get_db_connection()
    repo = Repository(conn)
    jobs = repo.list_queue_jobs(limit_history=10)
    conn.close()

    mem_tasks = activity_tracker.list_active()
    active_jobs = [j for j in jobs if j["status"] in ("running", "pending")]
    history_jobs = [j for j in jobs if j["status"] not in ("running", "pending")]

    cards_html = []

    # 1. Active in-memory tasks (e.g., installing model weights)
    for t in mem_tasks:
        cards_html.append(
            f"""
            <div class="queue-item running">
                <div class="queue-item-header">
                    <div>
                        <span class="queue-badge running">⏳ Em execução (Sistema)</span>
                        <strong class="queue-ep-title">{t["description"]}</strong>
                    </div>
                </div>
                <div class="progress-bar-container" style="margin-top: 8px;">
                    <div class="progress-bar-fill" style="width: 55%;"></div>
                </div>
            </div>
            """
        )

    # 2. Active & Pending Jobs in SQLite queue
    for j in active_jobs:
        jid = j["id"]
        pos = j["queue_position"]
        status = j["status"]
        ep_status = j.get("ep_status") or ""
        pct = round(float(j.get("progress_percent") or 0.0), 1)
        ep_title = j.get("episode_title") or f"Episódio #{j['episode_id']}"
        feed_title = j.get("feed_title") or "Podcast"
        raw_model_id = j.get("model_id") or "padrão"
        asr_model, llm_prov = parse_job_models(raw_model_id)
        mode_label = (
            f"🎙️ ASR ({asr_model}) + 🤖 LLM ({llm_prov})"
            if llm_prov
            else f"🎙️ Transcrição Local ({asr_model})"
        )

        if status == "running":
            if ep_status == "summarizing_llm":
                stage_text = f"⏳ Resumindo transcrição via LLM ({llm_prov or 'API'})"
                bar_class = "progress-bar-fill transcribe"
            elif ep_status == "transcribing":
                stage_text = f"⏳ Transcrevendo áudio ({pct:.0f}%)"
                bar_class = "progress-bar-fill transcribe"
            else:
                stage_text = f"⬇️ Baixando áudio ({pct:.0f}%)"
                bar_class = "progress-bar-fill"
            badge_html = '<span class="queue-badge running">▶ Executando (#1)</span>'
        else:
            stage_text = f"🕒 Aguardando na fila (Posição #{pos})"
            bar_class = "progress-bar-fill"
            pct = 0.0
            badge_html = f'<span class="queue-badge pending">🕒 Na Fila (#{pos})</span>'

        cards_html.append(
            f"""
            <div class="queue-item {status}" id="queue-job-{jid}">
                <div class="queue-item-header">
                    <div class="queue-item-meta">
                        {badge_html}
                        <span class="queue-feed-tag">{feed_title}</span>
                        <span class="queue-mode-tag">{mode_label}</span>
                    </div>
                    <button type="button"
                            class="btn-cancel-job"
                            hx-post="/queue/{jid}/cancel"
                            hx-target="#queue-panel-container"
                            hx-swap="outerHTML"
                            title="Cancelar este item da fila">
                        ✖ Cancelar
                    </button>
                </div>
                <div class="queue-ep-title">{ep_title}</div>
                <div class="queue-progress-row">
                    <span class="queue-stage-text">{stage_text}</span>
                    <span class="queue-pct-text">{pct:.0f}%</span>
                </div>
                <div class="progress-bar-container">
                    <div class="{bar_class}" style="width: {max(pct, 2):.0f}%;"></div>
                </div>
            </div>
            """
        )

    if not cards_html:
        active_section = """
        <div class="queue-empty-box">
            ✅ Nenhum item em processamento ou aguardando na fila no momento.
        </div>
        """
    else:
        active_section = '<div class="queue-list">' + "".join(cards_html) + "</div>"

    # 3. Recent History (Completed / Cancelled / Failed)
    history_rows = []
    for h in history_jobs:
        st = h["status"]
        ep_title = h.get("episode_title") or f"Episódio #{h['episode_id']}"
        feed_title = h.get("feed_title") or "Podcast"
        model_id = h.get("model_id") or ""
        ep_id = h.get("episode_id")
        if st == "completed":
            st_badge = '<span class="queue-badge completed">✅ Concluído</span>'
            action_link = f'<a href="/view/{ep_id}" class="btn-view" style="padding: 4px 10px; font-size: 0.78rem;">📖 Abrir Resultado</a>'
        elif st == "cancelled":
            st_badge = '<span class="queue-badge cancelled">🚫 Cancelado</span>'
            action_link = ""
        else:
            err = (h.get("error_message") or "Erro")[:80]
            st_badge = f'<span class="queue-badge failed" title="{err}">❌ Falhou: {err}</span>'
            action_link = ""

        history_rows.append(
            f"""
            <div class="queue-history-row">
                <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                    {st_badge}
                    <span style="color: #94a3b8; font-size: 0.8rem;">[{feed_title}]</span>
                    <strong style="color: #e2e8f0; font-size: 0.88rem;">{ep_title}</strong>
                    <code style="font-size: 0.75rem; color: #60a5fa;">{model_id}</code>
                </div>
                <div>{action_link}</div>
            </div>
            """
        )

    history_section = ""
    if history_rows:
        history_section = f"""
        <div style="margin-top: 24px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h3 style="color: #cbd5e1; font-size: 1rem;">📜 Histórico Recente</h3>
                <button type="button"
                        class="btn-reprocess"
                        hx-post="/queue/clear-history"
                        hx-target="#queue-panel-container"
                        hx-swap="outerHTML">
                    🧹 Limpar Histórico
                </button>
            </div>
            <div class="queue-history-list">
                {"".join(history_rows)}
            </div>
        </div>
        """

    cancel_all_btn = ""
    if active_jobs:
        cancel_all_btn = """
        <button type="button"
                class="btn-delete"
                hx-post="/queue/cancel-all"
                hx-confirm="Deseja cancelar todos os itens da fila?"
                hx-target="#queue-panel-container"
                hx-swap="outerHTML">
            🛑 Cancelar Todos da Fila
        </button>
        """

    return f"""
    <div id="queue-panel-container"
         hx-get="/queue/panel"
         hx-trigger="every 1.5s"
         hx-swap="outerHTML">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 10px;">
            <div>
                <span class="badge-total">{len(active_jobs) + len(mem_tasks)} ativo(s) na fila</span>
            </div>
            <div>{cancel_all_btn}</div>
        </div>
        {active_section}
        {history_section}
    </div>
    """


@router.get("/")
def list_queue_json():
    conn = get_db_connection()
    repo = Repository(conn)
    jobs = repo.list_queue_jobs()
    conn.close()
    return {"jobs": jobs, "system_tasks": activity_tracker.list_active()}


@router.get("/panel", response_class=Response)
def get_queue_panel_partial():
    return Response(content=_render_queue_panel_html(), media_type="text/html")


@router.post("/{job_id}/cancel")
def cancel_queue_job(job_id: int, request: Request, from_card: int | None = None):
    """Cancel a pending or running job."""
    conn = get_db_connection()
    repo = Repository(conn)
    job = repo.cancel_job(job_id)
    conn.close()
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")

    logger.info(f"[QUEUE] Job #{job_id} (Episódio #{job.episode_id}) cancelado pelo usuário.")

    if from_card:
        from pod2bullets.web.routes.episodes import get_episode_card

        return get_episode_card(job.episode_id)

    if request.headers.get("hx-request"):
        return Response(content=_render_queue_panel_html(), media_type="text/html")
    return {"ok": True, "job_id": job_id, "status": "cancelled"}


@router.post("/cancel-all")
def cancel_all_queue_jobs(request: Request):
    """Cancel all pending and running jobs in the queue."""
    conn = get_db_connection()
    repo = Repository(conn)
    count = repo.cancel_all_active_jobs()
    conn.close()
    logger.info(f"[QUEUE] Todos os {count} jobs ativos foram cancelados pelo usuário.")
    if request.headers.get("hx-request"):
        return Response(content=_render_queue_panel_html(), media_type="text/html")
    return {"ok": True, "cancelled_count": count}


@router.post("/clear-history")
def clear_queue_history(request: Request):
    """Clear finished/cancelled/failed jobs from the queue history."""
    conn = get_db_connection()
    repo = Repository(conn)
    count = repo.clear_finished_jobs()
    conn.close()
    if request.headers.get("hx-request"):
        return Response(content=_render_queue_panel_html(), media_type="text/html")
    return {"ok": True, "cleared_count": count}
