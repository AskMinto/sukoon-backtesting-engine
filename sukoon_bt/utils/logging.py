"""Structured logging — spec §23.

JSON-line output (one record per line) with timestamps + event kind +
context fields. Tiny implementation on top of stdlib ``logging`` so we
keep zero extra runtime deps for now; we can swap to structlog later if
the structured-output story gets richer.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from typing import Any

import orjson

LOGGER_NAME = "sukoon_bt"

_RESERVED_LOGRECORD_KEYS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message", "asctime",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_KEYS:
                continue
            if isinstance(value, (str, int, float, bool, type(None), list, dict)):
                payload[key] = value
            else:
                payload[key] = str(value)
        return orjson.dumps(payload).decode()


def configure(level: str = "INFO") -> logging.Logger:
    """Idempotently configure the sukoon_bt logger to write JSON lines to stderr."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")


__all__ = ["LOGGER_NAME", "JsonFormatter", "configure", "get_logger"]
