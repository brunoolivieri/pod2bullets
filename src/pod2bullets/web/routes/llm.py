"""Web routes for LLM configuration, per-provider API control, editable prompt, and transcript summarization."""

import html
import logging

from fastapi import APIRouter, Form, HTTPException, Request, Response

from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.llm.service import LLM_PROVIDERS, LLMService, LLMSummaryError

logger = logging.getLogger("pod2bullets.web.llm")

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/config")
def get_llm_config():
    conn = get_db_connection()
    repo = Repository(conn)
    cfg = LLMService(repo).get_config()
    conn.close()
    safe_providers = {}
    for pid, pdata in cfg["providers"].items():
        safe_providers[pid] = {k: v for k, v in pdata.items() if k != "api_key"}
    return {
        "active_provider": cfg["active_provider"],
        "last_direct_provider": cfg["last_direct_provider"],
        "prompt": cfg["prompt"],
        "providers": safe_providers,
    }


@router.post("/config")
def save_llm_config(
    request: Request,
    provider: str = Form(...),
    prompt: str | None = Form(None),
    model_name: str | None = Form(None),
    api_key: str | None = Form(None),
):
    conn = get_db_connection()
    repo = Repository(conn)
    svc = LLMService(repo)
    try:
        svc.save_config(
            provider=provider,
            prompt=prompt,
            model_name=model_name,
            api_key=api_key,
        )
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=str(e))
    conn.close()

    if request.headers.get("hx-request"):
        prov_label = LLM_PROVIDERS.get(provider, {}).get("name", provider)
        return Response(
            content=f"""
            <div style="padding: 10px 14px; background: rgba(16, 185, 129, 0.15); border: 1px solid #10b981; color: #34d399; border-radius: 6px; font-weight: 600; margin-top: 10px;">
                ✅ Configuração salva com sucesso! ({prov_label})
            </div>
            """,
            media_type="text/html",
        )
    return {"ok": True, "provider": provider}


@router.post("/provider/{provider_id}")
def save_single_provider_api(
    provider_id: str,
    request: Request,
    model_name: str = Form(...),
    api_key: str | None = Form(None),
):
    """Save API key and model for a specific provider card in the LLM Control Center."""
    conn = get_db_connection()
    repo = Repository(conn)
    svc = LLMService(repo)
    try:
        svc.save_config(
            provider=provider_id,
            model_name=model_name,
            api_key=api_key,
        )
    except Exception as e:
        conn.close()
        if request.headers.get("hx-request"):
            return Response(
                content=f'<span style="color: #f87171; font-weight: 700;">❌ {html.escape(str(e))}</span>',
                media_type="text/html",
            )
        raise HTTPException(status_code=400, detail=str(e))
    conn.close()

    if request.headers.get("hx-request"):
        return Response(
            content='<span style="color: #10b981; font-weight: 700;">✅ API salva e selecionada! Recarregando...</span><script>setTimeout(() => location.reload(), 500);</script>',
            media_type="text/html",
        )
    return {"ok": True, "provider": provider_id}


@router.delete("/provider/{provider_id}/key")
def delete_single_provider_key(provider_id: str, request: Request):
    """Delete stored API key for a specific provider."""
    conn = get_db_connection()
    repo = Repository(conn)
    svc = LLMService(repo)
    svc.clear_api_key(provider_id)
    conn.close()

    if request.headers.get("hx-request"):
        return Response(
            content='<span style="color: #f87171; font-weight: 700;">🗑️ Chave removida! Recarregando...</span><script>setTimeout(() => location.reload(), 500);</script>',
            media_type="text/html",
        )
    return {"ok": True, "provider": provider_id}


@router.post("/prompt")
def save_custom_prompt_route(request: Request, prompt: str = Form(...)):
    """Save the customizable summarization prompt."""
    conn = get_db_connection()
    repo = Repository(conn)
    LLMService(repo).save_prompt_only(prompt)
    conn.close()

    if request.headers.get("hx-request"):
        return Response(
            content="""
            <div style="padding: 10px 14px; background: rgba(16, 185, 129, 0.15); border: 1px solid #10b981; color: #34d399; border-radius: 6px; font-weight: 600; margin-top: 10px;">
                ✅ Prompt customizável salvo com sucesso! Ele será usado nos próximos resumos.
            </div>
            """,
            media_type="text/html",
        )
    return {"ok": True}


@router.post("/summarize/{episode_id}")
def summarize_episode_route(
    episode_id: int,
    request: Request,
    provider: str | None = Form(None),
    model_name: str | None = Form(None),
    prompt: str | None = Form(None),
    api_key: str | None = Form(None),
):
    conn = get_db_connection()
    repo = Repository(conn)
    svc = LLMService(repo)
    try:
        summary = svc.summarize_episode(
            episode_id=episode_id,
            provider=provider,
            model_name=model_name,
            custom_prompt=prompt,
            api_key=api_key,
        )
        attempts = list(svc._last_attempts_report)
    except Exception as e:
        attempts = getattr(e, "attempts", []) or list(svc._last_attempts_report)
        conn.close()
        # Log a clean error line without dumping a 50-line stack trace for expected API errors
        if isinstance(e, (LLMSummaryError, ValueError, RuntimeError)):
            logger.error(f"[LLM] Não foi possível resumir o episódio #{episode_id}: {e}")
        else:
            logger.error(
                f"[LLM] Erro inesperado ao resumir episódio #{episode_id}: {e}", exc_info=True
            )

        if request.headers.get("hx-request"):
            err_escaped = html.escape(str(e))
            attempts_html = ""
            if attempts:
                li_items = "".join(f"<li>{html.escape(a)}</li>" for a in attempts)
                attempts_html = f"""
                <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(239, 68, 68, 0.35); font-size: 0.82rem; color: #fca5a5;">
                    <strong>📋 Tentativas realizadas (da versão mais recente para alternativas):</strong>
                    <ul style="margin: 6px 0 0 18px; padding: 0;">{li_items}</ul>
                </div>
                """
            return Response(
                content=f"""
                <div style="padding: 14px; background: rgba(239, 68, 68, 0.14); border: 1px solid #ef4444; color: #f87171; border-radius: 6px; margin-top: 12px;">
                    <div><strong>❌ Falha ao gerar resumo com LLM:</strong> {err_escaped}</div>
                    {attempts_html}
                </div>
                """,
                media_type="text/html",
            )
        raise HTTPException(status_code=400, detail=str(e))

    conn.close()

    if request.headers.get("hx-request"):
        prov_name = LLM_PROVIDERS.get(summary.provider, {}).get("name", summary.provider)
        escaped_text = html.escape(summary.summary_text)
        attempts_badge = (
            '<span style="font-size: 0.78rem; color: #34d399; margin-left: 8px;">✅ 1ª tentativa (modelo mais recente)</span>'
            if len(attempts) <= 1
            else f'<span style="font-size: 0.78rem; color: #fbbf24; margin-left: 8px;">🔄 Obtido na {len(attempts)}ª tentativa (fallback automático)</span>'
        )
        attempts_detail_html = ""
        if len(attempts) > 1:
            li_items = "".join(f"<li>{html.escape(a)}</li>" for a in attempts)
            attempts_detail_html = f"""
            <div style="margin-bottom: 10px; padding: 8px 12px; background: rgba(30, 41, 59, 0.75); border-radius: 6px; font-size: 0.78rem; color: #cbd5e1;">
                <strong>Histórico de tentativas da API:</strong>
                <ul style="margin: 4px 0 0 18px; padding: 0;">{li_items}</ul>
            </div>
            """
        return Response(
            content=f"""
            <div class="summary-result-card" style="background: #0f172a; border: 1px solid #3b82f6; border-radius: 8px; padding: 20px; margin-top: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
                    <div>
                        <strong style="color: #60a5fa; font-size: 1.05rem;">✨ Resumo Gerado por {prov_name} ({summary.model_name})</strong>
                        <span style="font-size: 0.8rem; color: #94a3b8; margin-left: 10px;">⏱️ {summary.duration_proc_seconds}s</span>
                        {attempts_badge}
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <a href="/llm/summaries/{summary.id}/download" class="btn-txt">💾 Exportar Resumo (.TXT)</a>
                    </div>
                </div>
                {attempts_detail_html}
                <pre class="plain-text-display" style="margin-top: 8px;">{escaped_text}</pre>
            </div>
            """,
            media_type="text/html",
        )

    return summary


@router.get("/summaries/{summary_id}/download")
def download_summary_txt(summary_id: int):
    conn = get_db_connection()
    repo = Repository(conn)
    summary = repo.get_summary(summary_id)
    ep = repo.get_episode(summary.episode_id) if summary else None
    conn.close()

    if not summary:
        raise HTTPException(status_code=404, detail="Resumo não encontrado")

    ep_slug = ep.slug if ep else f"episodio-{summary.episode_id}"
    filename = f"{ep_slug}__resumo_{summary.provider}.txt"
    return Response(
        content=summary.summary_text.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
