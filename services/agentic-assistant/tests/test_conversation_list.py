"""List-my-chats summaries: newest first, owner-scoped, derived preview."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from auth.tokens import mint_assistant_token
from fastapi.testclient import TestClient

import api.chat as chat_api
from agent.config import get_agent_settings
from main import app

SECRET = "test-assistant-secret"


class FakePool:
    @asynccontextmanager
    async def connection(self):
        yield object()


@pytest.fixture
def client(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "assistant_jwt_secret", SECRET)
    app.state.assistant_user_pool = FakePool()
    yield TestClient(app, raise_server_exceptions=False)
    app.state.assistant_user_pool = None


def _headers(user_id="u-1"):
    return {
        "Authorization": "Bearer "
        + mint_assistant_token(user_id=user_id, role="manager", secret=SECRET, ttl_seconds=600)
    }


class Result:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


class FakeListConnection:
    """Minimal async connection serving list + count + first-question queries."""

    def __init__(self, conversations, counts, first_questions):
        # conversations: list of (conversation_id, updated_at)
        # counts: {conversation_id: assistant_row_count}
        # first_questions: {conversation_id: content or None}
        self.conversations = conversations
        self.counts = counts
        self.first_questions = first_questions
        self.queries = []

    async def execute(self, sql, params=()):
        self.queries.append((sql, params))
        lowered = sql.lower()
        if "from assistant_conversations" in lowered and "order by updated_at desc" in lowered:
            return Result(self.conversations)
        if "count(*)" in lowered and "role = 'assistant'" in lowered:
            cid = params[0]
            return Result([(self.counts.get(cid, 0),)])
        if "role = 'user'" in lowered and "order by turn_index asc" in lowered:
            cid = params[0]
            content = self.first_questions.get(cid)
            return Result([(content,)] if content is not None else [])
        return Result([])


async def test_list_returns_newest_first_with_preview_and_turn_count():
    from models.conversations import async_list_conversations

    stamped_new = datetime(2026, 9, 14, 2, 0, tzinfo=UTC)
    stamped_old = datetime(2026, 9, 13, 2, 0, tzinfo=UTC)
    conn = FakeListConnection(
        conversations=[("c-new", stamped_new), ("c-old", stamped_old)],
        counts={"c-new": 3, "c-old": 1},
        first_questions={"c-new": "hello world", "c-old": "x" * 200},
    )
    rows = await async_list_conversations(conn, "u-1", limit=50)
    assert [r["conversation_id"] for r in rows] == ["c-new", "c-old"]
    assert rows[0]["turn_count"] == 3
    assert rows[0]["preview"] == "hello world"
    assert rows[0]["updated_at"] == stamped_new.isoformat()
    # long first message is cut to a short preview
    assert len(rows[1]["preview"]) <= 120
    assert rows[1]["preview"].startswith("x")


def test_list_route_returns_my_chats_newest_first(client, monkeypatch):
    async def fake_list(connection, owner, **kwargs):
        assert owner == "u-1"
        return [
            {
                "conversation_id": "c-new",
                "updated_at": "2026-09-14T02:00:00+00:00",
                "turn_count": 2,
                "preview": "hello world",
            }
        ]

    monkeypatch.setattr(chat_api, "async_list_conversations", fake_list)
    response = client.get("/conversations", headers=_headers())
    assert response.status_code == 200
    assert response.json() == [
        {
            "conversation_id": "c-new",
            "updated_at": "2026-09-14T02:00:00+00:00",
            "turn_count": 2,
            "preview": "hello world",
        }
    ]


def test_list_route_requires_auth(client):
    assert client.get("/conversations").status_code in (401, 403)


async def test_list_scopes_to_owner_and_handles_empty():
    from models.conversations import async_list_conversations

    conn = FakeListConnection(conversations=[], counts={}, first_questions={})
    assert await async_list_conversations(conn, "u-1") == []
    # owner_subject must be bound as a query param (no cross-user leak)
    assert any(
        "owner_subject" in sql.lower() and "u-1" in params
        for sql, params in conn.queries
        for params in [params]
    )
