"""HTTP contract tests for assistant login and user administration."""

from contextlib import asynccontextmanager

import pytest
from auth.tokens import decode_assistant_token, decode_assistant_ws_ticket, mint_assistant_token
from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation

import api.auth as auth_api
from agent.config import get_agent_settings
from main import app

SECRET = "test-assistant-secret"


class FakePool:
    class Connection:
        async def commit(self):
            return None

    @asynccontextmanager
    async def connection(self):
        yield self.Connection()


def _user(user_id="u-1", role="admin"):
    return {
        "id": user_id,
        "email": f"{user_id}@example.com",
        "role": role,
        "created_at": None,
    }


@pytest.fixture
def client(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "assistant_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "agentic_assistant_jwt_ttl_seconds", 600)
    app.state.assistant_user_pool = FakePool()
    yield TestClient(app, raise_server_exceptions=False)
    app.state.assistant_user_pool = None


def _headers(role="admin", user_id="admin-1"):
    return {
        "Authorization": "Bearer "
        + mint_assistant_token(user_id=user_id, role=role, secret=SECRET, ttl_seconds=600)
    }


def test_login_success_returns_bearer_token_without_password_hash(client, monkeypatch):
    async def fake_authenticate(connection, email, password):
        return _user("admin-1", "admin")

    monkeypatch.setattr(
        auth_api.users,
        "authenticate_async",
        fake_authenticate,
    )

    response = client.post(
        "/auth/login", json={"email": "root@example.com", "password": "password"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 600
    assert "password_hash" not in body["user"]
    claims = decode_assistant_token(body["access_token"], secret=SECRET)
    assert (claims.subject, claims.role) == ("admin-1", "admin")


@pytest.mark.parametrize(
    "email,password", [("unknown@example.com", "password"), ("root@example.com", "wrong")]
)
def test_login_failures_are_generic(client, monkeypatch, email, password):
    async def fake_authenticate(*args):
        return None

    monkeypatch.setattr(auth_api.users, "authenticate_async", fake_authenticate)

    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_requires_jwt_secret(client, monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "assistant_jwt_secret", "")
    monkeypatch.setattr(
        auth_api.users,
        "authenticate_async",
        lambda *args: pytest.fail("database authentication must not run without JWT config"),
    )

    response = client.post(
        "/auth/login", json={"email": "root@example.com", "password": "password"}
    )

    assert response.status_code == 503


def test_websocket_ticket_requires_user_jwt_and_is_short_lived(client):
    response = client.post("/auth/ws-ticket", headers=_headers(role="manager"))

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "ws-ticket"
    assert body["expires_in"] == 60
    claims = decode_assistant_ws_ticket(body["access_token"], secret=SECRET)
    assert (claims.subject, claims.role) == ("admin-1", "manager")

    service_response = client.post(
        "/auth/ws-ticket", headers={"Authorization": "Bearer service-token"}
    )
    assert service_response.status_code == 401


def test_missing_database_returns_503(monkeypatch):
    app.state.assistant_user_pool = None
    response = TestClient(app, raise_server_exceptions=False).post(
        "/auth/login", json={"email": "root@example.com", "password": "password"}
    )
    assert response.status_code == 503


def test_admin_user_operations_success(client, monkeypatch):
    created = _user("u-2", "lead")
    updated = _user("u-2", "manager")
    async def fake_create(*args, **kwargs):
        return created

    async def fake_list(*args, **kwargs):
        return [_user(), created]

    async def fake_role(*args, **kwargs):
        return updated

    monkeypatch.setattr(auth_api.users, "create_user_async", fake_create)
    monkeypatch.setattr(auth_api.users, "list_users_async", fake_list)
    monkeypatch.setattr(auth_api.users, "set_role_async", fake_role)

    create_response = client.post(
        "/auth/users",
        json={"email": "new@example.com", "password": "password", "role": "lead"},
        headers=_headers(),
    )
    list_response = client.get("/auth/users", headers=_headers())
    update_response = client.patch(
        "/auth/users/u-2/role", json={"role": "manager"}, headers=_headers()
    )

    assert create_response.status_code == 201
    assert create_response.json()["role"] == "lead"
    assert list_response.status_code == 200
    assert len(list_response.json()) == 2
    assert update_response.status_code == 200
    assert update_response.json()["role"] == "manager"


def test_service_token_cannot_manage_users(client, monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "agent_service_token", "service-token")

    response = client.get("/auth/users", headers={"Authorization": "Bearer service-token"})

    assert response.status_code == 401


@pytest.mark.parametrize(
    "method,path,json_body",
    [
        (
            "post",
            "/auth/users",
            {"email": "new@example.com", "password": "password", "role": "lead"},
        ),
        ("get", "/auth/users", None),
        ("patch", "/auth/users/u-2/role", {"role": "lead"}),
    ],
)
def test_non_admin_cannot_manage_users(client, monkeypatch, method, path, json_body):
    request = getattr(client, method)
    if method == "get":
        response = request(path, headers=_headers(role="manager"))
    else:
        response = request(path, json=json_body, headers=_headers(role="manager"))

    assert response.status_code == 403


def test_create_user_duplicate_is_conflict(client, monkeypatch):
    def duplicate(*args, **kwargs):
        raise UniqueViolation("duplicate")

    async def duplicate_async(*args, **kwargs):
        raise UniqueViolation("duplicate")

    monkeypatch.setattr(auth_api.users, "create_user_async", duplicate_async)
    response = client.post(
        "/auth/users",
        json={"email": "new@example.com", "password": "password", "role": "lead"},
        headers=_headers(),
    )

    assert response.status_code == 409


def test_role_change_rejects_self_and_unknown_user(client, monkeypatch):
    self_response = client.patch(
        "/auth/users/admin-1/role", json={"role": "manager"}, headers=_headers()
    )
    assert self_response.status_code == 422

    async def missing_role(*args, **kwargs):
        return None

    monkeypatch.setattr(auth_api.users, "set_role_async", missing_role)
    missing_response = client.patch(
        "/auth/users/missing/role", json={"role": "manager"}, headers=_headers()
    )
    assert missing_response.status_code == 404
