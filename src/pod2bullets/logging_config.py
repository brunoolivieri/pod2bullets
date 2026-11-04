"""Dual logging configuration (APP bash log + Transcription log) and polling suppression."""

import io
import logging
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from pod2bullets.config import settings

_LOGGING_CONFIGURED = False
_SESSION_TIMESTAMP: str | None = None
_FILE_LOCK = threading.Lock()

# ANSI escape sequence regex so the APP log file has clean readable text
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# High-frequency polling paths whose 200 OK logs must be suppressed (Item 12)
SUPPRESSED_POLLING_PATHS = (
    "/episodes/card/",
    "/system/status",
    "/models/card/",
    "/logs/tail",
)


def is_suppressed_polling_line(text: str) -> bool:
    """Return True if a log line or terminal line is a 200 OK poll that should be suppressed."""
    if not any(p in text for p in SUPPRESSED_POLLING_PATHS):
        return False
    return "200" in text


class PollingLogFilter(logging.Filter):
    """Filter out noisy 200 OK polling requests from uvicorn.access and pod2bullets.web."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if is_suppressed_polling_line(msg):
            return False
        return True


def get_active_log_paths() -> dict[str, Path]:
    """Return paths for the active APP log and Transcription log (`YYYY-MM-DD-HH-MM-APP` and `transcricao`)."""
    global _SESSION_TIMESTAMP
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    if _SESSION_TIMESTAMP is None:
        _SESSION_TIMESTAMP = datetime.now().strftime("%Y-%m-%d-%H-%M")

    app_log_path = settings.logs_dir / f"{_SESSION_TIMESTAMP}-APP.log"
    tx_log_path = settings.logs_dir / f"{_SESSION_TIMESTAMP}-transcricao.log"

    if not app_log_path.exists():
        app_log_path.write_text(
            f"=== Log de Sistema (APP) iniciado em {_SESSION_TIMESTAMP} ===\n",
            encoding="utf-8",
        )
    if not tx_log_path.exists():
        tx_log_path.write_text(
            f"=== Log de Transcrições iniciado em {_SESSION_TIMESTAMP} ===\n",
            encoding="utf-8",
        )
    return {
        "app": app_log_path,
        "transcricao": tx_log_path,
    }


def append_to_app_log(text: str) -> None:
    """Append clean text to the active YYYY-MM-DD-HH-MM-APP.log file."""
    if not text or is_suppressed_polling_line(text):
        return
    clean_text = _ANSI_ESCAPE_RE.sub("", text)
    if not clean_text:
        return
    try:
        with _FILE_LOCK:
            app_log_path = get_active_log_paths()["app"]
            with open(app_log_path, "a", encoding="utf-8") as f:
                f.write(clean_text)
    except Exception:
        pass


def append_to_transcription_log(text: str) -> None:
    """Append a formatted line to the active YYYY-MM-DD-HH-MM-transcricao.log file."""
    if not text:
        return
    try:
        with _FILE_LOCK:
            tx_log_path = get_active_log_paths()["transcricao"]
            with open(tx_log_path, "a", encoding="utf-8") as f:
                f.write(text if text.endswith("\n") else text + "\n")
    except Exception:
        pass


class TeeBashStream(io.TextIOBase):
    """Mirrors everything printed to stdout/stderr into the YYYY-MM-DD-HH-MM-APP.log file."""

    def __init__(self, original_stream: io.TextIOBase):
        self._original = original_stream

    def write(self, s: str) -> int:
        if not s:
            return 0
        if is_suppressed_polling_line(s):
            return len(s)

        written = len(s)
        try:
            written = self._original.write(s)
        except Exception:
            pass
        append_to_app_log(s)
        return written

    def flush(self) -> None:
        try:
            self._original.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return getattr(self._original, "isatty", lambda: False)()
        except Exception:
            return False

    @property
    def encoding(self) -> str:
        return getattr(self._original, "encoding", "utf-8")


class DynamicAppLogHandler(logging.Handler):
    """Ensures all Python log records also go to YYYY-MM-DD-HH-MM-APP.log even if stdout isn't wrapped."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if not is_suppressed_polling_line(msg):
                append_to_app_log(msg + "\n")
        except Exception:
            pass


class DynamicTranscriptionLogHandler(logging.Handler):
    """Writes all transcription, worker, downloader, and LLM log records to YYYY-MM-DD-HH-MM-transcricao.log."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            append_to_transcription_log(msg)
        except Exception:
            pass


def setup_verbose_logging(level: int = logging.INFO, wrap_stdio: bool = False) -> None:
    """Configure verbose terminal output, bash Tee into YYYY-MM-DD-HH-MM-APP.log, and YYYY-MM-DD-HH-MM-transcricao.log."""
    global _LOGGING_CONFIGURED
    get_active_log_paths()

    poll_filter = PollingLogFilter()
    logging.getLogger("uvicorn.access").addFilter(poll_filter)
    logging.getLogger("pod2bullets.web").addFilter(poll_filter)

    if wrap_stdio and not isinstance(sys.stdout, TeeBashStream):
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(line_buffering=True)
            except Exception:
                pass
        sys.stdout = TeeBashStream(sys.stdout)  # type: ignore[assignment]
    if wrap_stdio and not isinstance(sys.stderr, TeeBashStream):
        sys.stderr = TeeBashStream(sys.stderr)  # type: ignore[assignment]

    if _LOGGING_CONFIGURED:
        return

    console = Console(stderr=False, force_terminal=True)
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_level=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        markup=True,
    )
    rich_handler.setFormatter(
        logging.Formatter("%(name)s: %(message)s", datefmt="[%Y-%m-%d %H:%M:%S]")
    )
    rich_handler.addFilter(poll_filter)

    app_file_handler = DynamicAppLogHandler(level=logging.INFO)
    app_file_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    app_file_handler.addFilter(poll_filter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(rich_handler)
    root_logger.addHandler(app_file_handler)

    tx_file_handler = DynamicTranscriptionLogHandler(level=logging.INFO)
    tx_file_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    for tx_logger_name in (
        "pod2bullets.transcriber",
        "pod2bullets.worker",
        "pod2bullets.downloader",
        "pod2bullets.llm",
    ):
        tx_lg = logging.getLogger(tx_logger_name)
        tx_lg.setLevel(level)
        if not any(isinstance(h, DynamicTranscriptionLogHandler) for h in tx_lg.handlers):
            tx_lg.addHandler(tx_file_handler)

    for logger_name in (
        "pod2bullets",
        "pod2bullets.feeds",
        "pod2bullets.models",
        "pod2bullets.web",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ):
        lg = logging.getLogger(logger_name)
        lg.setLevel(level)
        lg.addFilter(poll_filter)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _LOGGING_CONFIGURED = True


def read_log_tail(log_type: str = "app", max_chars: int = 35000) -> dict[str, str]:
    """Read the tail of the active APP or Transcription log file for the live Log Viewer."""
    paths = get_active_log_paths()
    target = paths["transcricao"] if log_type == "transcricao" else paths["app"]
    if not target.exists():
        return {"filename": target.name, "content": ""}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = "... [início truncado para visualização rápida] ...\n" + text[-max_chars:]
        return {"filename": target.name, "content": text}
    except Exception as e:
        return {"filename": target.name, "content": f"Erro ao ler log: {e}"}
