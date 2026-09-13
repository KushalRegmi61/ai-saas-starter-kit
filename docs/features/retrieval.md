<!-- last_verified: 2026-09-13 -->
# Retrieval (Phase 1)

Single-tool RAG retrieval over Qdrant vectors + Neon registry/cache.

## Contract

- Public surfaces: synchronous `rag.retrieval.search_rag(...)` for compatibility and native async `rag.retrieval.search_rag_async(...) -> SearchResponse` for the streaming assistant (both re-exported from `rag`). Router, RRF, reranker, cache, and RBAC remain internal.
- HTTP: the RAG library remains HTTP-agnostic. The agentic-assistant exposes
  authenticated `WS /ask` for persistent streamed chat and
  `GET /conversations/{id}` for owned history; its internal
  `search_knowledge_base` tool remains bound to the host-resolved
  `AccessFilter`. The old `POST /retrieval/search` route was removed with the
  API's RAG logic (2026-09-12).
- Phases: retrieval now; direct ingestion (`rag/ingestion/index_document`) later; `services/auth` extraction later. No S3, no Lambda triggers in this package.
- Search strategy is locked to `hybrid` (2026-09-13): the web client offers no mode choice and always sends `search_mode: "hybrid"`. The backend literal still accepts `semantic | hybrid | auto`, but `vector` / `bm25` were never valid on the wire (Pydantic 422) and retrieval has no keyword-only branch — standalone BM25 would be new `libs/rag` feature work, not alignment.
- Evidence wire shape (2026-09-13): `done.sources` carries the last tool call's chunks as `{source, page?, chunk_index?, score?, snippet?}` — serialised `Source` dicts plus a snippet truncated to 300 chars (`SNIPPET_CHARS` in `agent/tools/search.py`). The web `toEvidence()` adapter (`lib/use-assistant-chat.ts`) maps these to `RAGSourceEvidence` (`doc_id ← source`, `title ← basename + page`); `score`/`snippet` stay optional and the panel hides those parts when absent instead of rendering `NaN%`/empty quotes. History reloads carry `sources: []` (per-turn sources are not persisted) — see Phase 5.

## WebSocket wire protocol (`WS /ask`, 2026-09-13)

| Direction | Message | Shape |
|---|---|---|
| Client → server | `auth` | `{type, access_token}` (short-lived `ws-ticket`; bad ticket → close `4401`) |
| Server → client | `ready` | `{type, expires_at}` |
| Client → server | `ask` | `{type, request_id, question, top_k?, search_mode: "hybrid", conversation_id?}` — one active ask per socket (`request_in_progress` otherwise) |
| Server → client | `step` | `{type, request_id, name?, text?, query?, expanded_queries?, sources?}` — `name` is the graph node (`classify_intent`, `agent`, `tools`, …) or service note (`agent_budget`, memory compaction) |
| Server → client | `token` | `{type, request_id, content}` — generation nodes only (classifier suppressed) |
| Server → client | `done` | `{type, request_id, conversation_id, answer, sources, grounded, rewritten_question, workflow_steps}` |
| Server → client | `error` | `{type, request_id?, code, text}` — `invalid_message`, `request_in_progress`, `invalid_request`, `not_found`, `forbidden`, `server_error` |
| HTTP | `GET /conversations/{id}` | Owned history as `[{turn_index, question, answer, sources: [], created_at}]`; 404/403 on missing/forbidden |

The assistant chat path uses async psycopg/Qdrant/OpenAI adapters; semantic and
corpus retrieval run concurrently, while CPU-only ranking is isolated from the
event loop. Parallel tool calls in one step merge (`sources`/`results` accumulate,
`workflow_steps` last-wins); every LLM call is bounded by
`AGENTIC_ASSISTANT_LLM_TIMEOUT_SECONDS` (default 120s).

## Pipeline

`resolve_search_mode` (deterministic router) → embed query (OpenAI) → parallel Qdrant filtered semantic + corpus scroll → BM25 + RRF (k=60, candidate `max(reranker_top_n, top_k*4, 20)`) → rerank (`none` default) → `SearchResponse` via shared formatting (`[i] Source: {source}[, page X]`). Cache wraps the result: key `SHA(question|CTX:ctx_hash)`, Tier-1 exact + Tier-2 semantic ≥0.92 same-context, TTL + `hit_count`.

## RBAC

Caller passes `AccessFilter(departments, max_access_level)`; rag only enforces. Qdrant filter: department ∈ allowed (or `all`) AND access_level ∈ allowed-labels. BM25 corpus filtered in-process with the same predicate. Role→filter mapping lives in `libs/auth` (`role_to_filter` + service-owned `RolePolicy`); the old `services/api/app/repo/rag_auth.py` adapter was deleted with the API's RAG logic (2026-09-12).

## Configuration

`QDRANT_URL/QDRANT_API_KEY/QDRANT_COLLECTION`, `AGENTIC_ASSISTANT_DATABASE_URL` (Neon + pgvector), `OPENAI_API_KEY/BASE_URL`, `AGENTIC_ASSISTANT_JWT_SECRET`, and the agentic-assistant memory/WebSocket settings. Unconfigured → `503`. The chat socket requires a short-lived assistant WebSocket ticket and stores conversation turns in the same Neon database.

## Tests

`libs/rag/tests/` (router, RRF, formatting, RBAC, cache keys, tenant) + `libs/auth/tests/test_mapping.py` (role→filter). Tenant coverage lives in `libs/rag/tests/test_tenant.py`.

## Multi-service use (tenant + portable filter)

- Tenant semantics: `tenant=None` normalizes to `"default"`. The tenant is stamped on the Qdrant payload, the Neon registry row, and the query-cache key; chunk/registry deletes scoped; delete-path cache flush is scoped per tenant (over-invalidation only within the tenant) and point IDs are tenant-qualified (`{tenant}:{source}:{chunk_index}:{text}` (→ sha256)).
- Host recipe: each host resolves its own identity to an `AccessFilter` and passes `tenant` on index/delete calls. Reference implementation: `libs/auth/mapping.py::role_to_filter` (the API stamps `AGENTIC_ASSISTANT_TENANT` on its forwarded ingest/purge calls).
- Non-goals: no required filter yet (a no-filter call still searches permissively), no per-call collection override, no external policy engine (Cedar/OPA) — the `attributes` field on `AccessFilter` is the seam for one later.
- Dev-DB reset note: pre-tenant dev data (Qdrant points with old `_chunk_id` payloads lacking `tenant`, plus existing `documents`/`query_cache` rows) are orphans — reset the `chunks` collection and the `documents`/`query_cache` tables on legacy dev databases (no production data exists).

## Ingestion (agentic-assistant service)

- Trigger: `finalize_upload` (`services/api/app/service/upload.py`) best-effort forwards via `_maybe_index_in_rag` → `repo/ingest_client.index_document_remote` → `POST /ingest` on the agentic-assistant service (service-token auth). PDF + plain text (`.txt/.md`) only; skipped (`rag_indexed=false`) when the agent service is unconfigured or forwarding fails.
- Engine: `rag.ingestion.index_document` now runs inside `services/agentic-assistant` (`src/api/ingest.py`, dual-authed via `agent/authz.py`); retrieval stays an agent-internal tool with no HTTP route.
- Metadata: explicit `department`/`access_level` args win; else filename-prefix inference (`infer_document_metadata`); else `general`/`internal`. Unknown explicit values are rejected (400) by the API before forwarding.
- Idempotency: SHA-256 over loaded doc texts; a matching registry `content_hash` for the source skips re-index (0 chunks). Otherwise old chunks are replaced and the query cache flushed.
- Failure contract: indexing never fails the upload — errors log and `FileUploadResponse` returns `rag_indexed=false`.
- Delete purges: file deletion best-effort calls the agent `DELETE /sources` (Qdrant chunks + registry row + cache flush); the B2 delete stands regardless.
- Deferred: background jobs, docx loaders.
