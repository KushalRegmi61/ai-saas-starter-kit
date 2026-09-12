# RAG Phase 2 (Direct Ingestion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-index RAG-readable uploads (pdf/txt/md) into Qdrant + Neon at `/upload/complete` time, and purge their chunks on file delete — no S3, no Lambda, no async jobs.

**Architecture:** `rag/ingestion/` gains the single tool `index_document(content: bytes, filename, source, department?, access_level?) -> IngestionResult` (load → hash-dedup → chunk → embed → upsert → registry → cache-flush), mirroring `search_rag()` as the only other cross-package entrypoint. API calls it from `finalize_upload` (failure-safe: upload never fails because indexing failed) and purges from `remove_file`.

**Tech Stack:** pdfplumber, langchain-text-splitters (new rag deps); Qdrant upsert/delete-by-filter (qdrant-client 1.19); Neon `documents` registry; OpenAI embeddings via existing `embed_texts`.

**Spec:** Port sources are `../enterprise-rag-assistant/app/ingestion/{pipeline,loaders,chunking,document_store}.py`, `app/access/rbac.py` (filename maps + `infer_document_metadata` only), `app/retrieval/vector_store.py` (`_index_chunks_pgvector` pattern + `_chunk_id` verbatim), `app/cache/query_cache.py` (`flush_cache` signature), `app/config.py` (chunk 900/150, retry 3/1.0/10.0). Explicitly excluded: `ingest_from_s3`, `_download_from_s3`, `ingest_jobs` + `run_ingest_job` + status polling, docx support, `/documents/*` endpoints, `load_directory`/`ingest_directory`/`sync_directory`, `list_documents`, `bump_corpus_version` (no in-memory BM25 cache in Phase 1 — N/A), `trace_span` (no tracing infra), `ROLE_POLICIES`.

## Global Constraints

- Backend layering `types -> config -> repo -> retrieval|ingestion`: no backward imports, no `boto3` outside `repo/` (no boto3 at all here), no business logic in `runtime/`, Pydantic at boundaries.
- Files stay under 300 lines; structured logging only (`logging`, no `print`); `ruff check` + `ruff format` clean in both packages (isort: `rag` is first-party in services/rag, `app` is first-party in services/api — rag imports sort as third-party in api).
- `B904`: `raise ... from None` inside `except` clauses. `B905`: `zip(..., strict=...)`.
- Verbatim-port rule: chunking table rule, `IngestionResult` shape (`documents_loaded, chunks_created, chunks_indexed, sources`), `_chunk_id`, filename inference maps, `flush_cache(conn, expired_only=False)` signature.
- Qdrant payload schema MUST stay `{text, source, page, chunk_index, department, access_level}` — Phase 1 `semantic_search`/`scroll_corpus` read exactly these keys.
- Test runner: rag tests via `/home/pursottam/mine/projects/ai-saas-starter-kit/services/api/.venv/bin/python -m pytest tests/ -q` from `services/rag`; api tests via `.venv/bin/python -m pytest tests/ -q` from `services/api`. Lint: `.venv/bin/ruff check .` + `.venv/bin/ruff format --check .` in each package dir (use the api venv binary for both).
- Frontend: if `FileUploadResponse` is mirrored in `apps/web`, extend the TS type too.

## Decisions (user-approved)

1. Trigger = auto-index in `finalize_upload`. No new endpoint. Only `application/pdf` + `text/plain` indexed; everything else skips silently with `rag_indexed=false`.
2. RBAC = uploader declares via `CompleteUploadRequest.department/access_level`, filename inference falls back, default `general`/`internal`. Unknown declared values → 400.
3. Sync only — jobs deferred. `finalize_upload` runs in `run_in_threadpool`, so inline embedding doesn't block the event loop.
4. Source identity = B2 key (`uploads/{user_id}/{name}`), NOT bare filename (cross-user collisions). Inference runs on the basename.
5. Index failure never fails the upload. Catch-all in service, `logger.exception`, response carries `rag_indexed: bool = False`.
6. Dimension guard + retry parity included (see Tasks 1, 5).

---

### Task 1: rag deps + chunk/retry settings

**Files:**
- Modify: `services/rag/pyproject.toml` (dependencies list)
- Modify: `services/rag/src/rag/config.py` (+5 fields)
- Modify: `services/rag/src/rag/repo/embeddings.py` (`_retry` reads settings)

**Interfaces:**
- Consumes: nothing. Produces: `RagSettings.chunk_size = 900`, `chunk_overlap = 150` (enterprise `app/config.py:20-21`); `openai_retry_attempts = 3`, `openai_retry_min_wait = 1.0`, `openai_retry_max_wait = 10.0` (enterprise `app/config.py:40-42`).

- [ ] **Step 1: Add dependencies** (`pdfplumber>=0.11`, `langchain-text-splitters>=0.3`) and the 5 settings fields.
- [ ] **Step 2: Wire `_retry()` to settings:**

```python
def _retry():
    s = get_rag_settings()
    return retry(
        retry=retry_if_exception_type((Exception,)),
        stop=stop_after_attempt(s.openai_retry_attempts),
        wait=wait_exponential(multiplier=1, min=s.openai_retry_min_wait, max=s.openai_retry_max_wait),
        reraise=True,
    )
```

- [ ] **Step 3: Install + verify:** `services/api/.venv/bin/pip install -e ../rag` from `services/rag` (or `pip install pdfplumber langchain-text-splitters` into the api venv), then `python -c "import pdfplumber, langchain_text_splitters; print('ok')"`. Expected: `ok`.
- [ ] **Step 4: Run rag suite.** Expected: all pass (baseline 11 passed).
- [ ] **Step 5: Commit** — `git add services/rag/pyproject.toml services/rag/src/rag/config.py services/rag/src/rag/repo/embeddings.py && git commit -m "feat(rag): ingestion deps + chunk/retry settings"`

---

### Task 2: Port document loaders (txt/md/pdf only)

**Files:**
- Create: `services/rag/src/rag/ingestion/loaders.py`
- Test: `services/rag/tests/test_loaders.py`

**Interfaces:**
- Consumes: `rag.retrieval.rbac.infer_document_metadata` (Task 3 — implement Task 3 first if running out of order, or run Tasks 2+3 as one batch).
- Produces: `load_bytes(content: bytes, filename: str) -> list[SimpleDoc]`; `SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf"}`. Reuse existing `rag.repo.neon_repo.SimpleDoc` (text/metadata) — do not redefine.

Port notes (enterprise `loaders.py:29-126,231-272`): keep `_load_text`, `_load_pdf` (two-pass tables-blanked text + per-table markdown docs with `content_type`/`table_index`/`page` metadata), `_table_to_markdown`, `_inside_any_table` verbatim. Drop `load_directory`, `_load_docx`, `_dedup_merged_cells`, `.docx`. New entrypoint works in-memory (`pdfplumber.open(io.BytesIO(content))`) — no tempfile:

```python
def load_bytes(content: bytes, filename: str) -> list[SimpleDoc]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        text = content.decode("utf-8")
        return [SimpleDoc(text=text, metadata={"source": Path(filename).name, "file_type": suffix.lstrip("."), **infer_document_metadata(filename)})]
    if suffix == ".pdf":
        return _load_pdf_bytes(content, filename)
    raise ValueError(f"Unsupported document type: {suffix}")
```

- [ ] **Step 1: Write the failing test:**

```python
def test_load_txt_and_md():
    docs = load_bytes(b"# hello\n\nworld", "notes.md")
    assert len(docs) == 1 and docs[0].text.startswith("# hello")
    assert docs[0].metadata["source"] == "notes.md"

def test_unsupported_suffix_raises():
    with pytest.raises(ValueError):
        load_bytes(b"GIF89a...", "cat.gif")
```

- [ ] **Step 2: Run test to verify it fails** — `python -m pytest tests/test_loaders.py -q` from `services/rag`. Expected: FAIL.
- [ ] **Step 3: Write `loaders.py` per port notes.**
- [ ] **Step 4: Run tests.** Expected: PASS + full suite green.
- [ ] **Step 5: Commit** — `git commit -m "feat(rag): port byte-oriented document loaders (txt/md/pdf)"`

---

### Task 3: Port filename RBAC inference + chunker

**Files:**
- Modify: `services/rag/src/rag/retrieval/rbac.py` (+ maps + `infer_document_metadata`)
- Create: `services/rag/src/rag/ingestion/chunking.py`
- Test: `services/rag/tests/test_ingestion_rbac.py`, `services/rag/tests/test_chunking.py`

**Interfaces:**
- Consumes: `RagSettings.chunk_size/chunk_overlap` (Task 1). Produces: `infer_document_metadata(filename) -> {"department","access_level"}`; `chunk_documents(documents: list[SimpleDoc]) -> list[SimpleDoc]` (`chunk_index` in metadata).

Port notes: maps + function verbatim from enterprise `rbac.py:77-120` (no `ROLE_POLICIES`). Chunker verbatim from enterprise `chunking.py:7-37` with `get_rag_settings()`; tables kept whole (`chunk_index: 0`).

- [ ] **Step 1: Write failing tests:**

```python
def test_infer_prefix_and_fallback():
    assert infer_document_metadata("hr_policy.pdf") == {"department": "hr", "access_level": "confidential"}
    assert infer_document_metadata("random.txt") == {"department": "general", "access_level": "internal"}

def test_tables_never_split():
    big_table = "| a |\n| --- |\n" + "| row |\n" * 500
    out = chunk_documents([SimpleDoc(text=big_table, metadata={"content_type": "table"})])
    assert len(out) == 1 and out[0].metadata["chunk_index"] == 0

def test_text_splits_with_overlap():
    out = chunk_documents([SimpleDoc(text="word " * 500, metadata={})])
    assert len(out) > 1 and all("chunk_index" in d.metadata for d in out)
```

- [ ] **Step 2: Run to verify FAIL → Step 3: Implement → Step 4: PASS, suite green → Step 5: Commit** `feat(rag): port RBAC filename inference + chunker`.

---

### Task 4: Neon document registry + cache flush

**Files:**
- Modify: `services/rag/src/rag/repo/neon_repo.py` (`ensure_tables` + 4 functions)
- Modify: `services/rag/src/rag/retrieval/query_cache.py` (+ `flush_cache`)
- Test: `services/rag/tests/test_registry.py` (mock-connection SQL assertions)

**Interfaces:**
- Consumes: nothing new. Produces: `get_document(conn, source) -> dict | None`; `upsert_document(conn, source, content_hash, chunks_count, department="general", access_level="internal", file_mtime=None)`; `update_mtime(conn, source, file_mtime)`; `delete_document(conn, source)`; `flush_cache(conn, expired_only=False)`.

Port notes (enterprise `document_store.py:26-139`, `cache/query_cache.py:173`): `ensure_tables` gains the full `documents` DDL **including `file_mtime DOUBLE PRECISION`** plus the `ALTER TABLE ... ADD COLUMN IF NOT EXISTS file_mtime` migration (Phase 1 table lacks the column). Skip `list_documents`, all job functions. `flush_cache` deletes from whatever table `ensure_cache_table` creates — read that function first and match the name.

- [ ] **Step 1: Write failing tests** (MagicMock connection: `upsert_document` executes SQL containing `ON CONFLICT (source)`; `flush_cache` executes a DELETE against the cache table).
- [ ] **Step 2: FAIL → Step 3: Implement → Step 4: PASS → Step 5: Commit** `feat(rag): document registry + cache flush in neon repo`.

---

### Task 5: Qdrant write path + dimension guard (new code, ported pattern)

**Files:**
- Modify: `services/rag/src/rag/repo/qdrant_repo.py` (+4 functions)
- Test: `services/rag/tests/test_qdrant_writes.py` (mock `QdrantClient`)

**Interfaces:**
- Consumes: `RagSettings.qdrant_collection/embedding_dimensions`. Produces: `ensure_collection()`; `assert_collection_dimensions()`; `upsert_chunks(chunks, vectors) -> int`; `delete_chunks_by_source(source) -> None`.

Write path spec (payload keys MUST equal Phase 1 read keys):

```python
def _chunk_id(source: str, chunk_index: int, text: str) -> str:  # verbatim enterprise vector_store.py:447-451
    raw = f"{source}:{chunk_index}:{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def ensure_collection() -> None:
    assert_collection_dimensions()  # no-op when missing/empty
    ...create with VectorParams(size=embedding_dimensions, distance=COSINE) if missing...

def upsert_chunks(chunks: list[SimpleDoc], vectors: list[list[float]]) -> int:
    ...PointStruct(id=_chunk_id(...), vector=v, payload={"text","source","page","chunk_index","department","access_level"})...
    return len(points)

def delete_chunks_by_source(source: str) -> None:
    ...client.delete(collection, points_selector=Filter(must=[FieldCondition(key="source", match=MatchValue(value=source))]))...

def assert_collection_dimensions() -> None:
    ...scroll limit=1 with_vectors=True; skip when missing/empty; ValueError on mismatch...
```

Verify `collection_exists`/`delete`/`scroll(with_vectors=True)` signatures against installed `qdrant-client==1.19.0` before finalizing; adjust to actual SDK.

- [ ] **Step 1: Write failing tests** (mock client: payload keys exactly `{text, source, page, chunk_index, department, access_level}`; same input → same ids; delete builds a `source ==` filter; dim guard raises on mismatch, no-ops on empty).
- [ ] **Step 2: FAIL → Step 3: Implement → Step 4: PASS → Step 5: Commit** `feat(rag): qdrant write path + dimension guard`.

---

### Task 6: `index_document()` + `delete_indexed_source()` single tools

**Files:**
- Create: `services/rag/src/rag/ingestion/index.py`
- Modify: `services/rag/src/rag/ingestion/__init__.py`, `services/rag/src/rag/__init__.py` (export both)
- Test: `services/rag/tests/test_index.py` (monkeypatch `embed_texts`, `upsert_chunks`, registry fns; real loaders/chunker/inference)

**Interfaces:**
- Consumes: Tasks 2–5. Produces: `index_document(content: bytes, filename: str, source: str, department: str | None = None, access_level: str | None = None) -> IngestionResult`; `delete_indexed_source(source: str) -> None`.

Core logic (adapted from enterprise `pipeline._ingest_file:283-365`; mtime tier dropped; embeddings batched at 64):

```python
EMBED_BATCH_SIZE = 64

def index_document(content, filename, source, department=None, access_level=None) -> IngestionResult:
    docs = load_bytes(content, filename)  # ValueError/UnicodeDecodeError propagate -> API maps to skip
    if not docs:
        return IngestionResult(documents_loaded=0, chunks_created=0, chunks_indexed=0, sources=[source])
    for d in docs:
        d.metadata["source"] = source
    content_hash = hashlib.sha256("\n".join(d.text for d in docs).encode()).hexdigest()
    with get_conn() as conn:
        ensure_tables(conn)
        existing = get_document(conn, source)
        if existing and existing["content_hash"] == content_hash:
            return IngestionResult(documents_loaded=0, chunks_created=0, chunks_indexed=0, sources=[source])
        delete_chunks_by_source(source)
        flush_cache(conn)
    chunks = chunk_documents(docs)
    vectors: list[list[float]] = []
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        vectors.extend(embed_texts([c.text for c in chunks[i : i + EMBED_BATCH_SIZE]]))
    ensure_collection()
    indexed = upsert_chunks(chunks, vectors)
    meta = infer_document_metadata(filename)
    if department:
        meta["department"] = department
    if access_level:
        meta["access_level"] = access_level
    with get_conn() as conn:
        upsert_document(conn, source=source, content_hash=content_hash, chunks_count=indexed,
                        department=meta["department"], access_level=meta["access_level"])
    return IngestionResult(documents_loaded=len(docs), chunks_created=len(chunks), chunks_indexed=indexed, sources=[source])

def delete_indexed_source(source: str) -> None:
    delete_chunks_by_source(source)
    with get_conn() as conn:
        ensure_tables(conn)
        delete_document(conn, source)
        flush_cache(conn)
```

- [ ] **Step 1: Write failing tests** — unchanged bytes → all-zero, no upsert call; changed bytes → delete-before-upsert ordering (mock call order); explicit metadata beats inference; `delete_indexed_source` calls all three purges.
- [ ] **Step 2: FAIL → Step 3: Implement → Step 4: PASS → Step 5: Commit** `feat(rag): index_document + delete_indexed_source single tools`.

---

### Task 7: API wiring — auto-index on complete, purge on delete

**Files:**
- Modify: `services/api/app/repo/b2_client.py` (+ `get_object_bytes` — read existing client style first; sibling of `get_object_head_bytes`)
- Modify: `services/api/app/types/upload.py` (`CompleteUploadRequest` + `FileUploadResponse.rag_indexed: bool = False`)
- Modify: `services/api/app/service/upload.py` (`finalize_upload(..., department=None, access_level=None)` + `_maybe_index_in_rag`), `services/api/app/service/files.py` (`remove_file` purge), `services/api/app/runtime/upload.py` (pass-through)
- Test: `services/api/tests/test_rag_ingestion.py`

**Interfaces:**
- Consumes: `rag.index_document`, `rag.delete_indexed_source`. Local allow-lists: `VALID_DEPARTMENTS = {"hr","security","product","finance","general"}`, `VALID_ACCESS_LEVELS = {"public","internal","confidential","restricted"}`.

```python
RAG_INDEXABLE_TYPES = {"application/pdf": {".pdf"}, "text/plain": {".txt", ".md", ".log", ".text"}}

def _maybe_index_in_rag(key, filename, content_type, department, access_level) -> bool:
    if content_type not in RAG_INDEXABLE_TYPES:
        return False
    if not (settings.qdrant_url and settings.rag_database_url and settings.openai_api_key):
        return False
    try:
        content = get_object_bytes(key)
        index_document(content, filename, source=key, department=department, access_level=access_level)
        return True
    except ValueError:
        return False
    except Exception:
        logger.exception("RAG auto-index failed: key=%s", key)
        return False
```

`finalize_upload`: validate declared values (unknown → `UploadError` 400); after `invalidate_list_cache()`, `rag_indexed = _maybe_index_in_rag(...)`. `remove_file`: after `delete_file(key)`, best-effort `delete_indexed_source(key)` gated on rag config, try/except + log. Frontend check: grep `apps/web` for the mirrored response type; extend with `rag_indexed: boolean` if present.

- [ ] **Step 1: Write failing API tests** — pdf complete (mocked B2 bytes + `index_document`) → `rag_indexed true`, source==key, declared metadata passed; png → false, not called; `index_document` raising → still 200 + false; `department=foo` → 400; `remove_file` → purge called, purge raising → delete still succeeds.
- [ ] **Step 2: FAIL → Step 3: Implement → Step 4: PASS + full api suite → Step 5: Commit** `feat(api): auto-index uploads to RAG, purge on delete`.

---

### Task 8: Docs + full verification

**Files:**
- Modify: `docs/features/retrieval.md` (+ Phase 2 section), `ARCHITECTURE.md` (+ ingestion flow line).

- [ ] **Step 1: Update both docs.**
- [ ] **Step 2: Run gates** — `pnpm lint:api && pnpm test:api && pnpm check:structure` (repo root) + rag suite. Baselines: api 243 passed, structure 6 passed, rag 11 passed (all grow with new tests).
- [ ] **Step 3: Commit** — `git commit -m "docs: phase 2 ingestion (retrieval feature + architecture)"`.
