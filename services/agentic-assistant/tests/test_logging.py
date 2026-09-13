"""Logging: formatter shapes + format selection."""

import json
import logging

from agent.logging_config import JSONFormatter, PrettyFormatter, _resolve_format, configure_logging


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
    configure_logging(log_format="json")
    configure_logging(log_format="json")
    assert len(logging.root.handlers) == 1
    assert isinstance(logging.root.handlers[0].formatter, JSONFormatter)


def test_pretty_formatter_single_line_no_color():
    record = logging.LogRecord(
        "agent.graph.nodes.chitchat", logging.INFO, __file__, 1, "node done answer_len=%d", (34,), None
    )
    line = PrettyFormatter(use_color=False).format(record)
    assert "\n" not in line
    assert "chitchat" in line
    assert "agent.graph.nodes.chitchat" not in line
    assert "answer_len=34" in line
    assert "INFO" in line


def test_pretty_short_name():
    assert PrettyFormatter.short_name("agent.llm") == "llm"
    assert PrettyFormatter.short_name("service") == "service"


def test_resolve_format_explicit_and_fallback(monkeypatch):
    assert _resolve_format("pretty") == "pretty"
    assert _resolve_format("json") == "json"
    assert _resolve_format("bogus") == "json"
    monkeypatch.setenv("AGENTIC_ASSISTANT_LOG_FORMAT", "pretty")
    assert _resolve_format(None) == "pretty"


def test_configure_logging_pretty_installs_pretty_formatter():
    configure_logging(log_format="pretty")
    assert isinstance(logging.root.handlers[0].formatter, PrettyFormatter)
