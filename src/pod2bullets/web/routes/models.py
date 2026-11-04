"""Transcription models selection, discovery and local download routes."""

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Response
from huggingface_hub import snapshot_download

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection
from pod2bullets.transcriber.registry import CATALOG, ModelRegistry

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/")
def list_models():
    registry = ModelRegistry()
    return registry.list_models()


@router.post("/default")
def set_default_model(model_id: str = Form(...)):
    registry = ModelRegistry()
    info = registry.get_model_info(model_id)
    if not info:
        return {"error": "Modelo não encontrado"}
    settings.default_model_id = model_id
    return {"default_model_id": settings.default_model_id}


@router.delete("/{model_id}")
def uninstall_model_endpoint(model_id: str):
    """Uninstall and delete model weights from local disk."""
    registry = ModelRegistry()
    success = registry.uninstall_model(model_id)
    if not success:
        raise HTTPException(status_code=404, detail="Modelo não encontrado ou já desinstalado")
    return {"ok": True, "model_id": model_id}


@router.post("/{model_id}/download")
def download_model_local(model_id: str, background_tasks: BackgroundTasks):
    meta = CATALOG.get(model_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Modelo não encontrado")

    dest_dir = settings.models_dir / model_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Retrieve saved token if any
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = 'hf_token'")
    row = cur.fetchone()
    hf_token = row["value"] if row else None
    conn.close()

    def run_snapshot():
        try:
            snapshot_download(
                repo_id=meta["repo"],
                local_dir=str(dest_dir),
                token=hf_token,
                local_dir_use_symlinks=False,
            )
        except Exception as e:
            print(f"Erro ao baixar modelo {model_id}: {e}")

    background_tasks.add_task(run_snapshot)

    return Response(
        content=f"""
        <div class="model-card" id="model-card-{model_id}">
            <div class="model-info">
                <h3>{meta["name"]}</h3>
                <p>{meta["desc"]}</p>
                <span class="model-size">Tamanho em disco: ~{meta["size_mb"]} MB</span>
            </div>
            <div class="model-actions">
                <span class="badge-downloading" style="color: #60a5fa; font-weight: 600;">
                    ⏳ Baixando arquivos para disco local...
                </span>
            </div>
        </div>
        """,
        media_type="text/html",
    )
