"""WebSocket chat, ticket authentication, and conversation-history contracts."""

import asyncio
import threading
from contextlib import contextmanager

import pytest
from auth.tokens import mint_assistant_token
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import api.chat as chat_api
from agent.config import get_agent_settings
from main import app
from models.conversations import ConversationForbidden, ConversationNotFound

SECRET = "test-assistant-secret"


class FakePool:
    @contextmanager
    def connection(self):
        yield object()


@pytest.fixture
def client(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "assistant_jwt_secret", SECRET)
    app.state.assistant_user_pool = FakePool()
    yield TestClient(app, raise_server_exceptions=False)
    app.state.assistant_user_pool = None


def _headers(role="manager", user_id="u-1"):
    return {
        "Authorization": "Bearer "
        + mint_assistant_token(user_id=user_id, role=role, secret=SECRET, ttl_seconds=600)
    }


def test_websocket_streams_events_and_supports_multiple_requests(client, monkeypatch):
    async def fake_stream(pool, request, claims):
        yield {"type": "step", "text": "retrieved"}
        yield {"type": "token", "text": "hello"}
        yield {
            "type": "done",
            "conversation_id": request.conversation_id or "conversation-1",
            "sources": [],
            "grounded": True,
            "rewritten_question": None,
            "workflow_steps": ["done"],
        }

    monkeypatch.setattr(chat_api, "stream_chat", fake_stream)
    ticket = client.post("/auth/ws-ticket", headers=_headers()).json()["access_token"]

    with client.websocket_connect("/ask") as websocket:
        websocket.send_json({"type": "auth", "access_token": ticket})
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_json({"type": "ask", "request_id": "r-1", "question": "hello"})
        events = [websocket.receive_json() for _ in range(3)]
        assert [event["type"] for event in events] == ["step", "token", "done"]
        assert all(event["request_id"] == "r-1" for event in events)
        assert events[-1]["conversation_id"] == "conversation-1"

        websocket.send_json(
            {
                "type": "ask",
                "request_id": "r-2",
                "question": "follow-up",
                "conversation_id": "conversation-1",
            }
        )
        follow_up = [websocket.receive_json() for _ in range(3)]
        assert follow_up[-1]["request_id"] == "r-2"


def test_websocket_rejects_normal_jwt_as_ticket(client):
    with pytest.raises(WebSocketDisconnect) as error, client.websocket_connect("/ask") as websocket:
        websocket.send_json(
            {
                "type": "auth",
                "access_token": mint_assistant_token(user_id="u-1", role="manager", secret=SECRET),
            }
        )
        websocket.receive_json()
    assert error.value.code == 4401


def test_websocket_rejects_concurrent_request(client, monkeypatch):
    release = threading.Event()

    async def fake_stream(pool, request, claims):
        yield {"type": "step", "text": "started"}
        await asyncio.to_thread(release.wait)
        yield {
            "type": "done",
            "conversation_id": "conversation-1",
            "sources": [],
            "grounded": False,
            "rewritten_question": None,
            "workflow_steps": [],
        }

    monkeypatch.setattr(chat_api, "stream_chat", fake_stream)
    ticket = client.post("/auth/ws-ticket", headers=_headers()).json()["access_token"]

    with client.websocket_connect("/ask") as websocket:
        websocket.send_json({"type": "auth", "access_token": ticket})
        websocket.receive_json()
        websocket.send_json({"type": "ask", "request_id": "r-1", "question": "one"})
        assert websocket.receive_json()["type"] == "step"
        websocket.send_json({"type": "ask", "request_id": "r-2", "question": "two"})
        busy = websocket.receive_json()
        assert busy["code"] == "request_in_progress"
        release.set()
        assert websocket.receive_json()["type"] == "done"


def test_history_route_requires_owner_and_returns_full_history(client, monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "get_full_history",
        lambda connection, conversation_id, owner: [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )
    response = client.get("/conversations/c-1", headers=_headers())
    assert response.status_code == 200
    assert response.json() == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


@pytest.mark.parametrize(
    "error,status_code",
    [(ConversationNotFound, 404), (ConversationForbidden, 403)],
)
def test_history_route_hides_storage_errors_as_contract(client, monkeypatch, error, status_code):
    def fail(*args):
        raise error("c-1")

    monkeypatch.setattr(chat_api, "get_full_history", fail)
    response = client.get("/conversations/c-1", headers=_headers())
    assert response.status_code == status_code
