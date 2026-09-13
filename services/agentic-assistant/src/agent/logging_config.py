"""Central logging for the agentic-assistant service.

Single sink for every module, two renderings:

- ``json``   — one JSON object per line (timestamp, level, logger, service,
  message), mirroring services/api/main.py. This is the production format:
  aggregators and Railway log drains parse it.
- ``pretty`` — one short human line per event
  (``02:16:20 INFO chitchat node chitchat: done answer_len=34``), with ANSI
  colour when attached to a terminal. For local dev readability.

Selection via ``AGENTIC_ASSISTANT_LOG_FORMAT``: ``auto`` (default), ``json``,
or ``pretty``. ``auto`` picks ``pretty`` when stdout is a TTY and ``json``
otherwise, so local runs are readable and deployed logs stay structured.

Call configure_logging() once at process start (main.py); every other module
just does ``logger = logging.getLogger(__name__)``.

Never log secrets here or at call sites: passwords, tokens, JWT secrets, and
API keys must only appear as configured=True/False flags.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import ClassVar


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": "agentic-assistant",
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
            log_entry["traceback"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


class PrettyFormatter(logging.Formatter):
    """Single-line human rendering: time, level, short module, message."""

    _COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "\x1b[36m",  # cyan
        "INFO": "\x1b[32m",  # green
        "WARNING": "\x1b[33m",  # yellow
        "ERROR": "\x1b[31m",  # red
        "CRITICAL": "\x1b[35m",  # magenta
    }
    _RESET = "\x1b[0m"
    _DIM = "\x1b[2m"

    def __init__(self, use_color: bool = True) -> None:
        super().__init__()
        self.use_color = use_color

    @staticmethod
    def short_name(logger_name: str) -> str:
        """Collapse dotted paths to the last segment: a.b.chitchat -> chitchat."""
        return logger_name.split(".")[-1] if logger_name else logger_name

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S.%f")[:-3]
        name = self.short_name(record.name)
        level = record.levelname
        if self.use_color:
            color = self._COLORS.get(level, "")
            line = (
                f"{self._DIM}{timestamp}{self._RESET} "
                f"{color}{level:<7}{self._RESET} "
                f"{self._DIM}{name:<14}{self._RESET} {record.getMessage()}"
            )
        else:
            line = f"{timestamp} {level:<7} {name:<14} {record.getMessage()}"
        if record.exc_info and record.exc_info[1]:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _resolve_format(explicit: str | None) -> str:
    """Normalise the requested format; unknown values fall back to json."""
    requested = (explicit or os.environ.get("AGENTIC_ASSISTANT_LOG_FORMAT", "auto")).lower()
    if requested == "auto":
        return "pretty" if sys.stdout.isatty() else "json"
    return requested if requested in ("json", "pretty") else "json"


def configure_logging(
    level: int = logging.INFO, log_format: str | None = None
) -> logging.Logger:
    """Install the selected handler on the root logger (idempotent)."""
    resolved = _resolve_format(log_format)
    handler = logging.StreamHandler(sys.stdout)
    if resolved == "pretty":
        handler.setFormatter(PrettyFormatter(use_color=sys.stdout.isatty()))
    else:
        handler.setFormatter(JSONFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(level)
    # Quiet noisy libraries — per-request detail comes from our own loggers.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logger = logging.getLogger("agentic-assistant")
    logger.info("logging ready: format=%s", resolved)
    return logger
