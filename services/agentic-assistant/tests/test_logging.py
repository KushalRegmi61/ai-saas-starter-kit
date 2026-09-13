"""Structured JSON logging: formatter shape + no-secret settings log."""

import json
import logging

from agent.logging_config import JSONFormatter, configure_logging


def test_json_formatter_shape():
    record = logging.LogRecord("agent.llm", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    line = JSONFormatter().format(record)
    entry = json.loads(line)
    assert entry["level"] == "INFO"
    assert entry["logger"] == "agent.llm"
    assert entry["service"] == "agentic-assistant"
    assert entry["message"] == "hello world"
    assert "timestamp" in entry


def test_configure_logging_installs_single_handler():
    configure_logging()
    configure_logging()
    assert len(logging.root.handlers) == 1
    assert isinstance(logging.root.handlers[0].formatter, JSONFormatter)
