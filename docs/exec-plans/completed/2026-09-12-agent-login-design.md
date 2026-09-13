# Design: agent login + user admin (agentic-assistant)

<!-- Implemented 2026-09-12; moved to docs/exec-plans/completed after validation. -->

<!-- Spec for the login pass. Approach A (agent-local auth) selected 2026-09-12.
     Lives under exec-plans/active per AGENTS.md §7 instead of the skill-default
     docs/superpowers/specs/. Frontend token storage + chat websocket are
     explicitly out of scope. -->

## Objective

Give `services/agentic-assistant` a standalone identity subsystem so a user can
`POST /auth/login` with email + password and receive a `libs/auth` JWT that the
existing dual-auth mutations (and the future chat socket) accept. An env-seeded
admin can provision `employee` / `lead` / `manager` / `admin` users via admin-only
routes. No Supabase in the agent; no login flow exists anywhere else to reuse.

## Decisions (locked with user)

1. Agent-local auth against Neon `assistant_users` (libs/auth store/crypto/tokens).
2. First admin env-seeded on startup (`AGENTIC_ASSISTANT_ADMIN_EMAIL` +
   `AGENTIC_ASSISTANT_ADMIN_PASSWORD`).
3. Scope = login + admin user management in one pass (login alone is a dead end).
4. `agent/` is reasoning-only: identity code lives in new top-level `src/models/`.
5. No `GET /auth/me`: the JWT carries `sub`/`role`/`exp`; the frontend reads
   identity from the stored token. Token storage is frontend scope, not this pass.
6. Rate limiting deferred to tech debt (gateway/slowapi later).

## Routes (`src/api/auth.py`, prefix `/auth`)

| Method + path              | Auth            | Success              | Errors                              |
|----------------------------|-----------------|----------------------|-------------------------------------|
| `POST /auth/login`         | none            | `200 {access_token, token_type: "bearer", expires_in, user: {id, email, role}}` | `401 "Invalid email or password"` (unknown user and wrong password identical — no enumeration) |
| `POST /auth/users`         | admin JWT       | `201` public user shape | `403` non-admin; `409` duplicate email |
| `GET /auth/users`          | admin JWT       | `200` list, limit 200  | `403` non-admin                     |
| `PATCH /auth/users/{id}/role` | admin JWT    | `200` public user shape | `403` non-admin; `404` unknown id; `422` self-role-change (an admin cannot change their own role — no self-lockout) |

Request shapes reuse the lib: `auth.types.LoginRequest`, `auth.types.CreateUserRequest`.
Response user shape reuses `auth.types.AssistantUser`. Tokens minted with
`auth.tokens.mint_assistant_token(user_id, role, secret, ttl)`; verified with
`auth.tokens.decode_assistant_token` (issuer `assistant-auth`, HS256).

## Models (`src/models/` — new package, sibling of `agent/` and `api/`)

- `src/models/__init__.py` — package docstring only.
- `src/models/users.py` (single file, ~150 lines) — all sync, lib-style:
  - `get_pool(agentic_assistant_database_url)` — `psycopg_pool.ConnectionPool`
    (thread-safe; sync
    matches the lib's `%s` store contract, so handlers stay sync `def` and
    FastAPI's threadpool handles concurrency; no async-pool machinery).
  - `ensure_and_seed(conn, admin_email, admin_password)` — `ensure_assistant_tables`
    + upsert seed admin (insert when missing; never overwrite/demote an existing
    row) + `record_audit_event("admin.seeded")`. No env → caller logs a warning.
  - `authenticate(conn, email, password)` → public user dict or None (bcrypt via
    `auth.crypto.verify_password`; hash never leaves this module).
  - `create_user`, `list_users`, `set_role` — thin guards over `auth.store`
    (`insert_user`/`list_users`/`set_user_role`) + audit events
    (`user.created`, `user.role_changed`, `login.success`, `login.failed`).

## Wiring (`main.py` + `config.py`)

- Settings use explicit `AGENTIC_ASSISTANT_*` aliases:
  `AGENTIC_ASSISTANT_DATABASE_URL`, `AGENTIC_ASSISTANT_ADMIN_EMAIL`,
  `AGENTIC_ASSISTANT_ADMIN_PASSWORD`, `AGENTIC_ASSISTANT_JWT_SECRET`,
  `AGENTIC_ASSISTANT_JWT_TTL_SECONDS`, and
  `AGENTIC_ASSISTANT_SERVICE_TOKEN`. The API's outbound agent settings use
  `AGENTIC_ASSISTANT_SERVICE_URL` and `AGENTIC_ASSISTANT_SERVICE_TOKEN`.
- Lifespan: open pool (503 auth routes when `database_url` empty — fail closed,
  same pattern as the service-token 503), ensure + seed, close on shutdown.
- Mount `api.auth.router`. Runtime dep: pool from app state; JWT admin dep reuses
  `agent/authz.py` (`require_admin` accepts admin JWT; service token must NOT
  authorize user-admin — machine callers don't provision users).

## Security

- Generic 401 detail on login; 401 bad/expired JWT, 403 non-admin (existing `authz`
  semantics reused).
- Passwords: bcrypt via lib (72-byte cap); never logged, never returned.
- Seed password lives only in env (Railway secret); startup logs email, never secret.
- `assistant_jwt_secret` (`AGENTIC_ASSISTANT_JWT_SECRET`) must now be non-empty in any env serving browser traffic
  (previously optional); empty still fails closed.

## Tests (TDD, `tests/test_auth_api.py`)

Fake-connection doubles mirroring lib `test_store.py` + pool/app-state override —
no live DB. Cases: login success shape (`token_type`, `expires_in`, user has no
hash); wrong-password and unknown-user → identical 401 detail; duplicate → 409;
non-admin JWT → 403 on every `/users` route; service token → 401 (not a JWT — machine callers can't provision users); self-role-change → 422;
unknown id → 404; seed inserts-when-missing, never-overwrites.

## Docs + env (same change)

- `docs/features/assistant-auth.md` (login section), `.env.example`
  (`AGENTIC_ASSISTANT_DATABASE_URL`, `AGENTIC_ASSISTANT_ADMIN_EMAIL/PASSWORD`,
  `AGENTIC_ASSISTANT_JWT_TTL_SECONDS`, and the service URL/token names),
  this plan → completed on merge, tech-debt row for login rate limiting.
- New deps `psycopg[binary]` and `psycopg-pool` in agent `pyproject.toml` (+ lock); isort
  `known-first-party += ["models"]`.

## Out of scope

Frontend token storage/session handling; chat websocket (next pass — verifies the
same JWTs); password reset/change; brute-force rate limiting; Supabase role sync
(Supabase `user`/`admin` and assistant `employee/lead/manager/admin` are
independent ladders by design).
