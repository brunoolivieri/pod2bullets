"""Web routes for LLM configuration, editable summarization prompt, and episode summarization."""

import html
import logging

from fastapi import APIRouter, Form, HTTPException, Request, Response

from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.llm.service import LLM_PROVIDERS, LLMService

logger = logging.getLogger("pod2bullets.web.llm")

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/config")
def get_llm_config():
    conn = get_db_connection()
    repo = Repository(conn)
    cfg = LLMService(repo).get_config()
    conn.close()
    # Mask raw keys in JSON response
    safe_providers = {}
    for pid, pdata in cfg["providers"].items():
        safe_providers[pid] = {k: v for k, v in pdata.items() if k != "api_key"}
    return {
        "active_provider": cfg["active_provider"],
        "prompt": cfg["prompt"],
        "providers": safe_providers,
    }


@router.post("/config")
def save_llm_config(
    request: Request,
    provider: str = Form(...),
    prompt: str = Form(...),
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
                ✅ Configurações e Prompt salvos com sucesso! (Provedor ativo: {prov_label})
            </div>
            """,
            media_type="text/html",
        )
    return {"ok": True, "provider": provider}


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
    except Exception as e:
        conn.close()
        logger.error(f"[LLM] Erro ao resumir episódio #{episode_id}: {e}", exc_info=True)
        if request.headers.get("hx-request"):
            err_escaped = html.escape(str(e))
            return Response(
                content=f"""
                <div style="padding: 14px; background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; color: #f87171; border-radius: 6px; margin-top: 12px;">
                    <strong>❌ Falha ao gerar resumo com LLM:</strong> {err_escaped}
                </div>
                """,
                media_type="text/html",
            )
        raise HTTPException(status_code=400, detail=str(e))

    conn.close()

    if request.headers.get("hx-request"):
        prov_name = LLM_PROVIDERS.get(summary.provider, {}).get("name", summary.provider)
        escaped_text = html.escape(summary.summary_text)
        return Response(
            content=f"""
            <div class="summary-result-card" style="background: #0f172a; border: 1px solid #3b82f6; border-radius: 8px; padding: 20px; margin-top: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
                    <div>
                        <strong style="color: #60a5fa; font-size: 1.05rem;">✨ Resumo Gerado por {prov_name} ({summary.model_name})</strong>
                        <span style="font-size: 0.8rem; color: #94a3b8; margin-left: 10px;">⏱️ {summary.duration_proc_seconds}s</span>
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <a href="/llm/summaries/{summary.id}/download" class="btn-txt">💾 Exportar Resumo (.TXT)</a>
                    </div>
                </div>
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

