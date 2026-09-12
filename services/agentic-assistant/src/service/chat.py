"""Authenticated conversation orchestration for the WebSocket chat surface."""

from __future__ import annotations

from collections.abc import AsyncIterator

from auth.types import AssistantClaims
from psycopg_pool import ConnectionPool

from agent.graph.streaming import stream_answer
from agent.types import AskRequest
from models.conversations import (
    ConversationSnapshot,
    append_exchange,
    conversation_lock,
    load_snapshot,
    new_conversation_id,
    update_summary,
)
from service.memory import PreparedMemory, prepare_memory


async def stream_chat(
    pool: ConnectionPool,
    request: AskRequest,
    claims: AssistantClaims,
) -> AsyncIterator[dict]:
    conversation_id = request.conversation_id or new_conversation_id()
    with pool.connection() as connection, conversation_lock(connection, conversation_id):
        if request.conversation_id:
            snapshot = load_snapshot(connection, conversation_id, claims.subject)
            connection.commit()
        else:
            snapshot = ConversationSnapshot(
                conversation_id=conversation_id,
                owner_subject=claims.subject,
                rolling_summary="",
                summary_through_turn=-1,
                turns=[],
            )

        prepared = await prepare_memory(snapshot)
        if prepared.changed:
            yield {"type": "step", "text": "compacted conversation memory"}
            with connection.transaction():
                update_summary(
                    connection,
                    conversation_id=conversation_id,
                    summary=prepared.summary,
                    summary_through_turn=prepared.summary_through_turn,
                )

        final_event = None
        async for event in stream_answer(
            request.question,
            top_k=request.top_k,
            search_mode=request.search_mode,
            access_filter=_access_filter(claims),
            conversation_history=prepared.turns,
            memory_summary=prepared.summary,
        ):
            if event["type"] == "done":
                final_event = event
                continue
            yield event

        if final_event is None:
            raise RuntimeError("streaming workflow ended without a final event")

        with connection.transaction():
            append_exchange(
                connection,
                conversation_id=conversation_id,
                owner_subject=claims.subject,
                question=request.question,
                answer=final_event["answer"],
            )

        final_snapshot = _snapshot_after_exchange(prepared, request, final_event)
        compacted = await prepare_memory(final_snapshot)
        if compacted.changed:
            with connection.transaction():
                update_summary(
                    connection,
                    conversation_id=conversation_id,
                    summary=compacted.summary,
                    summary_through_turn=compacted.summary_through_turn,
                )

        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "sources": final_event["sources"],
            "grounded": final_event["grounded"],
            "rewritten_question": final_event["rewritten_question"],
            "workflow_steps": final_event["workflow_steps"],
        }


def _snapshot_after_exchange(
    prepared: PreparedMemory,
    request: AskRequest,
    final_event: dict,
) -> ConversationSnapshot:
    last_index = prepared.last_turn_index
    return ConversationSnapshot(
        conversation_id=request.conversation_id or "new",
        owner_subject="",
        rolling_summary=prepared.summary,
        summary_through_turn=prepared.summary_through_turn,
        turns=[
            *prepared.turns,
            {"index": last_index + 1, "role": "user", "content": request.question},
            {
                "index": last_index + 2,
                "role": "assistant",
                "content": final_event["answer"],
            },
        ],
    )


def _access_filter(claims: AssistantClaims):
    from agent.authz import claims_to_access_filter
    from agent.config import get_agent_settings

    return claims_to_access_filter(claims, tenant=get_agent_settings().default_tenant)
