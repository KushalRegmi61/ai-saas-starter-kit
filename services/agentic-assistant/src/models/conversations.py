"""Neon-backed conversation turns and rolling-summary state."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class ConversationNotFound(LookupError):
    """Raised when a requested conversation does not exist."""


class ConversationForbidden(PermissionError):
    """Raised when a conversation belongs to another assistant user."""


@dataclass(frozen=True)
class ConversationSnapshot:
    conversation_id: str
    owner_subject: str
    rolling_summary: str
    summary_through_turn: int
    turns: list[dict[str, Any]]


def ensure_conversation_tables(connection: Any) -> None:
    logger.info("models: ensuring conversation tables")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_conversations (
            conversation_id TEXT PRIMARY KEY,
            owner_subject TEXT NOT NULL,
            rolling_summary TEXT NOT NULL DEFAULT '',
            summary_through_turn INTEGER NOT NULL DEFAULT -1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_conversation_turns (
            conversation_id TEXT NOT NULL REFERENCES assistant_conversations(conversation_id)
                ON DELETE CASCADE,
            turn_index INTEGER NOT NULL, role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (conversation_id, turn_index)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS assistant_conversation_turns_recent_idx
        ON assistant_conversation_turns (conversation_id, turn_index DESC)
        """
    )


async def ensure_conversation_tables_async(connection: Any) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_conversations (
            conversation_id TEXT PRIMARY KEY, owner_subject TEXT NOT NULL,
            rolling_summary TEXT NOT NULL DEFAULT '', summary_through_turn INTEGER NOT NULL DEFAULT -1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_conversation_turns (
            conversation_id TEXT NOT NULL REFERENCES assistant_conversations(conversation_id)
                ON DELETE CASCADE,
            turn_index INTEGER NOT NULL, role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (conversation_id, turn_index)
        )
        """
    )
    await connection.execute(
        """
        CREATE INDEX IF NOT EXISTS assistant_conversation_turns_recent_idx
        ON assistant_conversation_turns (conversation_id, turn_index DESC)
        """
    )
def new_conversation_id() -> str:
    return str(uuid.uuid4())


def load_snapshot(
    connection: Any,
    conversation_id: str,
    owner_subject: str,
) -> ConversationSnapshot:
    row = connection.execute(
        """
        SELECT owner_subject, rolling_summary, summary_through_turn
        FROM assistant_conversations
        WHERE conversation_id = %s
        """,
        (conversation_id,),
    ).fetchone()
    if row is None:
        raise ConversationNotFound(conversation_id)
    if row[0] != owner_subject:
        raise ConversationForbidden(conversation_id)

    logger.info("models: load snapshot conversation_id=%s", conversation_id)
    turns = connection.execute(
        """
        SELECT turn_index, role, content
        FROM assistant_conversation_turns
        WHERE conversation_id = %s AND turn_index > %s
        ORDER BY turn_index ASC
        """,
        (conversation_id, row[2]),
    ).fetchall()
    logger.info("models: snapshot loaded turns=%d", len(turns))
    return ConversationSnapshot(
        conversation_id=conversation_id,
        owner_subject=row[0],
        rolling_summary=row[1],
        summary_through_turn=row[2],
        turns=[{"index": item[0], "role": item[1], "content": item[2]} for item in turns],
    )


def get_full_history(connection: Any, conversation_id: str, owner_subject: str) -> list[dict]:
    logger.info("models: history fetch conversation_id=%s", conversation_id)
    snapshot = load_snapshot(connection, conversation_id, owner_subject)
    rows = connection.execute(
        """
        SELECT turn_index, role, content, created_at
        FROM assistant_conversation_turns
        WHERE conversation_id = %s
        ORDER BY turn_index ASC
        """,
        (conversation_id,),
    ).fetchall()
    # Loading the snapshot first performs the ownership check before any history leaves storage.
    del snapshot
    logger.info("models: history rows=%d conversation_id=%s", len(rows), conversation_id)
    return _pair_turns(rows)


def _pair_turns(rows: list) -> list[dict]:
    """Fold ordered (turn_index, role, content, created_at) rows into Q/A turns.

    Exchanges are appended atomically as user+assistant pairs, so a trailing
    lone user turn (or any orphan) is skipped rather than rendered half-empty.
    Per-turn sources are not persisted; pairs carry sources=[].
    """
    turns: list[dict] = []
    pending: tuple | None = None
    for index, role, content, created_at in rows:
        if role == "user":
            pending = (index, content)
        elif role == "assistant" and pending is not None:
            user_index, question = pending
            pending = None
            timestamp = (
                created_at.isoformat()
                if hasattr(created_at, "isoformat")
                else created_at
            )
            turns.append(
                {
                    "turn_index": user_index,
                    "question": question,
                    "answer": content,
                    "sources": [],
                    "created_at": timestamp,
                }
            )
    return turns


def append_exchange(
    connection: Any,
    *,
    conversation_id: str,
    owner_subject: str,
    question: str,
    answer: str,
) -> int:
    logger.info(
        "models: append exchange conversation_id=%s q_len=%d a_len=%d",
        conversation_id,
        len(question),
        len(answer),
    )
    connection.execute(
        """
        INSERT INTO assistant_conversations (conversation_id, owner_subject)
        VALUES (%s, %s)
        ON CONFLICT (conversation_id) DO NOTHING
        """,
        (conversation_id, owner_subject),
    )
    row = connection.execute(
        """
        SELECT owner_subject, COALESCE(MAX(turn_index), -1)
        FROM assistant_conversation_turns
        RIGHT JOIN assistant_conversations USING (conversation_id)
        WHERE assistant_conversations.conversation_id = %s
        GROUP BY assistant_conversations.owner_subject
        """,
        (conversation_id,),
    ).fetchone()
    if row is None or row[0] != owner_subject:
        raise ConversationForbidden(conversation_id)
    next_index = int(row[1]) + 1
    connection.execute(
        """
        INSERT INTO assistant_conversation_turns
            (conversation_id, turn_index, role, content)
        VALUES (%s, %s, 'user', %s), (%s, %s, 'assistant', %s)
        """,
        (conversation_id, next_index, question, conversation_id, next_index + 1, answer),
    )
    connection.execute(
        """
        UPDATE assistant_conversations
        SET updated_at = NOW()
        WHERE conversation_id = %s
        """,
        (conversation_id,),
    )
    return next_index + 1


def update_summary(
    connection: Any,
    *,
    conversation_id: str,
    summary: str,
    summary_through_turn: int,
) -> None:
    logger.info(
        "models: update summary conversation_id=%s through=%d len=%d",
        conversation_id,
        summary_through_turn,
        len(summary),
    )
    connection.execute(
        """
        UPDATE assistant_conversations
        SET rolling_summary = %s, summary_through_turn = %s, updated_at = NOW()
        WHERE conversation_id = %s
        """,
        (summary, summary_through_turn, conversation_id),
    )


@contextmanager
def conversation_lock(connection: Any, conversation_id: str) -> Iterator[None]:
    """Serialize one conversation across worker processes using a DB lock."""
    connection.execute(
        "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
        (conversation_id,),
    )
    connection.commit()
    try:
        yield
    finally:
        connection.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            (conversation_id,),
        )
        connection.commit()


async def async_load_snapshot(
    connection: Any,
    conversation_id: str,
    owner_subject: str,
) -> ConversationSnapshot:
    cursor = await connection.execute(
        """
        SELECT owner_subject, rolling_summary, summary_through_turn
        FROM assistant_conversations WHERE conversation_id = %s
        """,
        (conversation_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise ConversationNotFound(conversation_id)
    if row[0] != owner_subject:
        raise ConversationForbidden(conversation_id)
    cursor = await connection.execute(
        """
        SELECT turn_index, role, content
        FROM assistant_conversation_turns
        WHERE conversation_id = %s AND turn_index > %s
        ORDER BY turn_index ASC
        """,
        (conversation_id, row[2]),
    )
    turns = await cursor.fetchall()
    return ConversationSnapshot(
        conversation_id=conversation_id,
        owner_subject=row[0],
        rolling_summary=row[1],
        summary_through_turn=row[2],
        turns=[{"index": item[0], "role": item[1], "content": item[2]} for item in turns],
    )


async def async_get_full_history(
    connection: Any, conversation_id: str, owner_subject: str
) -> list[dict]:
    await async_load_snapshot(connection, conversation_id, owner_subject)
    cursor = await connection.execute(
        """
        SELECT turn_index, role, content, created_at
        FROM assistant_conversation_turns
        WHERE conversation_id = %s ORDER BY turn_index ASC
        """,
        (conversation_id,),
    )
    return _pair_turns(await cursor.fetchall())


async def async_append_exchange(
    connection: Any,
    *,
    conversation_id: str,
    owner_subject: str,
    question: str,
    answer: str,
) -> int:
    await connection.execute(
        """
        INSERT INTO assistant_conversations (conversation_id, owner_subject)
        VALUES (%s, %s) ON CONFLICT (conversation_id) DO NOTHING
        """,
        (conversation_id, owner_subject),
    )
    cursor = await connection.execute(
        """
        SELECT owner_subject, COALESCE(MAX(turn_index), -1)
        FROM assistant_conversation_turns
        RIGHT JOIN assistant_conversations USING (conversation_id)
        WHERE assistant_conversations.conversation_id = %s
        GROUP BY assistant_conversations.owner_subject
        """,
        (conversation_id,),
    )
    row = await cursor.fetchone()
    if row is None or row[0] != owner_subject:
        raise ConversationForbidden(conversation_id)
    next_index = int(row[1]) + 1
    await connection.execute(
        """
        INSERT INTO assistant_conversation_turns
            (conversation_id, turn_index, role, content)
        VALUES (%s, %s, 'user', %s), (%s, %s, 'assistant', %s)
        """,
        (conversation_id, next_index, question, conversation_id, next_index + 1, answer),
    )
    await connection.execute(
        "UPDATE assistant_conversations SET updated_at = NOW() WHERE conversation_id = %s",
        (conversation_id,),
    )
    return next_index + 1


async def async_update_summary(
    connection: Any, *, conversation_id: str, summary: str, summary_through_turn: int
) -> None:
    await connection.execute(
        """
        UPDATE assistant_conversations
        SET rolling_summary = %s, summary_through_turn = %s, updated_at = NOW()
        WHERE conversation_id = %s
        """,
        (summary, summary_through_turn, conversation_id),
    )


PREVIEW_MAX_LEN = 120


def _preview_of(content: str | None) -> str:
    if not content:
        return ""
    return " ".join(str(content).split())[:PREVIEW_MAX_LEN]


def _isoformat_ts(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def list_conversations(
    connection: Any, owner_subject: str, *, limit: int = 50, offset: int = 0
) -> list[dict]:
    """Owner-scoped chat summaries, newest first (Option A: derived preview)."""
    logger.info("models: list conversations owner=%s limit=%d", owner_subject, limit)
    rows = connection.execute(
        """
        SELECT conversation_id, updated_at
        FROM assistant_conversations
        WHERE owner_subject = %s
        ORDER BY updated_at DESC
        LIMIT %s OFFSET %s
        """,
        (owner_subject, limit, offset),
    ).fetchall()
    summaries: list[dict] = []
    for conversation_id, updated_at in rows:
        count = connection.execute(
            """
            SELECT COUNT(*)
            FROM assistant_conversation_turns
            WHERE conversation_id = %s AND role = 'assistant'
            """,
            (conversation_id,),
        ).fetchone()
        first = connection.execute(
            """
            SELECT content
            FROM assistant_conversation_turns
            WHERE conversation_id = %s AND role = 'user'
            ORDER BY turn_index ASC
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
        summaries.append(
            {
                "conversation_id": conversation_id,
                "updated_at": _isoformat_ts(updated_at),
                "turn_count": int(count[0]) if count else 0,
                "preview": _preview_of(first[0] if first else None),
            }
        )
    return summaries


async def async_list_conversations(
    connection: Any, owner_subject: str, *, limit: int = 50, offset: int = 0
) -> list[dict]:
    """Async owner-scoped chat summaries, newest first (Option A)."""
    logger.info("models: list conversations owner=%s limit=%d", owner_subject, limit)
    cursor = await connection.execute(
        """
        SELECT conversation_id, updated_at
        FROM assistant_conversations
        WHERE owner_subject = %s
        ORDER BY updated_at DESC
        LIMIT %s OFFSET %s
        """,
        (owner_subject, limit, offset),
    )
    rows = await cursor.fetchall()
    summaries: list[dict] = []
    for conversation_id, updated_at in rows:
        cursor = await connection.execute(
            """
            SELECT COUNT(*)
            FROM assistant_conversation_turns
            WHERE conversation_id = %s AND role = 'assistant'
            """,
            (conversation_id,),
        )
        count = await cursor.fetchone()
        cursor = await connection.execute(
            """
            SELECT content
            FROM assistant_conversation_turns
            WHERE conversation_id = %s AND role = 'user'
            ORDER BY turn_index ASC
            LIMIT 1
            """,
            (conversation_id,),
        )
        first = await cursor.fetchone()
        summaries.append(
            {
                "conversation_id": conversation_id,
                "updated_at": _isoformat_ts(updated_at),
                "turn_count": int(count[0]) if count else 0,
                "preview": _preview_of(first[0] if first else None),
            }
        )
    return summaries


@asynccontextmanager
async def async_conversation_lock(connection: Any, conversation_id: str):
    """Serialize a conversation without blocking the event loop."""
    await connection.execute(
        "SELECT pg_advisory_lock(hashtextextended(%s, 0))", (conversation_id,)
    )
    await connection.commit()
    try:
        yield
    finally:
        await connection.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (conversation_id,)
        )
        await connection.commit()
