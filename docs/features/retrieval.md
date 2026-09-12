<!-- last_verified: 2026-09-12 -->
# Retrieval (Phase 1)

Single-tool RAG retrieval over Qdrant vectors + Neon registry/cache.

## Contract

- Public surface: `rag.retrieval.search_rag(question, top_k, search_mode, access_filter) -> SearchResponse` (re-exported as `rag.search_rag`). Only entrypoint; router, RRF, reranker, cache, and RBAC are internal.
- HTTP: none on the API — search is an agent-internal tool (`search_knowledge_base` in `services/agentic-assistant`, bound to the host-resolved `AccessFilter`). The old `POST /retrieval/search` route was removed with the API's RAG logic (2026-09-12).
- Phases: retrieval now; direct ingestion (`rag/ingestion/index_document`) later; `services/auth` extraction later. No S3, no Lambda triggers in this package.

## Pipeline

`resolve_search_mode` (deterministic router) → embed query (OpenAI) → parallel Qdrant filtered semantic + corpus scroll → BM25 + RRF (k=60, candidate `max(reranker_top_n, top_k*4, 20)`) → rerank (`none` default) → `SearchResponse` via shared formatting (`[i] Source: {source}[, page X]`). Cache wraps the result: key `SHA(question|CTX:ctx_hash)`, Tier-1 exact + Tier-2 semantic ≥0.92 same-context, TTL + `hit_count`.

## RBAC

Caller passes `AccessFilter(departments, max_access_level)`; rag only enforces. Qdrant filter: department ∈ allowed (or `all`) AND access_level ∈ allowed-labels. BM25 corpus filtered in-process with the same predicate. Role→filter mapping lives in `libs/auth` (`role_to_filter` + service-owned `RolePolicy`); the old `services/api/app/repo/rag_auth.py` adapter was deleted with the API's RAG logic (2026-09-12).

## Configuration

`QDRANT_URL/QDRANT_API_KEY/QDRANT_COLLECTION`, `AGENTIC_ASSISTANT_DATABASE_URL` (Neon + pgvector), `OPENAI_API_KEY/BASE_URL`, `AGENTIC_ASSISTANT_JWT_SECRET/ALGORITHM`, `AGENTIC_ASSISTANT_RATE_LIMIT_*`. Unconfigured → `503`. Rate limit is a fixed-window counter in Neon; skipped when no DB URL (local dev).

## Tests

`libs/rag/tests/` (router, RRF, formatting, RBAC, cache keys, tenant) + `libs/auth/tests/test_mapping.py` (role→filter). Tenant coverage lives in `libs/rag/tests/test_tenant.py`.

## Multi-service use (tenant + portable filter)

- Tenant semantics: `tenant=None` normalizes to `"default"`. The tenant is stamped on the Qdrant payload, the Neon registry row, and the query-cache key; chunk/registry deletes scoped; delete-path cache flush is scoped per tenant (over-invalidation only within the tenant) and point IDs are tenant-qualified (`{tenant}:{source}:{chunk_index}:{text}` (→ sha256)).
- Host recipe: each host resolves its own identity to an `AccessFilter` and passes `tenant` on index/delete calls. Reference implementation: `libs/auth/mapping.py::role_to_filter` (the API stamps `AGENTIC_ASSISTANT_TENANT` on its forwarded ingest/purge calls).
- Non-goals: no required filter yet (a no-filter call still searches permissively), no per-call collection override, no external policy engine (Cedar/OPA) — the `attributes` field on `AccessFilter` is the seam for one later.
- Dev-DB reset note: pre-tenant dev data (Qdrant points with old `_chunk_id` payloads lacking `tenant`, plus existing `documents`/`query_cache` rows) are orphans — reset the `chunks` collection and the `documents`/`query_cache` tables on legacy dev databases (no production data exists).

## Ingestion (agentic-assistant service)

- Trigger: `finalize_upload` (`services/api/app/service/upload.py`) best-effort forwards via `_maybe_index_in_rag` → `repo/ingest_client.index_document_remote` → `POST /ingest` on the agentic-assistant service (service-token auth). PDF + plain text (`.txt/.md`) only; skipped (`rag_indexed=false`) when the agent service is unconfigured or forwarding fails.
- Engine: `rag.ingestion.index_document` now runs inside `services/agentic-assistant` (`agent/runtime/ingest.py`); retrieval stays an agent-internal tool with no HTTP route.
- Metadata: explicit `department`/`access_level` args win; else filename-prefix inference (`infer_document_metadata`); else `general`/`internal`. Unknown explicit values are rejected (400) by the API before forwarding.
- Idempotency: SHA-256 over loaded doc texts; a matching registry `content_hash` for the source skips re-index (0 chunks). Otherwise old chunks are replaced and the query cache flushed.
- Failure contract: indexing never fails the upload — errors log and `FileUploadResponse` returns `rag_indexed=false`.
- Delete purges: file deletion best-effort calls the agent `DELETE /sources` (Qdrant chunks + registry row + cache flush); the B2 delete stands regardless.
- Deferred: background jobs, docx loaders.
