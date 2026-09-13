"""Central structured JSON logging for the agentic-assistant service.

Single sink for every module: JSON lines on stdout with timestamp, level,
logger, service, and message — mirroring services/api/main.py so logs look
identical across services. Call configure_logging() once at process start
(main.py); every other module just does `logger = logging.getLogger(__name__)`.

Never log secrets here or at call sites: passwords, tokens, JWT secrets, and
API keys must only appear as configured=True/False flags.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime


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


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Install the JSON handler on the root logger (idempotent)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(level)
    # Quiet noisy libraries — per-request detail comes from our own loggers.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return logging.getLogger("agentic-assistant")
