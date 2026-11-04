"""SQLite connection manager with WAL mode, migrations and row factory."""

import logging
import sqlite3
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Generator

from pod2bullets.config import settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
logger = logging.getLogger("pod2bullets.db")


def get_db_connection(db_path: Path | None = None) -> sqlite3.Connection:
    target_path = db_path or settings.db_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode and foreign keys
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path | None = None) -> None:
    conn = get_db_connection(db_path)
    with conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        # Migrate existing episodes table if image_url column is missing
        cols = [r[1] for r in conn.execute("PRAGMA table_info(episodes)").fetchall()]
        if "image_url" not in cols:
            logger.info("[DB] Adicionando coluna 'image_url' na tabela episodes...")
            conn.execute("ALTER TABLE episodes ADD COLUMN image_url TEXT;")
            conn.execute(
                """
                UPDATE episodes
                SET image_url = (SELECT f.image_url FROM feeds f WHERE f.id = episodes.feed_id)
                WHERE image_url IS NULL
                """
            )

        # Normalize RFC-2822 published_at dates to ISO-8601 so ORDER BY published_at DESC sorts newest first
        rows = conn.execute(
            "SELECT id, published_at FROM episodes WHERE published_at IS NOT NULL AND published_at NOT LIKE '20%' AND published_at NOT LIKE '19%'"
        ).fetchall()
        if rows:
            logger.info(
                f"[DB] Normalizando {len(rows)} datas de publicação de episódios para ISO-8601..."
            )
            updates = []
            for r in rows:
                try:
                    dt = parsedate_to_datetime(r["published_at"])
                    updates.append((dt.isoformat(), r["id"]))
                except Exception:
                    pass
            if updates:
                conn.executemany("UPDATE episodes SET published_at = ? WHERE id = ?", updates)

        # Clean up any stale running jobs from an interrupted previous server session
        conn.execute(
            "UPDATE jobs SET status = 'failed', error_message = 'Interrompido ao reiniciar servidor' WHERE status = 'running'"
        )
    conn.close()


@contextmanager
def db_session(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    conn = get_db_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
