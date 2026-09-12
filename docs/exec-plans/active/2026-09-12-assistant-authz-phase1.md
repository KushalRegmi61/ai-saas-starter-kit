# Plan: assistant authz phase 1 (agentic-assistant verifies, admin mutates)

**Status: implemented 2026-09-12** (commit follows). Goal: wire `libs/auth`
into `services/agentic-assistant` so `POST /ingest` + `DELETE /sources` admit
the machine service token **or** an admin assistant JWT, and every role gets a
resolvable retrieval filter — while login/minting stays out of this service.

## Decisions (user-confirmed)

- Dual-auth on mutations: service token OR admin JWT, either suffices.
  Browser flow after frontend login: login → `Bearer <admin JWT>` direct to
  the agent. API-forwarded auto-index (service token, no user JWT) keeps working.
- Agent verifies only: no `/auth/*` routes, no user store, no Neon pool here.
- Retrieval: role-derived filters for all four roles (emp 1 / lead 2 /
  mgr+admin 3); no new HTTP search route in this phase (tool-only stays).

## Changes

- `src/agent/config.py`: `assistant_jwt_secret` (empty = JWT path absent).
- New `src/agent/authz.py`: `get_claims` (401) / `require_admin` (403) /
  `require_service_or_admin` (503 when neither credential configured, else
  401/403; returns claims for JWT callers, None for service-token callers) /
  `claims_to_access_filter` (UnknownRole → 403, empty tenant → ValueError).
- `src/api/ingest.py` (moved out of `src/agent/runtime/` so routes live outside the agent package): both routes use the dual-auth dependency;
  422 / `{"purged": false}` contract unchanged. `require_service_token`
  removed (logic moved into `authz._valid_service_token`).
- `main.py`: CORS middleware (Bearer, no cookies; `allow_origins=["*"]` until
  the frontend domain is known — tracked as debt).
- `tests/test_authz.py` (9 tests): admin-JWT allow, non-admin 403 ×3 roles on
  both routes, bad/expired JWT 401, service-token precedence, 503 matrix,
  claims roundtrip, admin gate, per-role ceilings, unknown-role/empty-tenant.
- Docs: `docs/features/assistant-auth.md` (phase-1 section), `.env.example`
  (`ASSISTANT_JWT_SECRET`), tech-debt rows (`/ask`, JWT forwarding, CORS).

## Gates

`uv sync --all-packages --all-groups` (no lock change — `python-jose` arrives
transitively via `ai-saas-auth`), `ruff check` + `ruff format --check` clean,
agent suite 31 passed (22 existing + 9 new).

## Follow-ups (tracked in tech-debt-tracker)

1. `POST /ask` authed search route reusing `get_claims` +
   `claims_to_access_filter` (needed for browser search).
2. API forwards caller JWT (`ingest_client.py`) + agent logs `claims.subject`.
3. Tighten CORS origins to the frontend domain.
