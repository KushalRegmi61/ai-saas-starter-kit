"""Service-owned identity orchestration over the shared auth store."""

import pytest

import models.users as users


def test_seed_inserts_admin_when_email_is_absent(monkeypatch):
    inserted = {}
    audit = []
    monkeypatch.setattr(users, "ensure_assistant_tables", lambda connection: None)
    monkeypatch.setattr(users, "find_user_by_email", lambda connection, email: None)
    monkeypatch.setattr(users, "hash_password", lambda password: "hashed")

    def insert(connection, **kwargs):
        inserted.update(kwargs)
        return {"id": "admin-1", "email": kwargs["email"], "role": kwargs["role"]}

    monkeypatch.setattr(users, "insert_user", insert)
    monkeypatch.setattr(
        users, "record_audit_event", lambda connection, **kwargs: audit.append(kwargs)
    )

    result = users.ensure_and_seed(object(), "Root@Example.com", "correct horse")

    assert result == {"id": "admin-1", "email": "root@example.com", "role": "admin"}
    assert inserted == {"email": "root@example.com", "password_hash": "hashed", "role": "admin"}
    assert audit[0]["action"] == "admin.seeded"


def test_seed_never_overwrites_existing_user(monkeypatch):
    existing = {
        "id": "existing",
        "email": "root@example.com",
        "password_hash": "old-hash",
        "role": "employee",
    }
    monkeypatch.setattr(users, "ensure_assistant_tables", lambda connection: None)
    monkeypatch.setattr(users, "find_user_by_email", lambda connection, email: existing)
    monkeypatch.setattr(
        users,
        "insert_user",
        lambda *args, **kwargs: pytest.fail("existing seed user must not be overwritten"),
    )

    result = users.ensure_and_seed(object(), "ROOT@example.com", "new-password")

    assert result == {"id": "existing", "email": "root@example.com", "role": "employee"}


def test_partial_seed_credentials_fail_closed(monkeypatch):
    monkeypatch.setattr(users, "ensure_assistant_tables", lambda connection: None)

    with pytest.raises(ValueError, match="must be set together"):
        users.ensure_and_seed(object(), "root@example.com", "")


def test_authenticate_records_success_and_hides_hash(monkeypatch):
    events = []
    monkeypatch.setattr(
        users,
        "find_user_by_email",
        lambda connection, email: {
            "id": "u-1",
            "email": email,
            "password_hash": "hash",
            "role": "admin",
        },
    )
    monkeypatch.setattr(users, "verify_password", lambda password, password_hash: True)
    monkeypatch.setattr(
        users, "record_audit_event", lambda connection, **kwargs: events.append(kwargs)
    )

    result = users.authenticate(object(), "Root@Example.com", "password")

    assert result == {"id": "u-1", "email": "root@example.com", "role": "admin"}
    assert "password_hash" not in result
    assert events[0]["action"] == "login.success"


@pytest.mark.asyncio
async def test_async_pool_recycles_stale_connections(monkeypatch):
    import models.users as users_module

    seen = {}

    class FakePool:
        check_connection = staticmethod(lambda conn: None)

        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def open(self, wait=True):
            seen["opened"] = wait

    monkeypatch.setattr("psycopg_pool.AsyncConnectionPool", FakePool)
    await users_module.get_async_pool("postgresql://db")

    assert seen["max_lifetime"] <= 300
    assert seen["max_idle"] <= 60
    assert seen["check"] is not None
    assert seen["kwargs"]["keepalives"] == 1
