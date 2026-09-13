"""Authenticated conversation orchestration for the WebSocket chat surface."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from auth.types import AssistantClaims
from psycopg_pool import AsyncConnectionPool

from agent.graph.workflow import stream_graph
from agent.types import AskRequest
from models.conversations import (
    ConversationSnapshot,
    async_append_exchange,
    async_conversation_lock,
    async_load_snapshot,
    async_update_summary,
    new_conversation_id,
)
from service.memory import PreparedMemory, prepare_memory

logger = logging.getLogger(__name__)


async def stream_chat(
    pool: AsyncConnectionPool,
    request: AskRequest,
    claims: AssistantClaims,
) -> AsyncIterator[dict]:
    conversation_id = request.conversation_id or new_conversation_id()
    logger.info(
        "service chat: start conversation_id=%s new=%s question_len=%d",
        conversation_id,
        not request.conversation_id,
        len(request.question),
    )
    async with pool.connection() as connection, async_conversation_lock(
        connection, conversation_id
    ):
            if request.conversation_id:
                snapshot = await async_load_snapshot(connection, conversation_id, claims.subject)
                await connection.commit()
            else:
                snapshot = ConversationSnapshot(
                    conversation_id=conversation_id,
                    owner_subject=claims.subject,
                    rolling_summary="",
                    summary_through_turn=-1,
                    turns=[],
                )

            logger.info("service chat: preparing memory turns=%d", len(snapshot.turns))
            prepared = await prepare_memory(snapshot)
            logger.info(
                "service chat: memory ready turns=%d summary_len=%d changed=%s",
                len(prepared.turns),
                len(prepared.summary),
                prepared.changed,
            )
            if prepared.changed:
                yield {"type": "step", "text": "compacted conversation memory"}
                async with connection.transaction():
                    await async_update_summary(
                        connection,
                        conversation_id=conversation_id,
                        summary=prepared.summary,
                        summary_through_turn=prepared.summary_through_turn,
                    )

            final_event = None
            async for event in stream_graph(
                request.question,
                top_k=request.top_k,
                search_mode=request.search_mode,
                access_filter=_access_filter(claims),
                conversation_history=prepared.turns,
                memory_summary=prepared.summary,
                claims=claims,
                pool=pool,
            ):
                if event["type"] == "done":
                    final_event = event
                    continue
                yield event

            if final_event is None:
                logger.warning("service chat: workflow ended without final event")
                raise RuntimeError("streaming workflow ended without a final event")
            logger.info(
                "service chat: workflow done answer_len=%d grounded=%s",
                len(final_event["answer"]),
                final_event["grounded"],
            )

            async with connection.transaction():
                await async_append_exchange(
                    connection,
                    conversation_id=conversation_id,
                    owner_subject=claims.subject,
                    question=request.question,
                    answer=final_event["answer"],
                )

            final_snapshot = _snapshot_after_exchange(prepared, request, final_event)
            compacted = await prepare_memory(final_snapshot)
            if compacted.changed:
                logger.info("service chat: persisting compacted summary")
                async with connection.transaction():
                    await async_update_summary(
                        connection,
                        conversation_id=conversation_id,
                        summary=compacted.summary,
                        summary_through_turn=compacted.summary_through_turn,
                    )

            logger.info("service chat: done conversation_id=%s", conversation_id)
            yield {
                "type": "done",
                "conversation_id": conversation_id,
                "answer": final_event["answer"],
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
