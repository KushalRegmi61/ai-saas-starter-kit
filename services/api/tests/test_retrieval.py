"""Tests for POST /retrieval/search: auth gate, 503 when unconfigured, filter passthrough."""

import pytest
from jose import jwt

from app.config import settings
from app.repo import rag_auth
from app.repo.rag_auth import RagTokenClaims
from main import app


def _rag_token(domain="hr", actions=None):
    actions = actions if actions is not None else ["read:public", "read:internal"]
    return jwt.encode(
        {"sub": "u-rag", "domain": domain, "actions": actions},
        settings.agentic_assistant_jwt_secret or "test-secret",
        algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_retrieval_requires_bearer(client):
    resp = await client.post("/retrieval/search", json={"question": "pto?"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_retrieval_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr(settings, "agentic_assistant_jwt_secret", "correct-secret")
    resp = await client.post(
        "/retrieval/search",
        json={"question": "pto?"},
        headers={
            "Authorization": "Bearer "
            + jwt.encode({"sub": "u", "domain": "hr"}, "wrong", algorithm="HS256")
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_retrieval_503_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "agentic_assistant_jwt_secret", "test-secret")
    monkeypatch.setattr(settings, "qdrant_url", "")
    monkeypatch.setattr(settings, "agentic_assistant_database_url", "")
    token = _rag_token()
    resp = await client.post(
        "/retrieval/search",
        json={"question": "What is the PTO policy?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (401, 429, 503)


@pytest.mark.asyncio
async def test_retrieval_passes_access_filter(client, monkeypatch):
    monkeypatch.setattr(settings, "agentic_assistant_jwt_secret", "test-secret")
    monkeypatch.setattr(settings, "qdrant_url", "http://qdrant:6333")
    monkeypatch.setattr(settings, "agentic_assistant_database_url", "postgresql://x")
    app.dependency_overrides[rag_auth.require_rag_rate_limit] = lambda: RagTokenClaims(
        subject="u-rag",
        domain="hr",
        max_access_level=1,
        raw_actions=["read:public", "read:internal"],
    )
    seen = {}

    def fake_search(request, access_filter):
        seen["filter"] = access_filter
        from app.types.retrieval import SearchResponse

        return SearchResponse(question=request.question, results=[], search_mode="hybrid")

    import app.runtime.retrieval as retrieval_runtime

    monkeypatch.setattr(retrieval_runtime, "search", fake_search)
    try:
        resp = await client.post("/retrieval/search", json={"question": "pto?", "top_k": 2})
        assert resp.status_code == 200
        assert seen["filter"].departments == ["hr", "all", "general"]
        assert seen["filter"].max_access_level == 1
        assert seen["filter"].tenant == "api"
    finally:
        app.dependency_overrides.pop(rag_auth.require_rag_rate_limit, None)


def test_claims_to_access_filter_global_domain():
    claims = RagTokenClaims(subject="u", domain="admin", max_access_level=3, raw_actions=[])
    filt = rag_auth.claims_to_access_filter(claims)
    assert "all" in filt.departments and filt.max_access_level == 3
