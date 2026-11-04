"""Verbose terminal logging configuration for pod2bullets."""

import logging
import sys

from rich.console import Console
from rich.logging import RichHandler

_LOGGING_CONFIGURED = False


def setup_verbose_logging(level: int = logging.INFO) -> None:
    """Configure verbose, timestamped terminal logging for all background tasks and HTTP requests."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    console = Console(stderr=False, force_terminal=True)
    handler = RichHandler(
        console=console,
        show_time=True,
        show_level=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        markup=True,
    )
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s", datefmt="[%Y-%m-%d %H:%M:%S]"))

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Ensure pod2bullets and uvicorn loggers propagate and stay verbose
    for logger_name in (
        "pod2bullets",
        "pod2bullets.worker",
        "pod2bullets.downloader",
        "pod2bullets.transcriber",
        "pod2bullets.feeds",
        "pod2bullets.models",
        "pod2bullets.web",
        "uvicorn",
        "uvicorn.error",
    ):
        lg = logging.getLogger(logger_name)
        lg.setLevel(level)

    # Keep httpx / httpcore at WARNING unless debugging so chunk reads don't flood,
    # while our own downloader/feeds log every URL and progress clearly
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None
    _LOGGING_CONFIGURED = True
