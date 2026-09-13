"""Conversation storage primitives and ownership/serialization tests."""

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from models.conversations import (
    ConversationForbidden,
    ConversationNotFound,
    append_exchange,
    conversation_lock,
    ensure_conversation_tables,
    get_full_history,
    load_snapshot,
)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, owner="u-1", turns=None):
        self.owner = owner
        self.turns = turns or []
        self.calls = []
        self.commits = 0

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        lowered = sql.lower()
        if "select owner_subject, rolling_summary" in lowered:
            return Result([(self.owner, "summary", -1)])
        if "select turn_index, role, content" in lowered:
            return Result(self.turns)
        if "select owner_subject, coalesce(max(turn_index)" in lowered:
            return Result([(self.owner, -1)])
        return Result([])

    def commit(self):
        self.commits += 1

    @contextmanager
    def transaction(self):
        yield


def test_schema_initialization_is_idempotent_shape():
    connection = FakeConnection()
    ensure_conversation_tables(connection)
    ensure_conversation_tables(connection)
    assert len(connection.calls) == 6
    assert "assistant_conversations" in connection.calls[0][0]
    assert "assistant_conversation_turns" in connection.calls[1][0]


def test_snapshot_checks_owner_before_returning_turns():
    connection = FakeConnection(turns=[(0, "user", "hello")])
    snapshot = load_snapshot(connection, "c-1", "u-1")
    assert snapshot.rolling_summary == "summary"
    assert snapshot.turns == [{"index": 0, "role": "user", "content": "hello"}]

    with pytest.raises(ConversationForbidden):
        load_snapshot(connection, "c-1", "other-user")


def test_append_exchange_writes_ordered_user_and_assistant_turns():
    connection = FakeConnection()
    last_index = append_exchange(
        connection,
        conversation_id="c-1",
        owner_subject="u-1",
        question="hello",
        answer="hi",
    )
    assert last_index == 1
    insert = next(
        sql for sql, _ in connection.calls if "INSERT INTO assistant_conversation_turns" in sql
    )
    params = next(params for sql, params in connection.calls if sql == insert)
    assert params == ("c-1", 0, "hello", "c-1", 1, "hi")


def test_conversation_lock_commits_acquire_and_release():
    connection = FakeConnection()
    with conversation_lock(connection, "c-1"):
        assert connection.commits == 1
    assert connection.commits == 2
    assert sum("pg_advisory" in sql for sql, _ in connection.calls) == 2


def test_missing_snapshot_is_distinguished_from_owner_mismatch(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(connection, "execute", lambda sql, params=(): Result([]))
    with pytest.raises(ConversationNotFound):
        load_snapshot(connection, "missing", "u-1")


def test_full_history_pairs_turns_and_skips_orphans():
    stamped = datetime(2026, 9, 13, 2, 0, tzinfo=UTC)
    connection = FakeConnection(
        turns=[
            (0, "user", "q1", stamped),
            (1, "assistant", "a1", stamped),
            (2, "user", "q2", stamped),
            (3, "assistant", "a2", stamped),
            (4, "user", "unanswered", stamped),
        ]
    )
    history = get_full_history(connection, "c-1", "u-1")
    assert history == [
        {
            "turn_index": 0,
            "question": "q1",
            "answer": "a1",
            "sources": [],
            "created_at": stamped.isoformat(),
        },
        {
            "turn_index": 2,
            "question": "q2",
            "answer": "a2",
            "sources": [],
            "created_at": stamped.isoformat(),
        },
    ]
