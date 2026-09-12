"""Store contract: SQL shape assertions on a fake connection (no live DB)."""

from auth.store import (
    ensure_assistant_tables,
    find_user_by_email,
    find_user_by_id,
    insert_user,
    list_users,
    record_audit_event,
    set_user_role,
)


class FakeConn:
    """Minimal psycopg-like connection: records execute calls, replays rows."""

    def __init__(self, fetchone_result=None, fetchall_result=None):
        self.statements = []
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result or []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return self

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return self._fetchall_result


def _user_row():
    from datetime import UTC, datetime

    now = datetime(2026, 9, 12, tzinfo=UTC)
    return ("u-1", "Ada@Example.com", "hashed", "manager", now, now)


def test_ensure_creates_both_tables():
    conn = FakeConn()
    ensure_assistant_tables(conn)
    joined = "\n".join(sql for sql, _ in conn.statements)
    assert "assistant_users" in joined
    assert "assistant_audit_events" in joined


def test_find_by_email_normalizes_case():
    conn = FakeConn(fetchone_result=_user_row())
    user = find_user_by_email(conn, "ADA@EXAMPLE.COM")
    assert user is not None
    assert user["email"] == "Ada@Example.com"
    _, params = conn.statements[0]
    assert params == ("ada@example.com",)


def test_find_by_email_missing_returns_none():
    assert find_user_by_email(FakeConn(), "nobody@example.com") is None


def test_find_by_id():
    conn = FakeConn(fetchone_result=_user_row())
    user = find_user_by_id(conn, "u-1")
    assert user is not None
    assert user["id"] == "u-1"
    assert user["role"] == "manager"


def test_insert_user_returns_public_shape():
    conn = FakeConn(fetchone_result=_user_row())
    user = insert_user(conn, email="Ada@Example.com", password_hash="h", role="lead")
    assert user["email"] == "Ada@Example.com"
    assert "password_hash" not in user
    _, params = conn.statements[0]
    assert params[1] == "ada@example.com"
    assert params[2] == "h"
    assert params[3] == "lead"


def test_set_role_returns_updated_or_none():
    conn = FakeConn(fetchone_result=_user_row())
    assert set_user_role(conn, user_id="u-1", role="admin") is not None
    assert set_user_role(FakeConn(), user_id="nope", role="admin") is None


def test_list_users_returns_public_shapes():
    conn = FakeConn(fetchall_result=[_user_row(), _user_row()])
    users = list_users(conn)
    assert len(users) == 2
    assert all("password_hash" not in u for u in users)


def test_audit_event_records_action():
    conn = FakeConn()
    record_audit_event(
        conn,
        actor_id="a-1",
        actor_email="root@example.com",
        action="create_user",
        resource="assistant_user",
        target_id="u-1",
        detail={"role": "manager"},
    )
    sql, params = conn.statements[0]
    assert "assistant_audit_events" in sql
    assert params[2] == "create_user"
    assert params[5] == {"role": "manager"}
