"""Web routes for browsing, filtering, reading, and managing generated LLM summaries."""

import html
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from pod2bullets.db.connection import get_db_connection
from pod2bullets.db.repository import Repository
from pod2bullets.llm.service import LLM_PROVIDERS
from pod2bullets.transcriber.registry import ModelRegistry

logger = logging.getLogger("pod2bullets.web.summaries")

router = APIRouter(prefix="/summaries", tags=["summaries"])


def _render_summaries_list_html(
    summaries: list[dict],
    selected_feed_id: int | None = None,
    selected_provider: str | None = None,
) -> str:
    """Render the inner list of summaries cards (or empty state) with generation details."""
    if not summaries:
        filter_hint = ""
        if selected_feed_id or selected_provider:
            filter_hint = " com os filtros selecionados. Tente remover os filtros acima."
        return f"""
        <div class="empty-state" style="padding: 40px 20px; text-align: center; background: #1e293b; border-radius: 8px; border: 1px dashed #334155; margin-top: 14px;">
            <div style="font-size: 2.2rem; margin-bottom: 8px;">📑</div>
            <h3 style="color: #cbd5e1; margin-bottom: 6px;">Nenhum resumo encontrado{filter_hint}</h3>
            <p style="color: #94a3b8; font-size: 0.9rem; max-width: 500px; margin: 0 auto;">
                Gere resumos a partir de transcrições locais nos episódios usando qualquer uma das LLMs disponíveis (Gemini, Claude, ChatGPT, DeepSeek ou Qwen).
            </p>
        </div>
        """

    cards = []
    for s in summaries:
        sid = s["id"]
        ep_id = s["episode_id"]
        ep_title = html.escape(s.get("episode_title") or f"Episódio #{ep_id}")
        feed_title = html.escape(s.get("feed_title") or "Podcast")
        provider = s.get("provider") or "llm"
        model_name = html.escape(s.get("model_name") or "")
        prompt_used = html.escape(s.get("prompt_used") or "")
        summary_text = html.escape(s.get("summary_text") or "")
        duration = s.get("duration_proc_seconds")
        duration_str = f"{duration:.1f}s" if duration is not None else "?"
        created_at = s.get("created_at") or ""
        cover_img = s.get("episode_image_url") or s.get("feed_image_url")
        asr_model = s.get("asr_model_id") or "Transcrição Local"

        # Thematic badge styling per LLM provider
        badge_style_map = {
            "gemini": "background: rgba(59, 130, 246, 0.2); border-color: #3b82f6; color: #60a5fa;",
            "claude": "background: rgba(217, 119, 6, 0.2); border-color: #f59e0b; color: #fbbf24;",
            "chatgpt": "background: rgba(16, 185, 129, 0.2); border-color: #10b981; color: #34d399;",
            "deepseek": "background: rgba(6, 182, 212, 0.2); border-color: #06b6d4; color: #22d3ee;",
            "qwen": "background: rgba(147, 51, 234, 0.2); border-color: #a855f7; color: #c084fc;",
        }
        badge_style = badge_style_map.get(
            provider,
            "background: rgba(100, 116, 139, 0.2); border-color: #64748b; color: #cbd5e1;",
        )
        prov_label = LLM_PROVIDERS.get(provider, {}).get("name", provider.upper())

        cover_html = (
            f'<img src="{cover_img}" alt="Capa" class="ep-cover-img" style="width: 56px; height: 56px; border-radius: 6px; object-fit: cover;" loading="lazy">'
            if cover_img
            else '<div class="ep-cover-placeholder" style="width: 56px; height: 56px; border-radius: 6px; display: flex; align-items: center; justify-content: center; background: #0f172a; font-size: 1.5rem;">🎙️</div>'
        )

        prompt_block = (
            f"""
                <!-- Detalhes do Prompt Utilizado (Transparência de como foi gerado) -->
                <details style="margin-bottom: 12px; font-size: 0.8rem; background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 6px 10px;">
                    <summary style="cursor: pointer; color: #94a3b8; font-weight: 600; outline: none;">
                        🔍 Ver prompt utilizado na geração deste resumo
                    </summary>
                    <pre style="margin-top: 8px; white-space: pre-wrap; color: #cbd5e1; font-family: monospace; font-size: 0.78rem; line-height: 1.4;">{prompt_used}</pre>
                </details>
            """
            if prompt_used
            else ""
        )

        cards.append(
            f"""
            <div class="summary-card" id="summary-card-{sid}" style="background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 20px; margin-bottom: 18px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);">
                <!-- Header do Card -->
                <div style="display: flex; gap: 14px; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; margin-bottom: 12px; border-bottom: 1px solid rgba(51, 65, 85, 0.7); padding-bottom: 12px;">
                    <div style="display: flex; gap: 12px; align-items: center; max-width: 65%;">
                        {cover_html}
                        <div>
                            <span style="font-size: 0.8rem; color: #94a3b8; font-weight: 600;">{feed_title}</span>
                            <h3 style="font-size: 1.05rem; margin: 2px 0 4px 0; color: #f8fafc;">
                                <a href="/view/{ep_id}#summary-{sid}" style="color: #f8fafc; text-decoration: none;" hover="text-decoration: underline;">
                                    {ep_title}
                                </a>
                            </h3>
                            <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center; font-size: 0.76rem; color: #64748b;">
                                <span>📅 {created_at}</span>
                                <span>•</span>
                                <span>🎙️ Base: <code>{asr_model}</code></span>
                            </div>
                        </div>
                    </div>

                    <!-- Meta & Ações -->
                    <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 8px;">
                        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                            <span class="badge-llm" style="padding: 4px 10px; border-radius: 999px; font-size: 0.78rem; font-weight: 700; border: 1px solid; {badge_style}">
                                🤖 {prov_label} ({model_name})
                            </span>
                            <span style="font-size: 0.78rem; color: #94a3b8; background: #0f172a; padding: 3px 8px; border-radius: 6px; border: 1px solid #334155;">
                                ⏱️ {duration_str}
                            </span>
                        </div>

                        <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                            <a href="/view/{ep_id}#summary-{sid}" class="btn-view" style="padding: 4px 10px; font-size: 0.76rem;">📖 Ver Episódio</a>
                            <a href="/llm/summaries/{sid}/download" class="btn-txt" style="padding: 4px 10px; font-size: 0.76rem;">💾 Baixar .TXT</a>
                            <button type="button"
                                    class="btn-copy"
                                    style="padding: 4px 10px; font-size: 0.76rem;"
                                    onclick="navigator.clipboard.writeText(document.getElementById('sum-content-{sid}').innerText); alert('Resumo copiado!');">
                                📋 Copiar
                            </button>
                            <button type="button"
                                    class="btn-delete"
                                    style="padding: 4px 10px; font-size: 0.76rem;"
                                    hx-post="/summaries/{sid}/delete"
                                    hx-confirm="Deseja realmente excluir este resumo gerado por {prov_label}?"
                                    hx-target="#summaries-list-container"
                                    hx-swap="innerHTML">
                                🗑️ Excluir
                            </button>
                        </div>
                    </div>
                </div>

                {prompt_block}

                <!-- Texto do Resumo -->
                <div class="summary-body" style="background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 14px;">
                    <pre id="sum-content-{sid}" style="white-space: pre-wrap; word-break: break-word; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 0.9rem; line-height: 1.6; margin: 0;">{summary_text}</pre>
                </div>
            </div>
            """
        )

    return "".join(cards)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def summaries_page(
    request: Request,
    feed_id: int | None = None,
    provider: str | None = None,
):
    """Full page for browsing and managing all generated podcast summaries."""
    conn = get_db_connection()
    repo = Repository(conn)
    sub_lists = repo.list_all_lists()
    all_feeds = repo.list_feeds()
    all_models = ModelRegistry().list_models()

    clean_provider = provider.strip() if provider and provider.strip() != "all" else None
    summaries = repo.list_all_summaries(feed_id=feed_id, provider=clean_provider)
    conn.close()

    summaries_html = _render_summaries_list_html(
        summaries=summaries,
        selected_feed_id=feed_id,
        selected_provider=clean_provider,
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="summaries.html",
        context={
            "lists": sub_lists,
            "all_feeds": all_feeds,
            "models": all_models,
            "summaries": summaries,
            "summaries_count": len(summaries),
            "selected_feed_id": feed_id,
            "selected_provider": clean_provider or "all",
            "llm_providers": LLM_PROVIDERS,
            "summaries_list_html": summaries_html,
        },
    )


@router.get("/cards", response_class=Response)
def get_summaries_cards_partial(
    feed_id: int | None = None,
    provider: str | None = None,
):
    """HTMX partial endpoint for updating summary cards when filtering."""
    conn = get_db_connection()
    repo = Repository(conn)
    clean_provider = provider.strip() if provider and provider.strip() != "all" else None
    summaries = repo.list_all_summaries(feed_id=feed_id, provider=clean_provider)
    conn.close()

    html_content = _render_summaries_list_html(
        summaries=summaries,
        selected_feed_id=feed_id,
        selected_provider=clean_provider,
    )
    return Response(content=html_content, media_type="text/html")


@router.post("/{summary_id}/delete")
def delete_summary_route(
    summary_id: int,
    request: Request,
    feed_id: int | None = None,
    provider: str | None = None,
):
    """Delete a summary and refresh list."""
    conn = get_db_connection()
    repo = Repository(conn)
    deleted = repo.delete_summary(summary_id)
    if not deleted:
        conn.close()
        raise HTTPException(status_code=404, detail="Resumo não encontrado")

    clean_provider = provider.strip() if provider and provider.strip() != "all" else None
    remaining = repo.list_all_summaries(feed_id=feed_id, provider=clean_provider)
    conn.close()

    logger.info(f"[SUMMARIES] Resumo #{summary_id} excluído com sucesso.")

    if request.headers.get("hx-request"):
        html_content = _render_summaries_list_html(
            summaries=remaining,
            selected_feed_id=feed_id,
            selected_provider=clean_provider,
        )
        return Response(content=html_content, media_type="text/html")
    return {"ok": True, "deleted_id": summary_id}
