"""Startup and shutdown behavior for the assistant user pool."""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import main
from agent.config import get_agent_settings
from main import app


class FakePool:
    def __init__(self):
        self.closed = False

    @contextmanager
    def connection(self):
        yield object()

    def close(self):
        self.closed = True


def test_configured_pool_is_seeded_and_closed(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "agentic_assistant_database_url", "postgresql://db")
    monkeypatch.setattr(settings, "agentic_assistant_admin_email", "root@example.com")
    monkeypatch.setattr(settings, "agentic_assistant_admin_password", "password")
    pool = FakePool()
    seeded = []
    monkeypatch.setattr(main, "get_pool", lambda url: pool)
    monkeypatch.setattr(
        main,
        "ensure_and_seed",
        lambda connection, email, password: seeded.append((email, password)),
    )
    monkeypatch.setattr(main, "ensure_conversation_tables", lambda connection: None)

    with TestClient(app):
        assert app.state.assistant_user_pool is pool

    assert seeded == [("root@example.com", "password")]
    assert pool.closed is True
    assert app.state.assistant_user_pool is None


def test_unreachable_configured_database_fails_startup(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "agentic_assistant_database_url", "postgresql://db")
    monkeypatch.setattr(
        main, "get_pool", lambda url: (_ for _ in ()).throw(RuntimeError("db down"))
    )

    with pytest.raises(RuntimeError, match="db down"), TestClient(app):
        pass
