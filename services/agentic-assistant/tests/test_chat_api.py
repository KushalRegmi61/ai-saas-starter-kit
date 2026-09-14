"""WebSocket chat, ticket authentication, and conversation-history contracts."""

import asyncio
import threading
from contextlib import asynccontextmanager

import pytest
from auth.tokens import mint_assistant_token
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import api.chat as chat_api
import service.chat as service_chat
from agent.config import get_agent_settings
from agent.types import AskRequest
from main import app
from models.conversations import (
    ConversationForbidden,
    ConversationNotFound,
    ConversationSnapshot,
)
from service.memory import PreparedMemory

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


def _headers(role="manager", user_id="u-1"):
    return {
        "Authorization": "Bearer "
        + mint_assistant_token(user_id=user_id, role=role, secret=SECRET, ttl_seconds=600)
    }


def test_websocket_streams_events_and_supports_multiple_requests(client, monkeypatch):
    async def fake_stream(pool, request, claims):
        yield {"type": "step", "text": "retrieved"}
        yield {"type": "token", "content": "hello"}
        yield {
            "type": "done",
            "conversation_id": request.conversation_id or "conversation-1",
            "answer": "hello",
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
        assert events[1]["content"] == "hello"
        assert events[-1]["conversation_id"] == "conversation-1"
        assert events[-1]["answer"] == "hello"

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
            "answer": "later",
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
    async def fake_history(connection, conversation_id, owner):
        return [
            {
                "turn_index": 0,
                "question": "hello",
                "answer": "hi",
                "sources": [],
                "created_at": None,
            },
        ]

    monkeypatch.setattr(chat_api, "async_get_full_history", fake_history)
    response = client.get("/conversations/c-1", headers=_headers())
    assert response.status_code == 200
    assert response.json() == [
        {
            "turn_index": 0,
            "question": "hello",
            "answer": "hi",
            "sources": [],
            "created_at": None,
        },
    ]


@pytest.mark.parametrize(
    "error,status_code",
    [(ConversationNotFound, 404), (ConversationForbidden, 403)],
)
def test_history_route_hides_storage_errors_as_contract(client, monkeypatch, error, status_code):
    async def fail(*args):
        raise error("c-1")

    monkeypatch.setattr(chat_api, "async_get_full_history", fail)
    response = client.get("/conversations/c-1", headers=_headers())
    assert response.status_code == status_code


class _FakeConnection:
    async def commit(self):
        return None

    @asynccontextmanager
    async def transaction(self):
        yield self


class _FakeChatPool:
    @asynccontextmanager
    async def connection(self):
        yield _FakeConnection()


@asynccontextmanager
async def _noop_lock(connection, conversation_id):
    yield None


def _patch_stream_chat(monkeypatch):
    """Install storage/memory/graph fakes for service.stream_chat; return call log."""
    calls = {"loaded": [], "appended": []}

    async def fake_graph(question, **kwargs):
        yield {"type": "step", "name": "classify_intent", "text": "classifying intent"}
        yield {"type": "token", "content": "hi "}
        yield {"type": "token", "content": "there"}
        yield {
            "type": "done",
            "answer": "hi there",
            "sources": [],
            "project_evidence": [
                {
                    "tool": "get_project_blockers",
                    "status": "resolved",
                    "project_name": "Workalay",
                    "result_count": 0,
                    "summary": {"open_blocker_count": 0},
                    "records": [],
                }
            ],
            "grounded": False,
            "rewritten_question": None,
            "workflow_steps": ["classify", "chitchat_respond"],
        }

    async def fake_prepare(snapshot):
        return PreparedMemory(
            summary="",
            turns=[],
            summary_through_turn=-1,
            last_turn_index=-1,
            changed=False,
        )

    async def fake_load(connection, conversation_id, owner):
        calls["loaded"].append(conversation_id)
        return ConversationSnapshot(
            conversation_id=conversation_id,
            owner_subject=owner,
            rolling_summary="",
            summary_through_turn=-1,
            turns=[],
        )

    async def fake_append(connection, **kwargs):
        calls["appended"].append(kwargs)

    monkeypatch.setattr(service_chat, "stream_graph", fake_graph)
    monkeypatch.setattr(service_chat, "prepare_memory", fake_prepare)
    monkeypatch.setattr(service_chat, "async_conversation_lock", _noop_lock)
    monkeypatch.setattr(service_chat, "async_load_snapshot", fake_load)
    monkeypatch.setattr(service_chat, "async_append_exchange", fake_append)
    monkeypatch.setattr(service_chat, "_access_filter", lambda claims: None)
    return calls


async def _collect_stream_chat(request, claims):
    return [event async for event in service_chat.stream_chat(_FakeChatPool(), request, claims)]


async def test_stream_chat_done_carries_answer_and_mints_conversation_id(monkeypatch):
    from types import SimpleNamespace

    claims = SimpleNamespace(subject="u-1", role="manager")
    calls = _patch_stream_chat(monkeypatch)
    events = await _collect_stream_chat(AskRequest(question="hi"), claims)

    assert [event["type"] for event in events] == ["step", "token", "token", "done"]
    assert [event["content"] for event in events if event["type"] == "token"] == ["hi ", "there"]
    done = events[-1]
    assert done["answer"] == "hi there"
    assert done["project_evidence"][0]["project_name"] == "Workalay"
    assert done["conversation_id"]
    assert calls["loaded"] == []
    assert len(calls["appended"]) == 1


async def test_stream_chat_yields_tokens_before_persistence(monkeypatch):
    claims = type("Claims", (), {"subject": "u-1", "role": "manager"})()
    calls = _patch_stream_chat(monkeypatch)
    stream = service_chat.stream_chat(_FakeChatPool(), AskRequest(question="hi"), claims)

    assert (await stream.__anext__())["type"] == "step"
    assert (await stream.__anext__()) == {"type": "token", "content": "hi "}
    assert calls["appended"] == []

    remaining = [event async for event in stream]
    assert remaining[-1]["type"] == "done"
    assert len(calls["appended"]) == 1


async def test_stream_chat_follow_up_reuses_conversation_id(monkeypatch):
    from types import SimpleNamespace

    claims = SimpleNamespace(subject="u-1", role="manager")
    calls = _patch_stream_chat(monkeypatch)
    first = await _collect_stream_chat(AskRequest(question="hi"), claims)
    conversation_id = first[-1]["conversation_id"]

    second = await _collect_stream_chat(
        AskRequest(question="again", conversation_id=conversation_id), claims
    )
    assert second[-1]["conversation_id"] == conversation_id
    assert second[-1]["answer"] == "hi there"
    assert calls["loaded"] == [conversation_id]
