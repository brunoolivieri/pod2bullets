"""Transcription models selection, discovery and local installation routes."""

import logging
import threading

from fastapi import APIRouter, Form, HTTPException, Request, Response

from pod2bullets.config import settings
from pod2bullets.system_status import activity_tracker
from pod2bullets.transcriber.registry import CATALOG, ModelRegistry

logger = logging.getLogger("pod2bullets.web.models")

router = APIRouter(prefix="/models", tags=["models"])


def _render_model_card_html(model_id: str) -> str:
    registry = ModelRegistry()
    info = registry.get_model_info(model_id)
    if not info:
        return ""

    tasks = activity_tracker.list_active()
    installing_task = next((t for t in tasks if t["key"] == f"model_install:{model_id}"), None)

    default_badge = "★ (Padrão Ativo)" if info.is_default else ""
    if installing_task:
        actions_html = f"""
        <div class="status-box downloading"
             hx-get="/models/card/{info.id}"
             hx-trigger="every 1.5s"
             hx-target="#model-card-{info.id}"
             hx-swap="outerHTML">
            <div><span class="hourglass-icon">⏳</span> {installing_task["description"]}</div>
            <div class="progress-bar-container">
                <div class="progress-bar-fill" style="width: 60%;"></div>
            </div>
        </div>
        """
    elif info.is_installed:
        actions_html = f"""
        <div style="display: flex; gap: 10px; align-items: center;">
            <span class="badge-installed">✅ Instalado (~{info.size_mb} MB)</span>
            <button class="btn-delete"
                    hx-delete="/models/{info.id}"
                    hx-confirm="Deseja realmente desinstalar este modelo e liberar espaço em disco?"
                    hx-target="#model-card-{info.id}"
                    hx-swap="outerHTML">
                🗑️ Desinstalar
            </button>
        </div>
        """
    else:
        actions_html = f"""
        <form hx-post="/models/{info.id}/download"
              hx-target="#model-card-{info.id}"
              hx-swap="outerHTML">
            <button type="submit" class="btn-download" style="width: auto;">
                ⬇️ Instalar Localmente (~{info.size_mb} MB)
            </button>
        </form>
        """

    return f"""
    <div class="model-card" id="model-card-{info.id}">
        <div class="model-info">
            <h3>{info.name} {default_badge}</h3>
            <p>{info.description}</p>
            <span class="model-size">
                Tamanho em disco: <strong>~{info.size_mb} MB</strong> | Engine: <code>{info.engine_name}</code>
            </span>
        </div>
        <div class="model-actions">
            {actions_html}
        </div>
    </div>
    """


@router.get("/")
def list_models():
    registry = ModelRegistry()
    return registry.list_models()


@router.get("/card/{model_id}", response_class=Response)
def get_model_card(model_id: str):
    html = _render_model_card_html(model_id)
    if not html:
        raise HTTPException(status_code=404, detail="Modelo não encontrado")
    return Response(content=html, media_type="text/html")


@router.post("/default")
def set_default_model(model_id: str = Form(...)):
    registry = ModelRegistry()
    info = registry.get_model_info(model_id)
    if not info:
        return {"error": "Modelo não encontrado"}
    settings.default_model_id = model_id
    logger.info(f"[MODEL] Modelo ASR padrão alterado para: {model_id}")
    return {"default_model_id": settings.default_model_id}


@router.delete("/{model_id}")
def uninstall_model_endpoint(model_id: str, request: Request):
    """Uninstall and delete model weights from local disk."""
    registry = ModelRegistry()
    logger.info(f"[MODEL] Solicitação para desinstalar modelo '{model_id}'...")
    success = registry.uninstall_model(model_id)
    if not success:
        raise HTTPException(status_code=404, detail="Modelo não encontrado ou já desinstalado")
    if request.headers.get("hx-request"):
        return Response(content=_render_model_card_html(model_id), media_type="text/html")
    return {"ok": True, "model_id": model_id}


@router.post("/{model_id}/download")
def download_model_local(model_id: str):
    meta = CATALOG.get(model_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Modelo não encontrado")

    registry = ModelRegistry()
    logger.info(f"[MODEL] Disparando instalação em background do modelo '{model_id}'...")

    def _run_install():
        try:
            registry.install_model(model_id)
        except Exception as e:
            logger.error(f"[MODEL] Falha ao instalar '{model_id}': {e}", exc_info=True)

    threading.Thread(target=_run_install, name=f"install-{model_id}", daemon=True).start()

    return Response(
        content=f"""
        <div class="model-card" id="model-card-{model_id}">
            <div class="model-info">
                <h3>{meta["name"]}</h3>
                <p>{meta["desc"]}</p>
                <span class="model-size">
                    Tamanho estimado: <strong>~{meta["size_mb"]} MB</strong> | Engine: <code>{meta["engine"]}</code>
                </span>
            </div>
            <div class="model-actions">
                <div class="status-box downloading"
                     hx-get="/models/card/{model_id}"
                     hx-trigger="every 1.5s"
                     hx-target="#model-card-{model_id}"
                     hx-swap="outerHTML">
                    <div><span class="hourglass-icon">⏳</span> Instalando modelo localmente...</div>
                    <div class="progress-bar-container">
                        <div class="progress-bar-fill" style="width: 25%;"></div>
                    </div>
                </div>
            </div>
        </div>
        """,
        media_type="text/html",
    )
