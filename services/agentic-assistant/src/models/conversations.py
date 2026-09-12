"""Neon-backed conversation turns and rolling-summary state."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


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
            turn_index INTEGER NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
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

    turns = connection.execute(
        """
        SELECT turn_index, role, content
        FROM assistant_conversation_turns
        WHERE conversation_id = %s AND turn_index > %s
        ORDER BY turn_index ASC
        """,
        (conversation_id, row[2]),
    ).fetchall()
    return ConversationSnapshot(
        conversation_id=conversation_id,
        owner_subject=row[0],
        rolling_summary=row[1],
        summary_through_turn=row[2],
        turns=[{"index": item[0], "role": item[1], "content": item[2]} for item in turns],
    )


def get_full_history(connection: Any, conversation_id: str, owner_subject: str) -> list[dict]:
    snapshot = load_snapshot(connection, conversation_id, owner_subject)
    rows = connection.execute(
        """
        SELECT role, content
        FROM assistant_conversation_turns
        WHERE conversation_id = %s
        ORDER BY turn_index ASC
        """,
        (conversation_id,),
    ).fetchall()
    # Loading the snapshot first performs the ownership check before any history leaves storage.
    del snapshot
    return [{"role": row[0], "content": row[1]} for row in rows]


def append_exchange(
    connection: Any,
    *,
    conversation_id: str,
    owner_subject: str,
    question: str,
    answer: str,
) -> int:
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
