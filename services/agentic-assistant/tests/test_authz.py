"""Mutation authz: service token OR admin JWT; per-role retrieval filters."""

from auth.tokens import mint_assistant_token
from auth.types import AssistantClaims
from fastapi import HTTPException
from rag.types import IngestionResult

import agent.runtime.ingest as ingest_mod
from agent.authz import claims_to_access_filter, get_claims, require_admin
from agent.config import get_agent_settings
from main import app

_SVC = "svc-test-token"
_JWT = "jwt-test-secret"


def _client():
    from fastapi.testclient import TestClient

    return TestClient(app, raise_server_exceptions=False)


def _configure(monkeypatch, *, service=_SVC, secret=_JWT):
    monkeypatch.setattr(get_agent_settings(), "agent_service_token", service)
    monkeypatch.setattr(get_agent_settings(), "assistant_jwt_secret", secret)


def _jwt(role, **kw):
    args = {"user_id": "u-1", "role": role, "secret": _JWT}
    args.update(kw)
    return {"Authorization": f"Bearer {mint_assistant_token(**args)}"}


def _stub_index(monkeypatch):
    def fake_index(content, filename, source, department=None, access_level=None, tenant=None):
        return IngestionResult(documents_loaded=1, chunks_created=1, sources=[source])

    monkeypatch.setattr(ingest_mod, "index_document", fake_index)


def _stub_delete(monkeypatch):
    monkeypatch.setattr(ingest_mod, "delete_indexed_source", lambda s, tenant=None: None)


def _status(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except HTTPException as exc:
        return exc.status_code
    return None


def _post_ingest(headers=None):
    return _client().post(
        "/ingest",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"source": "uploads/u-1/doc.pdf"},
        headers=headers,
    )


# --- dual-auth on the HTTP surface ---


def test_admin_jwt_allows_ingest_and_delete(monkeypatch):
    _configure(monkeypatch)
    _stub_index(monkeypatch)
    _stub_delete(monkeypatch)
    headers = _jwt("admin")
    assert _post_ingest(headers).status_code == 200
    resp = _client().delete("/sources", params={"source": "s"}, headers=headers)
    assert resp.json() == {"purged": True}


def test_non_admin_jwt_forbidden_on_mutations(monkeypatch):
    _configure(monkeypatch)
    _stub_index(monkeypatch)
    _stub_delete(monkeypatch)
    for role in ("employee", "lead", "manager"):
        headers = _jwt(role)
        assert _post_ingest(headers).status_code == 403
        resp = _client().delete("/sources", params={"source": "s"}, headers=headers)
        assert resp.status_code == 403


def test_bad_and_expired_jwt_rejected(monkeypatch):
    _configure(monkeypatch)
    assert _post_ingest({"Authorization": "Bearer not-a-token"}).status_code == 401
    assert _post_ingest(_jwt("admin", ttl_seconds=-1)).status_code == 401


def test_service_token_still_works_when_jwt_configured(monkeypatch):
    _configure(monkeypatch)
    _stub_index(monkeypatch)
    resp = _post_ingest({"Authorization": f"Bearer {_SVC}"})
    assert resp.status_code == 200


def test_503_when_neither_credential_configured(monkeypatch):
    _configure(monkeypatch, service="", secret="")
    assert _post_ingest().status_code == 503
    assert _client().delete("/sources", params={"source": "s"}).status_code == 503


# --- unit: claims, admin gate, filter mapping ---


def test_get_claims_roundtrip_and_absent(monkeypatch):
    _configure(monkeypatch)
    token = mint_assistant_token(user_id="u-9", role="lead", secret=_JWT)

    class Creds:
        credentials = token

    claims = get_claims(Creds())
    assert (claims.subject, claims.role) == ("u-9", "lead")
    assert _status(get_claims, None) == 401


def test_require_admin_gate():
    assert require_admin(AssistantClaims(subject="u", role="admin", issued_at=1, expires_at=2)).role
    for role in ("employee", "lead", "manager"):
        claims = AssistantClaims(subject="u", role=role, issued_at=1, expires_at=2)
        assert _status(require_admin, claims) == 403


def test_filter_ceilings_follow_role_ladder():
    expected = {"employee": 1, "lead": 2, "manager": 3, "admin": 3}
    for role, level in expected.items():
        claims = AssistantClaims(subject="u", role=role, issued_at=1, expires_at=2)
        filtr = claims_to_access_filter(claims, tenant="acme")
        assert filtr.max_access_level == level
        assert filtr.tenant == "acme"
        assert filtr.departments == ["all"]


def test_filter_rejects_unknown_role_and_empty_tenant():
    claims = AssistantClaims(subject="u", role="superadmin", issued_at=1, expires_at=2)
    assert _status(claims_to_access_filter, claims, tenant="acme") == 403
    admin = AssistantClaims(subject="u", role="admin", issued_at=1, expires_at=2)
    try:
        claims_to_access_filter(admin, tenant="")
    except ValueError:
        pass
    else:
        raise AssertionError("empty tenant must fail loud")
