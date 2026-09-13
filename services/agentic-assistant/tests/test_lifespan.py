"""Startup and shutdown behavior for the assistant user pool."""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

import main
from agent.config import get_agent_settings
from main import app


class FakePool:
    def __init__(self):
        self.closed = False

    @asynccontextmanager
    async def connection(self):
        yield self.Connection()

    class Connection:
        async def commit(self):
            return None

    async def close(self):
        self.closed = True

    async def open(self, wait=False):
        return None


def test_configured_pool_is_seeded_and_closed(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "agentic_assistant_database_url", "postgresql://db")
    monkeypatch.setattr(settings, "agentic_assistant_admin_email", "root@example.com")
    monkeypatch.setattr(settings, "agentic_assistant_admin_password", "password")
    pool = FakePool()
    seeded = []

    async def get_pool(url):
        return pool

    monkeypatch.setattr(main, "get_async_pool", get_pool)
    monkeypatch.setattr(
        main,
        "ensure_and_seed_async",
        lambda connection, email, password: _record_seed(seeded, email, password),
    )

    async def ensure_tables(connection):
        return None

    monkeypatch.setattr(main, "ensure_conversation_tables_async", ensure_tables)
    monkeypatch.setattr(main, "ensure_project_tables_async", ensure_tables)
    monkeypatch.setattr(main, "ensure_project_token_tables_async", ensure_tables)

    with TestClient(app):
        assert app.state.assistant_user_pool is pool

    assert seeded == [("root@example.com", "password")]
    assert pool.closed is True
    assert app.state.assistant_user_pool is None


def test_unreachable_configured_database_fails_startup(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "agentic_assistant_database_url", "postgresql://db")
    monkeypatch.setattr(main, "get_async_pool", lambda url: _raise_async("db down"))

    with pytest.raises(RuntimeError, match="db down"), TestClient(app):
        pass


async def _raise_async(message):
    raise RuntimeError(message)


async def _record_seed(seeded, email, password):
    seeded.append((email, password))


def test_project_table_failure_fails_startup(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "agentic_assistant_database_url", "postgresql://db")
    pool = FakePool()

    async def get_pool(url):
        return pool

    async def fail_project_tables(connection):
        raise RuntimeError("project schema unavailable")

    async def seed_noop(connection, email, password):
        return None

    async def conversation_noop(connection):
        return None

    monkeypatch.setattr(main, "get_async_pool", get_pool)
    monkeypatch.setattr(main, "ensure_and_seed_async", seed_noop)
    monkeypatch.setattr(main, "ensure_conversation_tables_async", conversation_noop)
    monkeypatch.setattr(main, "ensure_project_tables_async", fail_project_tables)
    monkeypatch.setattr(main, "ensure_project_token_tables_async", conversation_noop)

    with pytest.raises(RuntimeError, match="project schema unavailable"), TestClient(app):
        pass
