# RAG Multi-Service Hardening (Tenant + Portable Filter) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `libs/rag` safe for independent projects sharing one backend: an optional `tenant` discriminator isolating corpora end-to-end, and a portable `AccessFilter` any host can construct from its own auth.

**Architecture:** Additive, backward-compatible change. `tenant: str | None = None` threads through ingest, retrieval, deletes, registry, and cache; `None` preserves today's single-corpus behavior exactly. `AccessFilter` gains `tenant` + generic `attributes` (for service-specific claims) while `departments`/`max_access_level` enforcement is untouched. Hosts (starting with `services/api`) pass their own tenant identity; the lib never resolves identity, only enforces what it is given.

**Tech Stack:** Python 3.11+, Pydantic v2, Qdrant payload filters, Neon Postgres (+pgvector), pytest with mock-connection SQL assertions (existing `test_registry.py` pattern — no live DB needed).

**Spec:** `docs/features/retrieval.md` (current contract) + this plan's Locked decisions below. There is no separate design doc; user decisions from 2026-09-12 shaping this plan: tenant optional (no migration — no production data), filter evolved additively for multi-service use (not made required).

## Global Constraints

- `libs/rag` stays auth-agnostic: it accepts `AccessFilter`, never constructs policy from identity. No JWT, no user lookups, no host imports enter the lib.
- Files stay under 300 lines (`qdrant_repo.py` is 207, `neon_repo.py` 154, `search.py` 114 — all additions must fit).
- Structured JSON logging only — no `print()` (ruff `T20`); ruff `E,W,F,I,B,UP,T20,SIM,RUF` clean, `known-first-party = ["rag"]`.
- Tests for every behavior change; mock external backends (existing tests never touch Qdrant/Neon/OpenAI — keep it that way).
- Qdrant payload schema extends to `{text, source, page, chunk_index, department, access_level, tenant}` — keys only ever added, never renamed.
- Run: `pnpm lint:rag && pnpm test:rag && pnpm lint:api && pnpm test:api && pnpm check:structure`.

## Locked decisions (do not relitigate during execution)

1. **Tenant is `str | None = None` everywhere, normalized once.** `normalize_tenant(t)` in `rag/retrieval/rbac.py` returns `t or "default"`. Ingest stamps the normalized value into chunk metadata; retrieval/delete/registry/cache normalize at entry. `None` in, `"default"` on the wire — the database never sees NULL, so uniqueness constraints stay sound.
2. **Search reads tenant from `AccessFilter.tenant`; ingest/delete take explicit `tenant` params.** One source of truth per path, no dual-pass consistency checks.
3. **No data migration.** User confirmed no production data. DDL is idempotent (`IF NOT EXISTS` / `DO ... EXCEPTION`) so fresh and legacy dev databases both converge; legacy dev DBs get tenant `"default"` backfill statements that are no-ops when empty.
4. **Filter stays optional in `search_rag` signature.** Today's default (`departments=["all"]`, level 0) is unchanged. Fail-closed-by-default is recorded as tech debt (Task 8), not implemented here.
5. **Cache flush stays correct-by-over-invalidation.** `flush_cache` gains an optional tenant scope, but a global flush remains valid (correctness-safe, only perf). No cross-tenant answer leak is possible via Tier-1 (tenant is in the key) or Tier-2 (tenant column filters the semantic lookup).

---

### Task 1: Portable filter type + tenant normalization

**Files:**
- Modify: `libs/rag/src/rag/types.py:10-14`
- Modify: `libs/rag/src/rag/retrieval/rbac.py` (append `normalize_tenant`)
- Test: `libs/rag/tests/test_tenant.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces (used by Tasks 2–7):
  - `AccessFilter(departments, max_access_level, tenant: str | None = None, attributes: dict[str, str] = {})`
  - `normalize_tenant(t: str | None) -> str` — returns `t or "default"`.

- [ ] **Step 1: Write the failing test** — create `libs/rag/tests/test_tenant.py`:

```python
from rag.retrieval.rbac import normalize_tenant
from rag.types import AccessFilter


def test_access_filter_carries_tenant_and_attributes():
    filt = AccessFilter(
        departments=["hr", "all", "general"],
        max_access_level=1,
        tenant="api",
        attributes={"project": "knowledge-assistant"},
    )
    assert filt.tenant == "api"
    assert filt.attributes == {"project": "knowledge-assistant"}


def test_access_filter_defaults_preserve_legacy_behavior():
    filt = AccessFilter(departments=["all"], max_access_level=0)
    assert filt.tenant is None
    assert filt.attributes == {}


def test_normalize_tenant():
    assert normalize_tenant(None) == "default"
    assert normalize_tenant("") == "default"
    assert normalize_tenant("api") == "api"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py -v`
Expected: FAIL with `TypeError` / validation error on unexpected `tenant` keyword, plus `ModuleNotFoundError`-style failure on `normalize_tenant` import (assert the exact error text before proceeding).

- [ ] **Step 3: Implement** — in `types.py`, extend the model (Pydantic `Field` is already imported):

```python
class AccessFilter(BaseModel):
    """Resolved access policy passed into retrieval. Never constructed by rag itself.

    `tenant` isolates independent projects sharing one backend (None =
    legacy single-corpus behavior, normalized to "default" on the wire).
    `attributes` carries service-specific claims the lib ignores today and
    hosts may enforce tomorrow (ABAC seam).
    """

    departments: list[str]
    max_access_level: int
    tenant: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
```

Append to `rbac.py`:

```python
def normalize_tenant(tenant: str | None) -> str:
    """Single normalization point: empty/None becomes "default"."""
    return tenant or "default"
```

- [ ] **Step 4: Run tests**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py -v`
Expected: 3 PASS. Then full suite `.../python -m pytest -q` — Expected: all pass (no existing behavior touched).

- [ ] **Step 5: Commit**

```bash
git add libs/rag/src/rag/types.py libs/rag/src/rag/retrieval/rbac.py libs/rag/tests/test_tenant.py
git commit -m "feat(rag): portable AccessFilter with tenant + attributes"
```

---

### Task 2: Retrieval-side tenant enforcement

**Files:**
- Modify: `libs/rag/src/rag/retrieval/rbac.py:59-65` (`passes_access_filter` gains `tenant`)
- Modify: `libs/rag/src/rag/repo/qdrant_repo.py:120-131` (`_qdrant_filter` gains `tenant`), `:134-139` + `:173-175` (`semantic_search`, `scroll_corpus` gain `tenant: str | None = None`)
- Modify: `libs/rag/src/rag/retrieval/search.py:36-42` (thread `filt.tenant` through; no signature change)
- Test: extend `libs/rag/tests/test_tenant.py`; existing `test_rbac.py`, `test_qdrant_writes.py` must pass unmodified (backward compat proof)

**Interfaces:**
- Consumes: `normalize_tenant`, `AccessFilter.tenant` (Task 1).
- Produces: tenant-scoped `semantic_search`, `scroll_corpus`, `passes_access_filter`; `search_rag` honors `filt.tenant` with zero signature change.

- [ ] **Step 1: Write the failing tests** — append to `libs/rag/tests/test_tenant.py`:

```python
from rag.retrieval.rbac import passes_access_filter


def test_passes_access_filter_enforces_tenant():
    meta = {"department": "hr", "access_level": "internal", "tenant": "api"}
    assert passes_access_filter(meta, ["hr"], 3, tenant="api") is True
    assert passes_access_filter(meta, ["hr"], 3, tenant="other") is False
    # Legacy points without a tenant key read as "default"
    legacy = {"department": "hr", "access_level": "internal"}
    assert passes_access_filter(legacy, ["hr"], 3, tenant="default") is True
    assert passes_access_filter(legacy, ["hr"], 3, tenant="api") is False
    # No tenant in filter disables the check (legacy behavior)
    assert passes_access_filter(meta, ["hr"], 3) is True


def test_qdrant_filter_includes_tenant():
    from rag.repo import qdrant_repo

    f = qdrant_repo._qdrant_filter(["hr"], 1, tenant="api")
    keys = [c.key for c in f.must]
    assert "tenant" in keys
    tenant_cond = next(c for c in f.must if c.key == "tenant")
    assert tenant_cond.match.value == "api"


def test_qdrant_filter_without_tenant_unchanged():
    from rag.repo import qdrant_repo

    f = qdrant_repo._qdrant_filter(["hr"], 1)
    assert [c.key for c in f.must] == ["department", "access_level"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'tenant'` (proves absence before touching source).

- [ ] **Step 3: Implement** — `rbac.py`:

```python
def passes_access_filter(
    metadata: dict,
    departments: list[str],
    max_access_level: int,
    tenant: str | None = None,
) -> bool:
    chunk_dept = metadata.get("department", "general")
    chunk_level_str = metadata.get("access_level", "internal")
    chunk_level = ACCESS_LEVELS.get(chunk_level_str, 1)
    dept_ok = "all" in departments or chunk_dept in departments
    level_ok = chunk_level <= max_access_level
    if tenant is None:
        return dept_ok and level_ok
    return dept_ok and level_ok and metadata.get("tenant", "default") == tenant
```

`qdrant_repo.py` — `_qdrant_filter(departments, max_access_level, tenant=None)`, inserting after the department condition (order: department, tenant, access_level — the test above asserts the no-tenant key order stays `["department", "access_level"]`):

```python
def _qdrant_filter(
    departments: list[str], max_access_level: int, tenant: str | None = None
):
    from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue

    must = []
    if "all" not in departments:
        must.append(FieldCondition(key="department", match=MatchAny(any=list(departments))))
    if tenant is not None:
        must.append(FieldCondition(key="tenant", match=MatchValue(value=tenant)))
    must.append(
        FieldCondition(
            key="access_level", match=MatchAny(any=list(allowed_level_labels(max_access_level)))
        )
    )
    return Filter(must=must)
```

`semantic_search` and `scroll_corpus` gain trailing `tenant: str | None = None` and pass it to `_qdrant_filter` / `passes_access_filter` respectively. `search.py` lines 34-41 become:

```python
    semantic_future = pool.submit(
        qdrant_repo.semantic_search,
        query_vector,
        candidate_k,
        list(filt.departments),
        int(filt.max_access_level),
        filt.tenant,
    )
    corpus_docs = qdrant_repo.scroll_corpus(
        list(filt.departments), int(filt.max_access_level), tenant=filt.tenant
    )
```

(`scroll_corpus` keeps its `limit` keyword — pass tenant as keyword so `limit` stays positional-safe.)

- [ ] **Step 4: Run tests**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py tests/test_rbac.py tests/test_qdrant_writes.py -v`
Expected: all PASS, including the pre-existing `test_rbac.py` / `test_qdrant_writes.py` unmodified (backward-compat proof).

- [ ] **Step 5: Commit**

```bash
git add libs/rag/src/rag/retrieval/rbac.py libs/rag/src/rag/repo/qdrant_repo.py libs/rag/src/rag/retrieval/search.py libs/rag/tests/test_tenant.py
git commit -m "feat(rag): tenant-scoped retrieval enforcement"
```

---

### Task 3: Ingestion stamping + metadata-order fix

**Files:**
- Modify: `libs/rag/src/rag/ingestion/index.py:32-82`
- Modify: `libs/rag/src/rag/repo/qdrant_repo.py:28-30` (`_chunk_id` gains tenant), `:76-107` (`upsert_chunks` payload gains tenant from chunk metadata)
- Test: `libs/rag/tests/test_tenant.py`; existing `test_index.py` asserts updated only where payload shape is asserted

**Interfaces:**
- Consumes: `normalize_tenant` (Task 1).
- Produces: `index_document(..., tenant: str | None = None)`; payloads always carry a concrete `tenant`; `_chunk_id` is tenant-qualified (same source+text in two tenants = distinct points).

**Context (read before implementing):** `index_document` currently upserts chunks with loader-inferred dept/level, then applies explicit overrides only to the registry row — so the Qdrant payload disagrees with the registry whenever the caller passes explicit values. `chunk_documents` copies `{**document.metadata}` into every chunk (verified in `chunking.py:21-35`), so stamping the docs *before* chunking fixes both the tenant and the override ordering in one reorder.

- [ ] **Step 1: Write the failing tests** — append to `libs/rag/tests/test_tenant.py`:

```python
def test_index_document_stamps_tenant_and_explicit_metadata(monkeypatch):
    import rag.ingestion.index as idx

    captured = {}

    monkeypatch.setattr(idx, "load_bytes", lambda content, filename: [SimpleDocForTest()])
    monkeypatch.setattr(idx, "chunk_documents", lambda docs: docs)
    monkeypatch.setattr(idx, "embed_texts", lambda texts: [[0.0] * 4 for _ in texts])
    monkeypatch.setattr(idx, "ensure_collection", lambda: None)
    def fake_upsert(chunks, vectors):
        captured["payload"] = dict(chunks[0].metadata)
        return 1

    monkeypatch.setattr(idx, "upsert_chunks", fake_upsert)
    monkeypatch.setattr(idx, "get_conn", _FakeConnCtx())
    monkeypatch.setattr(idx, "ensure_tables", lambda conn: None)
    monkeypatch.setattr(idx, "get_document", lambda conn, source, tenant="default": None)
    monkeypatch.setattr(idx, "delete_chunks_by_source", lambda source, tenant="default": None)
    monkeypatch.setattr(idx, "flush_cache", lambda conn, tenant=None: 0)
    monkeypatch.setattr(idx, "upsert_document", lambda conn, **kw: captured.update(registry=kw))

    from rag.ingestion.index import index_document

    index_document(b"x", "hr_policy.pdf", source="s", department="hr", access_level="confidential", tenant="api")
    assert captured["payload"]["tenant"] == "api"
    assert captured["payload"]["department"] == "hr"
    assert captured["payload"]["access_level"] == "confidential"
    assert captured["registry"]["tenant"] == "api"
```

Helpers (define once at the top of `test_tenant.py` — real code, not sketches):

```python
from rag.repo.neon_repo import SimpleDoc as _SimpleDoc


def SimpleDocForTest(**kw):
    meta = {"source": "s", "department": "general", "access_level": "internal"}
    meta.update(kw.pop("metadata", {}))
    return _SimpleDoc(text=kw.pop("text", "hello"), metadata=meta)


class _FakeConnCtx:
    def __init__(self):
        self.conn = object()

    def __call__(self):
        return self

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False
```

Note: `get_document`/`delete_chunks_by_source` are monkeypatched here with the Task 4/5 signatures (`tenant` keyword) — if Tasks 4–5 are not done yet, these lambdas still work because the *test* defines the double, not the source. But `index.py` must call them with `tenant=` keywords for the doubles to accept — write the source that way in Step 3 and keep the doubles; the real Task 4/5 implementations then match automatically.

- [ ] **Step 2: Run to verify it fails**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py -k "stamps_tenant" -v`
Expected: FAIL — `TypeError: index_document() got an unexpected keyword argument 'tenant'`.

- [ ] **Step 3: Implement** — rewrite `index_document` head (lines 32–56) as:

```python
def index_document(
    content: bytes,
    filename: str,
    source: str,
    department: str | None = None,
    access_level: str | None = None,
    tenant: str | None = None,
) -> IngestionResult:
    """Load, chunk, embed, and upsert one document. Content-hash deduped.

    Tenant is stamped on every chunk payload and the registry row. Explicit
    department/access_level win over filename inference for BOTH payload and
    registry (previously the payload kept the inferred values — fixed here).
    """
    tn = normalize_tenant(tenant)
    docs = load_bytes(content, filename)
    if not docs:
        return IngestionResult(
            documents_loaded=0, chunks_created=0, chunks_indexed=0, sources=[source]
        )
    meta = infer_document_metadata(filename)
    if department:
        meta["department"] = department
    if access_level:
        meta["access_level"] = access_level
    for d in docs:
        d.metadata["source"] = source
        d.metadata["department"] = meta["department"]
        d.metadata["access_level"] = meta["access_level"]
        d.metadata["tenant"] = tn
    content_hash = hashlib.sha256("\n".join(d.text for d in docs).encode()).hexdigest()
    with get_conn() as conn:
        ensure_tables(conn)
        existing = get_document(conn, source, tenant=tn)
        if existing and existing["content_hash"] == content_hash:
            return IngestionResult(
                documents_loaded=0, chunks_created=0, chunks_indexed=0, sources=[source]
            )
        delete_chunks_by_source(source, tenant=tn)
        flush_cache(conn, tenant=tn)
    chunks = chunk_documents(docs)
    vectors: list[list[float]] = []
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        vectors.extend(embed_texts([c.text for c in chunks[i : i + EMBED_BATCH_SIZE]]))
    ensure_collection()
    indexed = upsert_chunks(chunks, vectors)
    with get_conn() as conn:
        upsert_document(
            conn,
            source=source,
            content_hash=content_hash,
            chunks_count=indexed,
            department=meta["department"],
            access_level=meta["access_level"],
            tenant=tn,
        )
    return IngestionResult(
        documents_loaded=len(docs),
        chunks_created=len(chunks),
        chunks_indexed=indexed,
        sources=[source],
    )
```

`qdrant_repo.py`: `_chunk_id(source, chunk_index, text, tenant="default")` hashing `f"{tenant}:{source}:{chunk_index}:{text}"`; in `upsert_chunks`, `tn = str(meta.get("tenant", "default"))`, pass `tenant=tn` to `_chunk_id`, add `"tenant": tn` to the payload dict.

`delete_indexed_source(source, tenant=None)`: normalize, pass `tenant=tn` to `delete_chunks_by_source` and `delete_document` (Tasks 4–5 signatures — implement the *call shape* now; the callees land in their tasks).

- [ ] **Step 4: Run tests**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py tests/test_index.py -v`
Expected: new tests PASS; `test_index.py` — update only assertions that pin the old payload shape or old call signatures (the task's explicit-metadata assertions now also pass *through the payload*, which is the bug fix — keep those updated assertions).

- [ ] **Step 5: Commit**

```bash
git add libs/rag/src/rag/ingestion/index.py libs/rag/src/rag/repo/qdrant_repo.py libs/rag/tests/test_tenant.py libs/rag/tests/test_index.py
git commit -m "feat(rag): tenant-stamped ingestion, fix payload metadata ordering"
```

---

### Task 4: Registry tenant column + composite uniqueness

**Files:**
- Modify: `libs/rag/src/rag/repo/neon_repo.py:60-154` (`ensure_tables`, `get_document`, `upsert_document`, `update_mtime`, `delete_document`)
- Test: `libs/rag/tests/test_tenant.py` (SQL-shape asserts in the existing `test_registry.py` mock style) + update `libs/rag/tests/test_registry.py` call sites

**Interfaces:**
- Consumes: `normalize_tenant` (Task 1).
- Produces: `get_document(conn, source, tenant=None)`, `upsert_document(conn, ..., tenant="default", ...)`, `update_mtime(conn, source, file_mtime, tenant=None)`, `delete_document(conn, source, tenant=None)`; `documents` rows keyed by `(tenant, source)`.

**Context:** `documents.source` is currently the sole PRIMARY KEY — two tenants indexing the same B2 key would collide. The DDL below is idempotent (`IF NOT EXISTS` + `DO ... EXCEPTION`) so fresh and legacy dev databases converge; legacy rows backfill to `"default"`. No production data exists (user-confirmed), so no backfill verification beyond the statements themselves.

- [ ] **Step 1: Write the failing tests** — append to `libs/rag/tests/test_tenant.py`, following the mock-connection pattern in `test_registry.py` (a `FakeConn` recording `execute(sql, params)` calls — copy that helper's exact shape from `test_registry.py` before writing):

```python
def test_ensure_tables_adds_tenant_column_and_composite_key():
    from rag.repo import neon_repo

    conn = FakeConn()
    neon_repo.ensure_tables(conn)
    stmts = [sql for sql, _ in conn.executed]
    assert any("ADD COLUMN IF NOT EXISTS tenant" in s for s in stmts)
    assert any("tenant" in s and "source" in s and "PRIMARY KEY" in s for s in stmts)


def test_upsert_document_scopes_conflict_to_tenant():
    from rag.repo import neon_repo

    conn = FakeConn()
    neon_repo.upsert_document(conn, source="s", content_hash="h", chunks_count=1, tenant="api")
    sql, params = conn.executed[-1]
    assert "ON CONFLICT (tenant, source)" in sql
    assert params[0] == "api"  # tenant is the FIRST bound param after the column reorder
    assert params[1] == "s"


def test_get_and_delete_document_filter_by_tenant():
    from rag.repo import neon_repo

    conn = FakeConn()
    neon_repo.get_document(conn, "s", tenant="api")
    assert "tenant = %s" in conn.executed[-1][0]
    assert conn.executed[-1][1] == ("api", "s")
    neon_repo.delete_document(conn, "s", tenant="api")
    assert "tenant = %s" in conn.executed[-1][0]
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py -k "tenant_column or conflict_to_tenant or filter_by_tenant" -v`
Expected: FAIL — `TypeError` on the new `tenant` keywords / assertion failures on SQL shape.

- [ ] **Step 3: Implement** — `ensure_tables`, after the `documents` CREATE TABLE block and before the `file_mtime` ALTER (exact statements):

```sql
ALTER TABLE documents ADD COLUMN IF NOT EXISTS tenant TEXT DEFAULT 'default';
UPDATE documents SET tenant = 'default' WHERE tenant IS NULL;
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_pkey;
DO $$ BEGIN
    ALTER TABLE documents ADD PRIMARY KEY (tenant, source);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
```

`get_document(connection, source, tenant=None)`:

```python
tn = normalize_tenant(tenant)
row = connection.execute(
    "SELECT source, content_hash, file_mtime, department, access_level, "
    "chunks_count, indexed_at, status FROM documents WHERE tenant = %s AND source = %s",
    (tn, source),
).fetchone()
```

`upsert_document(..., tenant: str = "default", ...)` — normalize the incoming value (`tn = normalize_tenant(tenant)`), column list becomes `(tenant, source, content_hash, ...)` with params `(tn, source, ...)`, conflict clause `ON CONFLICT (tenant, source) DO UPDATE SET ...` (same SET list as today). `update_mtime` and `delete_document` gain trailing `tenant=None`, normalized, `AND tenant = %s` appended.

- [ ] **Step 4: Run tests**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py tests/test_registry.py -v`
Expected: new tests PASS; `test_registry.py` — update its `upsert_document`/`get_document`/`delete_document` call sites and SQL assertions to the tenant-scoped shapes (mechanical, same-file edits only).

- [ ] **Step 5: Commit**

```bash
git add libs/rag/src/rag/repo/neon_repo.py libs/rag/tests/test_tenant.py libs/rag/tests/test_registry.py
git commit -m "feat(rag): tenant-scoped document registry"
```

---

### Task 5: Delete scoping (Qdrant + registry)

**Files:**
- Modify: `libs/rag/src/rag/repo/qdrant_repo.py:110-117` (`delete_chunks_by_source`)
- Covered: `libs/rag/src/rag/ingestion/index.py:85-91` (`delete_indexed_source` — call shape written in Task 3, verify here)
- Test: `libs/rag/tests/test_tenant.py`; existing `test_qdrant_writes.py` call sites updated

**Interfaces:**
- Consumes: `normalize_tenant`, tenant-scoped `delete_document` (Task 4).
- Produces: `delete_chunks_by_source(source, tenant=None)` — tenant-scoped filter when set, legacy source-only match when `None` (fail-closed direction: a scoped delete never touches another tenant's points).

- [ ] **Step 1: Write the failing test** — append to `libs/rag/tests/test_tenant.py`:

```python
def test_delete_chunks_by_source_scopes_to_tenant(monkeypatch):
    from rag.repo import qdrant_repo

    seen = {}

    class FakeClient:
        def delete(self, collection_name, points_selector):
            seen["filter"] = points_selector

    monkeypatch.setattr(qdrant_repo, "_cached_client", lambda: FakeClient())
    qdrant_repo.delete_chunks_by_source("s", tenant="api")
    keys = [c.key for c in seen["filter"].must]
    assert keys == ["source", "tenant"]

    qdrant_repo.delete_chunks_by_source("s")
    assert [c.key for c in seen["filter"].must] == ["source"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py -k "scopes_to_tenant" -v`
Expected: FAIL — `TypeError` on `tenant` keyword.

- [ ] **Step 3: Implement**:

```python
def delete_chunks_by_source(source: str, tenant: str | None = None) -> None:
    """Delete points for a source; tenant-scoped when given (never cross-tenant)."""
    from qdrant_client.http.models import FieldCondition, Filter, MatchValue

    must = [FieldCondition(key="source", match=MatchValue(value=source))]
    if tenant is not None:
        must.append(FieldCondition(key="tenant", match=MatchValue(value=normalize_tenant(tenant))))
    _cached_client().delete(
        collection_name=get_rag_settings().qdrant_collection,
        points_selector=Filter(must=must),
    )
```

Import `normalize_tenant` at the top of `qdrant_repo.py` (`from rag.retrieval.rbac import allowed_level_labels, normalize_tenant`) — check for import cycles first: `rbac.py` imports nothing from `rag` (verified — stdlib only), so this is safe. Verify `delete_indexed_source` in `index.py` already passes `tenant=tn` through (written in Task 3); if not, fix it here.

- [ ] **Step 4: Run tests**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py tests/test_qdrant_writes.py tests/test_index.py -q`
Expected: all PASS (`test_qdrant_writes.py` call sites updated to the new signature where they pin it).

- [ ] **Step 5: Commit**

```bash
git add libs/rag/src/rag/repo/qdrant_repo.py libs/rag/src/rag/ingestion/index.py libs/rag/tests/test_tenant.py libs/rag/tests/test_qdrant_writes.py
git commit -m "feat(rag): tenant-scoped deletes"
```

---

### Task 6: Cache scoping (key + table + flush)

**Files:**
- Modify: `libs/rag/src/rag/retrieval/query_cache.py` (`make_cache_key`, `ensure_cache_table`, `get_cached_answer`, `store_cached_answer`, `flush_cache`)
- Modify: `libs/rag/src/rag/retrieval/search.py` (`_cache_get`/`_cache_put` thread tenant from the filter)
- Test: `libs/rag/tests/test_tenant.py`; existing `libs/rag/tests/test_cache_key.py` must pass unmodified unless it pins key preimages

**Interfaces:**
- Consumes: `normalize_tenant` (Task 1).
- Produces: `make_cache_key(question, ctx_hash, tenant=None)`; `get_cached_answer(conn, question, embedding, ctx_hash, tenant=None)`; `store_cached_answer(conn, ..., ctx_hash, tenant=None, ttl_hours=24)`; `flush_cache(conn, expired_only=False, tenant=None)`; `query_cache.tenant` column with `'default'` backfill.

- [ ] **Step 1: Write the failing tests** — append to `libs/rag/tests/test_tenant.py`:

```python
def test_cache_key_is_tenant_scoped():
    from rag.retrieval.query_cache import make_cache_key

    assert make_cache_key("hi", "ctx") == make_cache_key("hi", "ctx")
    assert make_cache_key("hi", "ctx", tenant="api") != make_cache_key("hi", "ctx")
    assert make_cache_key("hi", "ctx", tenant="api") == make_cache_key("hi", "ctx", tenant="api")
    assert make_cache_key("hi", "ctx", tenant=None) == make_cache_key("hi", "ctx")


def test_semantic_lookup_filters_by_tenant():
    from rag.retrieval import query_cache

    conn = FakeConn()
    query_cache.get_cached_answer(conn, "hi", [0.0] * 4, "ctx", tenant="api")
    tier2_sql = conn.executed[-1][0]
    assert "tenant = %s" in tier2_sql
    assert "api" in conn.executed[-1][1]


def test_flush_cache_scopes_to_tenant():
    from rag.retrieval import query_cache

    conn = FakeConn()
    query_cache.flush_cache(conn, tenant="api")
    assert "tenant = %s" in conn.executed[-1][0]
    query_cache.flush_cache(conn)
    assert conn.executed[-1][0] == "DELETE FROM query_cache"
```

(`FakeConn` is the shared helper from Task 3 Step 1 — `executed` list of `(sql, params)`; `get_cached_answer` runs two statements (Tier-1 SELECT then Tier-2 SELECT), so `executed[-1]` is the Tier-2 query. If your `FakeConn.fetchone` returns `None`, Tier-1 falls through to Tier-2 as required. Ensure the helper's `execute` returns an object with `fetchone() -> None`.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py -k "tenant_scoped or filters_by_tenant or scopes_to_tenant and cache or flush" -v`
Expected: FAIL — `TypeError` on the new `tenant` keywords. (If `-k` selects nothing, run the three test IDs explicitly.)

- [ ] **Step 3: Implement** — `query_cache.py`:

```python
def make_cache_key(question: str, ctx_hash: str, tenant: str | None = None) -> str:
    scope = normalize_tenant(tenant) if tenant is not None else None
    preimage = f"{question.strip()}|CTX:{ctx_hash}" if scope is None else f"{scope}|{question.strip()}|CTX:{ctx_hash}"
    return _hash(preimage)
```

Requires `from rag.retrieval.rbac import normalize_tenant` — cycle check: `rbac.py` imports stdlib only (verified Task 5 pattern); `neon_repo.py` already imports `ensure_cache_table` from `query_cache`, and `query_cache` importing `rbac` adds no cycle (rbac imports nothing from rag). Safe.

`ensure_cache_table`: fresh CREATE gains `tenant TEXT DEFAULT 'default'`; append `ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS tenant TEXT DEFAULT 'default'` plus `UPDATE query_cache SET tenant = 'default' WHERE tenant IS NULL`.

`get_cached_answer(..., tenant=None)`: Tier-1 unchanged (key already scoped); Tier-2 `WHERE` gains `AND tenant = %s` with normalized value appended to params. `store_cached_answer(..., tenant=None, ...)`: column list + values gain `tenant`, normalized. `flush_cache(connection, expired_only=False, tenant=None)`: `tenant is None` → today's statements verbatim; else `DELETE FROM query_cache WHERE tenant = %s` (and `AND expires_at ...` when `expired_only`).

`search.py`: `_cache_get(question, query_vector, ctx_hash, resolved_mode)` needs the tenant — change both helpers to accept `tenant` and pass `filt.tenant` at the two call sites (lines 64, 73). Exact edits:

```python
cached_response = _cache_get(question, query_vector, ctx_hash, resolved_mode, filt.tenant)
...
_cache_put(question, query_vector, response, resolved_mode, ctx_hash, filt.tenant)
```

with `def _cache_get(question, embedding, ctx_hash, resolved_mode, tenant=None)` forwarding to `query_cache.get_cached_answer(conn, question, embedding, ctx_hash, tenant=tenant)`, and likewise `_cache_put`.

- [ ] **Step 4: Run tests**

Run: `cd libs/rag && ../../services/api/.venv/bin/python -m pytest tests/test_tenant.py tests/test_cache_key.py -v`
Expected: all PASS. If `test_cache_key.py` pins exact key preimages, it still passes (two-arg calls hash the identical preimage as today — assert this before touching that file; only update it if the no-tenant preimage changed, which it must not).

- [ ] **Step 5: Commit**

```bash
git add libs/rag/src/rag/retrieval/query_cache.py libs/rag/src/rag/retrieval/search.py libs/rag/tests/test_tenant.py
git commit -m "feat(rag): tenant-scoped answer cache"
```

---

### Task 7: API adopts tenant (first host)

**Files:**
- Modify: `services/api/app/config/settings.py` (add `rag_tenant: str = "api"`)
- Modify: `services/api/app/repo/rag_auth.py` (`claims_to_access_filter` stamps `tenant=settings.rag_tenant`)
- Modify: `services/api/app/service/retrieval.py` (no change expected — filter already flows through; verify and note)
- Modify: `services/api/app/service/upload.py` (`_maybe_index_in_rag` passes `tenant=settings.rag_tenant`)
- Modify: `services/api/app/service/files.py` (`remove_file` purge passes `tenant=settings.rag_tenant`)
- Test: `services/api/tests/test_retrieval.py`, `services/api/tests/test_rag_ingestion.py` (assert passthrough)

**Interfaces:**
- Consumes: `AccessFilter.tenant`, `index_document(..., tenant=)`, `delete_indexed_source(..., tenant=)` (Tasks 1, 3, 5).
- Produces: API corpus isolated under tenant `"api"`; the reference host-mapping every future service copies.

- [ ] **Step 1: Write the failing assertions** — in `test_retrieval.py`, after the existing `seen["filter"].departments` / `max_access_level` assertions, add exactly: `assert seen["filter"].tenant == "api"`. In `test_rag_ingestion.py`, wherever `seen["department"]` is asserted, add exactly: `assert seen["tenant"] == "api"`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd services/api && .venv/bin/python -m pytest tests/test_retrieval.py tests/test_rag_ingestion.py -q`
Expected: FAIL — `AssertionError` / `KeyError` on `tenant` (the lib accepts it, the api just never sends it).

- [ ] **Step 3: Implement** — settings block (next to the other `rag_*` fields):

```python
rag_tenant: str = "api"
```

`rag_auth.py`:

```python
from rag.types import AccessFilter  # existing import

def claims_to_access_filter(claims: RagTokenClaims) -> AccessFilter:
    ...
    return AccessFilter(
        departments=departments,
        max_access_level=claims.max_access_level,
        tenant=settings.rag_tenant,
    )
```

(Keep the existing department-mapping body verbatim; only the constructor call gains `tenant=settings.rag_tenant`. `settings` is already imported in that module.)

`upload.py` `_maybe_index_in_rag`: add `tenant=settings.rag_tenant` to the `index_document(...)` call. `files.py` `remove_file`: `delete_indexed_source(key, tenant=settings.rag_tenant)`. `service/retrieval.py`: verify no edit needed (it forwards the filter object untouched) — if it reconstructs `AccessFilter` anywhere, thread tenant there too.

- [ ] **Step 4: Run tests**

Run: `cd services/api && .venv/bin/python -m pytest -q`
Expected: full api suite (256 + any new) PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/config/settings.py services/api/app/repo/rag_auth.py services/api/app/service/upload.py services/api/app/service/files.py services/api/tests/test_retrieval.py services/api/tests/test_rag_ingestion.py
git commit -m "feat(api): stamp rag tenant on search, index, and purge"
```

---

### Task 8: Docs, debt, gates, commit

**Files:**
- Modify: `docs/features/retrieval.md` (multi-service contract section)
- Modify: `docs/exec-plans/tech-debt-tracker.md` (append Open row)
- Modify: `.env.example` (document `RAG_TENANT`)
- Test: full gates (no new test files)

**Interfaces:**
- Consumes: Tasks 1–7 behavior.
- Produces: documented host-mapping recipe; recorded follow-ups.

- [ ] **Step 1: `retrieval.md`** — append a `## Multi-service use (tenant + portable filter)` section with exactly: (a) tenant semantics (`None` → `"default"`, stamped on payload/registry/cache, deletes scoped, point IDs qualified); (b) the host recipe — hosts resolve identity to `AccessFilter` themselves (link `services/api/app/repo/rag_auth.py::claims_to_access_filter` as the reference implementation) and pass `tenant` on index/delete; (c) explicit non-goals: no required filter yet, no per-call collection override, no external policy engine. Update the Tests line to add `libs/rag/tests/test_tenant.py`.

- [ ] **Step 2: Debt tracker** — append one Open row:

| Isolate failure further: `search_rag` permissive default filter + global cache flush | A no-filter call searches `departments=["all"]` @ level 0; any ingest flushes every tenant's cache rows | Make `access_filter` required (breaking: update all hosts) and default `flush_cache` to the calling tenant | Low |

- [ ] **Step 3: `.env.example`** — under the RAG block, add `# RAG_TENANT=api` with one line: project identity stamped on this host's indexed/searchable corpus; distinct per independent project sharing one backend.

- [ ] **Step 4: Run the gates**

Run: `pnpm lint:rag && pnpm test:rag && pnpm lint:api && pnpm test:api && pnpm check:structure`
Expected: all green (rag suite now includes `test_tenant.py`).

- [ ] **Step 5: Commit**

```bash
git add docs/features/retrieval.md docs/exec-plans/tech-debt-tracker.md .env.example
git commit -m "docs(rag): multi-service tenant contract and follow-ups"
```

---

## Out of scope (explicitly not this plan)

- Thin browser HTTP host (`services/rag-host` vs api-kept route) — still an open product decision; this plan changes no HTTP surface.
- Required `access_filter` (fail-closed default) — debt row in Task 8.
- Per-call collection override / multi-collection routing.
- External policy engines (Cedar/OPA) — the `attributes` field + host-side mapping are the seam; no engine is wired.
- `Source` result enrichment with tenant — add only when a consumer needs it.