"""Web routes for real-time Log Viewer (APP bash log and Transcription log)."""

from fastapi import APIRouter

from pod2bullets.config import settings
from pod2bullets.logging_config import get_active_log_paths, read_log_tail

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/tail")
def get_log_tail(log_type: str = "app"):
    """Return latest content of the active APP or Transcription log without polluting logs."""
    data = read_log_tail(log_type=log_type)
    paths = get_active_log_paths()
    return {
        "log_type": log_type,
        "filename": data["filename"],
        "content": data["content"],
        "active_files": {
            "app": paths["app"].name,
            "transcricao": paths["transcricao"].name,
        },
    }


@router.get("/files")
def list_all_log_files():
    """List all log files in the logs/ folder sorted newest first."""
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(
        settings.logs_dir.glob("*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "name": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
        }
        for f in files
    ]
