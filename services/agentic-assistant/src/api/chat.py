"""Persistent JWT-ticket authenticated WebSocket chat and history routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from auth.tokens import InvalidToken, decode_assistant_ws_ticket
from auth.types import AssistantClaims
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from rag.types import SearchMode

from agent.authz import require_jwt_user
from agent.config import get_agent_settings
from agent.types import AskRequest, ConversationTurn
from api.auth import get_user_pool
from models.conversations import ConversationForbidden, ConversationNotFound, get_full_history
from service.chat import stream_chat

logger = logging.getLogger(__name__)
router = APIRouter()


class SocketAskRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=10)
    search_mode: SearchMode = "auto"
    conversation_id: str | None = None


@router.websocket("/ask")
async def ask_socket(websocket: WebSocket) -> None:
    pool = getattr(websocket.app.state, "assistant_user_pool", None)
    secret = get_agent_settings().assistant_jwt_secret
    if pool is None or not secret:
        await websocket.close(code=1013, reason="Assistant chat is not configured")
        return

    await websocket.accept()
    claims = await _authenticate_socket(websocket, secret)
    if claims is None:
        return

    await websocket.send_json(
        {
            "type": "ready",
            "expires_at": datetime.fromtimestamp(claims.expires_at, tz=UTC).isoformat(),
        }
    )

    send_lock = asyncio.Lock()
    receive_task = asyncio.create_task(websocket.receive_json())
    active_task: asyncio.Task | None = None
    try:
        while True:
            wait_for = {receive_task}
            if active_task is not None:
                wait_for.add(active_task)
            done, _ = await asyncio.wait(wait_for, return_when=asyncio.FIRST_COMPLETED)

            if active_task is not None and active_task in done:
                active_task.result()
                active_task = None

            if receive_task not in done:
                continue

            payload = receive_task.result()
            receive_task = asyncio.create_task(websocket.receive_json())
            if not isinstance(payload, dict) or payload.get("type") != "ask":
                await _send_json(
                    websocket,
                    send_lock,
                    {"type": "error", "code": "invalid_message", "text": "Expected an ask message"},
                )
                continue
            if active_task is not None:
                await _send_json(
                    websocket,
                    send_lock,
                    {
                        "type": "error",
                        "request_id": payload.get("request_id"),
                        "code": "request_in_progress",
                        "text": "Only one ask may be active per WebSocket",
                    },
                )
                continue

            try:
                socket_request = SocketAskRequest.model_validate(payload)
            except ValidationError as exc:
                await _send_json(
                    websocket,
                    send_lock,
                    {
                        "type": "error",
                        "request_id": payload.get("request_id"),
                        "code": "invalid_request",
                        "text": str(exc),
                    },
                )
                continue
            active_task = asyncio.create_task(
                _run_request(
                    websocket,
                    send_lock,
                    pool,
                    claims,
                    socket_request,
                )
            )
    except WebSocketDisconnect:
        pass
    finally:
        receive_task.cancel()
        if active_task is not None:
            active_task.cancel()
        await asyncio.gather(receive_task, return_exceptions=True)
        if active_task is not None:
            await asyncio.gather(active_task, return_exceptions=True)


async def _authenticate_socket(websocket: WebSocket, secret: str) -> AssistantClaims | None:
    try:
        payload = await asyncio.wait_for(websocket.receive_json(), timeout=10)
    except (TimeoutError, WebSocketDisconnect):
        await websocket.close(code=4401, reason="WebSocket authentication required")
        return None
    if not isinstance(payload, dict) or payload.get("type") != "auth":
        await websocket.close(code=4401, reason="WebSocket authentication required")
        return None
    try:
        return decode_assistant_ws_ticket(payload.get("access_token", ""), secret=secret)
    except InvalidToken:
        await websocket.close(code=4401, reason="Invalid WebSocket ticket")
        return None


async def _run_request(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    pool,
    claims: AssistantClaims,
    socket_request: SocketAskRequest,
) -> None:
    request = AskRequest(
        question=socket_request.question,
        top_k=socket_request.top_k,
        search_mode=socket_request.search_mode,
        conversation_id=socket_request.conversation_id,
    )
    try:
        async for event in stream_chat(pool, request, claims):
            await _send_json(
                websocket,
                send_lock,
                {**event, "request_id": socket_request.request_id},
            )
    except ConversationNotFound:
        await _send_error(
            websocket, send_lock, socket_request.request_id, "not_found", "Conversation not found"
        )
    except ConversationForbidden:
        await _send_error(
            websocket,
            send_lock,
            socket_request.request_id,
            "forbidden",
            "Conversation access denied",
        )
    except WebSocketDisconnect:
        raise
    except Exception:
        logger.exception("WebSocket assistant request failed")
        await _send_error(
            websocket,
            send_lock,
            socket_request.request_id,
            "server_error",
            "Unable to complete the assistant request",
        )


async def _send_error(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    request_id: str,
    code: str,
    text: str,
) -> None:
    await _send_json(
        websocket,
        send_lock,
        {"type": "error", "request_id": request_id, "code": code, "text": text},
    )


async def _send_json(
    websocket: WebSocket, send_lock: asyncio.Lock, payload: dict[str, Any]
) -> None:
    async with send_lock:
        await websocket.send_json(payload)


@router.get("/conversations/{conversation_id}", response_model=list[ConversationTurn])
def conversation_history(
    conversation_id: str,
    pool=Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> list[ConversationTurn]:
    try:
        with pool.connection() as connection:
            history = get_full_history(connection, conversation_id, claims.subject)
        return [ConversationTurn(**turn) for turn in history]
    except ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found") from None
    except ConversationForbidden:
        raise HTTPException(status_code=403, detail="Conversation access denied") from None
