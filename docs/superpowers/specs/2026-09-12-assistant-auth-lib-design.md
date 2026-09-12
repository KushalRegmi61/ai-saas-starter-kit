# Spec: assistant auth as a shared lib (`libs/auth`)

## Status
Approved 2026-09-12 (approach A). Auth iteration only — manager dashboard
cards, per-project scoping, and agent chat tools are deferred.

## Goal
Ship knowledge-assistant identity (roles `employee/lead/manager/admin`) as an
importable workspace lib any service can use, mirroring how `libs/rag`
(`ai-saas-rag`) is packaged and consumed. Supabase `profiles.role`
(`user|admin`) is untouched — two separate systems.

## Non-goals (this iteration)
Manager project-progress dashboard, lead/employee per-project scoping,
agentic chat, restricting Supabase `/upload/*`.

## First principles applied (monorepo conventions)
1. Lib address: `libs/auth/`, dist `ai-saas-auth`, import package `auth`;
   `pyproject.toml` + `src/` layout + setuptools `packages.find where=["src"]`
   (mirrors `libs/rag/pyproject.toml`, `services/shared/pyproject.toml`).
2. Deps declared in the lib's `pyproject.toml` (`>=` ranges); exact `==` pins
   live in each consuming service's `requirements.txt` (reproducibility rule,
   `docs/RELIABILITY.md`). New third-party dep: `bcrypt`.
3. Lib is stateless: no FastAPI, no pool, no settings ownership. DB functions
   take a caller-provided `conn` (duck-typed `execute`); crypto/token
   functions take explicit params. No imports of `rag`, `app.*`, or `shared`.
4. Quality: copied ruff config (`known-first-party = ["auth"]`, T20, <300
   lines/file), `testpaths = ["tests"]`, tests for every behavior with fake
   connections (no live DB — `libs/rag/tests/test_registry.py` pattern).
5. Wiring: `-e ../../libs/auth` editable pin in consumer `requirements.txt`;
   `pnpm lint:auth` / `pnpm test:auth` scripts mirroring `lint:rag/test:rag`;
   feature doc `docs/features/assistant-auth.md` (doc mapping: feature logic
   → `docs/features/`).
6. Relationship to locked split-plan decisions: #5 ("no shared lib imports")
   is scoped to retrieval logic; auth primitives are version-stable and hold
   no service state, so lockstep-redeploy risk does not apply. #3
   (centralized `resolve_filter()`) is preserved: the lib's
   `role_to_filter()` is the pure mapping each service calls before
   enforcing; a future policy engine plugs in behind the same function.

## Public surface (`auth/__init__.py`)
- `types`: `ASSISTANT_ROLES`, `AssistantUser` (no hash), `AssistantClaims`,
  `LoginRequest`, `CreateUserRequest`, `FilterSpec`.
- `crypto`: `hash_password`, `verify_password` (72-byte pre-check).
- `tokens`: `mint_assistant_token`, `decode_assistant_token`
  (`sub/role/exp/iat/iss`, default TTL 12h), `InvalidToken`.
- `store`: `ensure_assistant_tables`, `find_user_by_email`,
  `find_user_by_id`, `insert_user`, `list_users`, `set_user_role`,
  `record_audit_event` (all take `conn`; emails normalized to lowercase).
- `mapping`: `ROLE_LEVELS = {employee:1, lead:2, manager:3, admin:3}`,
  `role_to_filter(role, tenant)` → `FilterSpec(departments=["all"],
  max_access_level, tenant)`; unknown role raises `UnknownRole`.

## Service integration (follows lib landing)
API owns pool (existing Neon pool), routes (`/assistant/*`), and FastAPI
`require_assistant_admin` Depends; service layer orchestrates lib calls.
`rag_auth.py` cutover replaces domain/actions decode with lib token verify +
`role_to_filter`. Assistant-admin upload reuses upload service with owner
`assistant/{id}` and required explicit department/level. Bootstrap: create
admin from env only when users table is empty.

## Verification
`pnpm lint:auth && pnpm test:auth && pnpm lint:api && pnpm test:api &&
pnpm check:structure`. Pass criteria: ruff clean, all pytest green, no file
>300 lines, docs updated in the same change.
