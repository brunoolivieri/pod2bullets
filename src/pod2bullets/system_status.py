"""Global system busy state tracker for UI hourglass indicator and verbose monitoring."""

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection


@dataclass
class SystemStatusInfo:
    is_busy: bool
    label: str
    detail: str = ""
    progress_percent: float | None = None
    active_count: int = 0

    @property
    def primary(self) -> str:
        return self.detail or self.label

    @property
    def count(self) -> int:
        return self.active_count

    def __getitem__(self, item: str) -> Any:
        if item == "primary":
            return self.primary
        if item == "count":
            return self.count
        return getattr(self, item)


class ActivityTracker:
    """Thread-safe registry of active in-memory tasks (model downloads, feed syncs, OPML imports)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, str] = {}

    def set_task(self, key: str, description: str) -> None:
        with self._lock:
            self._tasks[key] = description

    def start(self, key: str, description: str) -> None:
        self.set_task(key, description)

    def update(self, key: str, description: str | None = None, **kwargs: Any) -> None:
        if description is not None:
            self.set_task(key, description)

    def remove_task(self, key: str) -> None:
        with self._lock:
            self._tasks.pop(key, None)

    def finish(self, key: str) -> None:
        self.remove_task(key)

    def list_tasks(self) -> list[str]:
        with self._lock:
            return list(self._tasks.values())

    def list_active(self) -> list[dict[str, str]]:
        with self._lock:
            return [{"key": k, "description": v} for k, v in self._tasks.items()]


activity_tracker = ActivityTracker()


def get_system_status(db_path: Path | None = None) -> SystemStatusInfo:
    """Inspect active in-memory tasks and SQLite background jobs to determine if the system is busy."""
    mem_tasks = activity_tracker.list_tasks()
    active_jobs: list[dict] = []

    try:
        conn = get_db_connection(db_path or settings.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT j.id, j.job_type, j.status, j.progress_percent, j.model_id, e.title AS episode_title, e.status AS ep_status
            FROM jobs j
            LEFT JOIN episodes e ON e.id = j.episode_id
            WHERE j.status IN ('pending', 'running')
            ORDER BY CASE WHEN j.status = 'running' THEN 0 ELSE 1 END, j.id ASC
            """
        )
        active_jobs = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception:
        active_jobs = []

    total_active = len(mem_tasks) + len(active_jobs)
    if total_active == 0:
        return SystemStatusInfo(
            is_busy=False,
            label="Sistema Livre",
            detail="Nenhuma tarefa em segundo plano",
            active_count=0,
        )

    # Prioritize showing active in-memory task (e.g. model installation) or running job
    if mem_tasks:
        main_desc = mem_tasks[0]
        extra = f" (+{total_active - 1} na fila)" if total_active > 1 else ""
        return SystemStatusInfo(
            is_busy=True,
            label=f"Ocupado: {main_desc}{extra}",
            detail=main_desc,
            active_count=total_active,
        )

    top_job = active_jobs[0]
    ep_title = (top_job.get("episode_title") or f"Episódio #{top_job['id']}")[:40]
    ep_status = top_job.get("ep_status") or ""
    pct = round(float(top_job.get("progress_percent") or 0.0), 1)
    model_id = top_job.get("model_id") or settings.default_model_id

    if ep_status == "transcribing" or pct >= 50.0:
        action = f"Transcrevendo ({model_id}): {ep_title} ({pct}%)"
    elif top_job.get("status") == "running":
        action = f"Baixando áudio: {ep_title} ({pct}%)"
    else:
        action = f"Na fila: {ep_title}"

    extra = f" [+{total_active - 1}]" if total_active > 1 else ""
    return SystemStatusInfo(
        is_busy=True,
        label=f"{action}{extra}",
        detail=action,
        progress_percent=pct,
        active_count=total_active,
    )
