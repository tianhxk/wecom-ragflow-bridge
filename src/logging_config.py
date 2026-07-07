"""Application logging configuration."""

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


DEFAULT_LOG_FILE = "logs/wecom-ragflow-bridge.log"
DEFAULT_LOG_RETENTION_DAYS = 30
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s"


def _positive_int(name: str, default: int) -> int:
    value = os.environ.get(name, "")
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def configure_logging() -> tuple[int, Path]:
    """Configure console and rotating file handlers for the root logger."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO

    log_file = Path(os.environ.get("LOG_FILE") or DEFAULT_LOG_FILE).expanduser()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    retention_days = _positive_int("LOG_RETENTION_DAYS", DEFAULT_LOG_RETENTION_DAYS)
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=max(0, retention_days - 1),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=level,
        handlers=[console_handler, file_handler],
        force=True,
    )
    return level, log_file.resolve()
