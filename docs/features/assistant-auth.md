<!-- last_verified: 2026-09-12 -->
# Assistant Auth (shared lib)

Knowledge-assistant identity as an importable workspace lib (`libs/auth`,
dist `ai-saas-auth`), mirroring how `libs/rag` is packaged and consumed.
Supabase `profiles.role` (`user|admin`) is a separate system and is untouched.

## Contract

- Public surface: `auth/__init__.py` re-exports `types`, `crypto`
  (`hash_password`/`verify_password`), `tokens` (`mint_assistant_token` /
  `decode_assistant_token`), `store` (Neon `assistant_users` + audit CRUD),
  `mapping` (`role_to_filter`).
- The lib is stateless: no FastAPI, no pool, no settings. Secrets/TTLs are
  explicit params; store functions take the caller's DB connection.
- The lib never imports `libs/rag`: `role_to_filter` returns a plain
  `FilterSpec` and the consuming service builds its own `AccessFilter`.

## Roles (service-defined policy)

The lib owns the mechanism, the consuming service owns the policy. The
default ladder is `employee → 1 (internal)`, `lead → 2 (confidential)`,
`manager → 3 (restricted)`, `admin → 3 (restricted)` — every rung
cross-department (`departments=["all"]`) plus the caller's tenant. `admin`
shares manager's retrieval ceiling deliberately: 3 is the top of the shared
scale, and admin's authority is capability-based (user management, uploads),
gated on the role claim by the consuming service rather than by FilterSpec.
A service passes its own `RolePolicy` (rung names, ceilings, department
scope, free-form `attributes` for future project scoping) to
`role_to_filter` / token mint/verify; the policy is the sole authority and
is never merged with the default. Each policy declares its own `ceiling`
(default 3, matching libs/rag's scale) so services with coarser or finer
scales validate rungs against the backend they enforce — a policy can never
grant what its backend cannot understand. Unknown roles fail closed
(`UnknownRole` / `InvalidToken`). `FilterSpec.attributes` flows through so
services can attach service-specific claims without lib changes.

## Tokens

JWT `sub/role/exp/iat/iss` (`iss=assistant-auth`, HS256), default TTL 12h.
Passwords are bcrypt-hashed; over-72-byte passwords are rejected rather than
silently truncated.

## Tests

`libs/auth/tests/` (crypto, tokens incl. tamper/expiry/unknown-role,
mapping ladder, store SQL-shape on fake connections — no live DB).

## Service integration (agentic-assistant)

`services/agentic-assistant/src/agent/authz.py` is the reference consumer:
`get_claims` (assistant-JWT verify → 401), `require_admin` (`role == "admin"`
→ 403 otherwise), `require_jwt_admin` (JWT-only admin gate for identity
management), `require_service_or_admin` (machine service token **or** admin JWT
— either suffices, so API-forwarded auto-index keeps working while browser
callers authenticate directly after frontend login), and
`claims_to_access_filter` (`role_to_filter` → `AccessFilter`, emp 1 / lead 2 /
mgr+admin 3). Both mutation routes (`POST /ingest`, `DELETE /sources`) use the
dual-auth dependency; user secret is `AgentSettings.assistant_jwt_secret`
(`AGENTIC_ASSISTANT_JWT_SECRET`, empty = JWT path absent, fail closed). The app
also serves CORS for the browser-direct admin flow (Bearer, no cookies; tighten
`allow_origins` once the frontend domain is known).

The agent owns login and user administration:

- `POST /auth/login` accepts email/password and returns a 12-hour-by-default
  assistant JWT plus the public user shape. Unknown users and bad passwords
  return the same `401 Invalid email or password` response.
- `POST /auth/users`, `GET /auth/users`, and
  `PATCH /auth/users/{id}/role` require an admin assistant JWT. Service tokens
  cannot provision or modify human users.
- User tables and audit events are created in the shared Neon database by
  `libs/auth`. `AGENTIC_ASSISTANT_ADMIN_EMAIL` and
  `AGENTIC_ASSISTANT_ADMIN_PASSWORD` seed the first admin without overwriting
  an existing row.
- `AGENTIC_ASSISTANT_DATABASE_URL` missing → auth routes return `503`;
  configured but unreachable → service startup fails. Partial bootstrap
  credentials fail startup.

The service uses the `AGENTIC_ASSISTANT_*` namespace for its identity and
service-integration settings. Tests:
`services/agentic-assistant/tests/test_authz.py` (dual-auth matrix, ceilings,
fail-closed cases) and `test_auth_api.py` (login/admin route contracts).

Deferred: an HTTP search surface (retrieval stays tool-only;
`claims_to_access_filter` is the seam the future caller uses), API forwarding
of the caller's JWT, manager dashboard, per-project scoping, frontend token
storage, password reset/change, and login rate limiting. See
`docs/superpowers/specs/2026-09-12-assistant-auth-lib-design.md`.
