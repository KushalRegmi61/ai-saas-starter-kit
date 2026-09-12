# RAG Service Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract RAG out of the API process into a standalone `rag-service` (own FastAPI app, own deployable, own frontend assistant surface) so `services/api` no longer imports `rag.*`.

**Architecture:** `services/rag` gains a runnable HTTP shell (`main.py` + `runtime/` handlers, mirroring the api's `runtime/` layering) serving search + ingestion endpoints. The API keeps its behavior through a thin `repo/rag_client.py` httpx adapter (external APIs wrapped in `repo/` per AGENTS.md §3) for the two fire-and-forget triggers (index-on-finalize, purge-on-delete). The browser talks to the rag-service directly for search via a new `/assistant` page. Auth splits: enterprise JWT stays on rag-service for machine callers; browser search uses Supabase bearer (verified with the already-declared `python-jose` dep); api→rag triggers use a shared `RAG_SERVICE_TOKEN`.

**Tech Stack:** FastAPI + uvicorn (same as api), httpx (already an api dep, `httpx==0.28.1`), python-jose (already a rag dep), TanStack Query + `api-client.ts` pattern for the frontend, Railway Nixpacks (copy of `services/api/railway.json` pattern).

**Spec:** This plan IS the spec — it argues from the coupling inventory below. Executor reads this file plus the cited source files; no separate design doc.

## Global Constraints

- Backend layering `types -> config -> repo -> service -> runtime`, no backward imports (`services/api/tests/test_structure.py::test_no_backward_imports` pattern applies to the new service too).
- No `boto3` outside `repo/`; no business logic in route handlers; all request/response data validated by Pydantic models at the boundary.
- No `print()` (ruff `T20`); structured JSON logging only.
- Files stay under 300 lines (each new file below is sized accordingly).
- Every behavior change ships tests + docs in the same PR (see Task 6 mapping table).
- Lint clean before merge: `pnpm lint:api`-equivalent for the new service, `pnpm lint` for web.
- Frontend: all API calls through TanStack Query hooks in `apps/web/src/lib/queries.ts`; no bare `useEffect + fetch`. New endpoints touch three files: service `runtime/`, `lib/api-client.ts`, `lib/queries.ts`.
- Starter contract (AGENTS.md §2): `components/ui/`, `/files`, `/upload`, and the sidebar entries stay. The new `/assistant` page is ADDED (new sidebar item under Product), nothing existing is removed or renamed.
- shadcn/ui components are generated — never modify `src/components/ui/`.

---

## Coupling inventory (verified 2026-09-12, all must be resolved)

| # | File | Coupling | Resolution (task) |
|---|------|----------|-------------------|
| 1 | `services/api/app/service/retrieval.py:5,26` | `from rag.types import AccessFilter`; lazy `from rag.retrieval.search import search_rag` | Delete file (Task 3). Search is served by rag-service |
| 2 | `services/api/app/types/retrieval.py:3` | Re-exports `rag.types` contract | Delete file (Task 3). Contract lives in rag-service + `packages/shared` TS types |
| 3 | `services/api/app/repo/rag_auth.py:20,90` | `from rag.types import AccessFilter`; lazy `from rag.repo import neon_repo` | Move to rag-service as `src/rag/runtime/auth.py` (Task 1). Docstring already says "do not diverge" from enterprise source — move verbatim, only the settings import changes |
| 4 | `services/api/app/runtime/retrieval.py` | `POST /retrieval/search` router | Move to rag-service as `src/rag/runtime/search.py` (Task 1). Api drops the route |
| 5 | `services/api/app/service/upload.py:130-158` | `_maybe_index_in_rag` calls `rag.index_document(content, filename, source, department, access_level)` with bytes loaded via `get_object_bytes(key)` | Rewire to `repo/rag_client.index_document(...)` HTTP call, same signature, same best-effort contract (Task 3) |
| 6 | `services/api/app/service/files.py:156-169` | `remove_file` calls `rag.delete_indexed_source(key)` | Rewire to `repo/rag_client.delete_indexed_source(...)` HTTP call, same best-effort contract (Task 3) |
| 7 | `services/api/app/config/settings.py:156-167` | `qdrant_*`, `rag_database_url`, `rag_jwt_*`, `rag_rate_limit_*` settings | Delete block from api; equivalent lives in rag-service settings (Task 1). Api gains only `rag_service_url` + `rag_service_token` (Task 3) |
| 8 | `services/api/main.py:235` | `app.include_router(retrieval.router, ...)` | Delete line (Task 3) |
| 9 | `services/api/requirements.txt:10` | `-e ../rag` editable install | Delete line (Task 3). Api no longer installs rag |
| 10 | `services/api/pyproject.toml:12` | `dependencies = ["ai-saas-shared", "ai-saas-rag"]` | Drop `"ai-saas-rag"` → `["ai-saas-shared"]` (Task 3). Reverts the 2026-09-12 manifest fix, which was accurate for the coupled state |
| 11 | `services/api/tests/test_retrieval.py` | 401/503/filter tests against api routes + `rag_auth` | Move to rag-service tests, retargeted at the new app (Task 1) |
| 12 | `services/api/tests/test_rag_ingestion.py` | Mocks `rag.index_document` / `rag.delete_indexed_source` module attrs | Rewrite to mock `repo/rag_client` adapter fns instead (Task 3) |
| 13 | Frontend | Zero RAG client code (`api-client.ts`, `queries.ts` have no retrieval fns; no `/assistant` route) | Greenfield: TS types + client + hook + page (Task 4) |
| 14 | `docs/features/retrieval.md` | Documents coupled state ("temporarily housed in `services/api/app/repo/rag_auth.py`") | Rewrite (Task 6) |

---

## Locked decisions (do not relitigate during execution)

1. **Transport = HTTP, no queue.** The two api→rag triggers are already synchronous best-effort calls; making them HTTP POSTs preserves exact semantics. A queue (Redis/SQS) is deferred tech debt, recorded in Task 6.
2. **Api POSTs bytes it already holds.** `_maybe_index_in_rag` already loads object bytes via `get_object_bytes(key)`; the adapter POSTs those bytes as multipart to the rag-service. No B2 credentials move to rag-service. 100 MB edge noted as debt (same as today's in-process limit — no regression).
3. **Identity propagates, policy centralizes (multi-service auth model).** Every future consumer (api, worker, assistant UI, service Y) authenticates its OWN callers with whatever issuer fits it and forwards **identity, not decisions**, to rag-service: the end-user JWT directly (browser/direct callers), or `{service_token + user identity attributes}` for service-mediated calls (RFC 8693 delegation-style: `sub` = user, calling service named as actor). Rag-service verifies every inbound token itself (signature + `iss` + `exp`, zero-trust — no trust-on-network), then its single `resolve_filter()` seam maps subject attributes → `AccessFilter`, enforced as a retrieval-time metadata filter (Qdrant/pgvector pushdown) BEFORE any document reaches a model. Deny-by-default, fail closed. Rationale (researched 2026-09-12): access-token propagation (microservices.io) + retrieval-time filter enforcement is the standard two-layer defense-in-depth shape (AWS Bedrock + Verified Permissions 2026 pattern; Azure secure-multitenant-RAG guidance). Externalized policy engines (Cedar/OPA) are deferred per YAGNI — `resolve_filter()` is the seam where one plugs in later without touching callers. RBAC today (`read:*` → levels, departments) is just one mapping inside that seam; ABAC later means richer subject/object attributes flowing through the same function, per NIST SP 800-162. Concrete issuers at split time: Supabase JWT for the browser assistant (the web frontend has no enterprise-JWT issuance flow — finding #13; `python-jose`, already a rag dep, verifies it; user id maps to `["general", "public"]` + own subject as department, `max_access_level=1/internal` — exact mapping in Task 1, Step 3) and the enterprise JWT chain (`require_rag_rate_limit`, moved verbatim) for machine callers.
4. **Service-to-service = shared secret.** New `RAG_SERVICE_TOKEN` env var, sent as `Authorization: Bearer` on ingest/purge calls, verified in rag-service with `secrets.compare_digest`. No new dependencies.
5. **No shared RAG library; each service owns a thin adapter.** Future services MUST NOT `import rag` (no `-e ../rag`, no `ai-saas-rag` dep) — shared business-logic libraries force lockstep redeploys of all Y consumers and couple their evolution (Sam Newman / microservices.io consensus; Azure guidance against sharing libs across services). Each consumer handles its own API logic (routes, validation, caller auth) and talks HTTP to rag-service through its own small `repo/`-layer adapter (api's `repo/rag_client.py` from Task 3 is the reference copy — copy it, don't import it). Shared *request/response schemas* as a package are acceptable if drift ever hurts, but start duplicated.
6. **Rag-service layout mirrors api conventions:** `main.py` entrypoint + `src/rag/runtime/` handlers + existing `config/repo/retrieval/ingestion/types` layers. `services/shared` stays dependency-free (nothing moves there — `AccessFilter` needs Pydantic, shared forbids third-party deps).

---

### Task 1: Rag-service HTTP shell (search moves out first)

**Files:**
- Create: `services/rag/requirements.txt`
- Create: `services/rag/main.py`
- Create: `services/rag/src/rag/runtime/__init__.py`
- Create: `services/rag/src/rag/runtime/auth.py` (moved from `services/api/app/repo/rag_auth.py`, settings import swapped)
- Create: `services/rag/src/rag/runtime/search.py` (moved from `services/api/app/runtime/retrieval.py`)
- Create: `services/rag/src/rag/runtime/health.py`
- Modify: `services/rag/src/rag/config.py` (append service settings block)
- Modify: `services/rag/pyproject.toml` (add `[project.scripts]`? NO — keep library; add pytest `asyncio_mode` only if async tests are added; add `fastapi>=0.115`, `uvicorn[standard]`, `httpx`, `python-multipart` to `dependencies`)
- Create: `services/rag/railway.json`
- Create: `services/rag/tests/test_search_api.py` (moved + retargeted from `services/api/tests/test_retrieval.py`)
- Modify: `services/api/tests/test_retrieval.py` — DELETE in Task 3, not here

**Interfaces:**
- Consumes: `rag.types.*` (unchanged), `rag.retrieval.search.search_rag` (unchanged), `rag.repo.neon_repo` (unchanged).
- Produces (used by Task 2, Task 3, Task 4):
  - `POST /retrieval/search` — body `SearchRequest{question, top_k, search_mode}`, enterprise-JWT bearer → `SearchResponse`; unconfigured → `503`; bad query → `400`. Identical status contract to today's api route.
  - `GET /health` → `{"status": "ok", "service": "rag"}` (mirrors worker `health()` shape in `services/worker/src/worker/main.py:30-33`).
  - `get_rag_settings()` gains: `rag_jwt_secret`, `rag_jwt_algorithm="HS256"`, `rag_rate_limit_requests=60`, `rag_rate_limit_window_seconds=60`, `rag_service_token=""`, `supabase_jwt_secret=""`, `cors_origins=""`, `metrics_token=""`.

- [ ] **Step 1: Write the failing test** — create `services/rag/tests/test_search_api.py` importing the new app before it exists:

```python
from fastapi.testclient import TestClient

from main import app


def test_health():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "rag"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd services/rag && ../api/.venv/bin/python -m pytest tests/test_search_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'` (no `main.py`, no fastapi installed for rag yet).

- [ ] **Step 3: Create `requirements.txt`, `main.py`, `runtime/` shell**

`services/rag/requirements.txt` (pins mirror api style — exact `==`; versions below are current at plan date, re-resolve with `pip index versions` if stale):

```
-e ../shared
fastapi==0.139.2
uvicorn[standard]==0.51.0
python-multipart==0.0.32
python-dotenv==1.2.2
pydantic==2.13.4
pydantic-settings==2.14.2
qdrant-client>=1.9
rank-bm25>=0.2.2
openai>=1
psycopg[binary]>=3.1
psycopg-pool>=3.1
pgvector>=0.3
tenacity>=8.2
python-jose[cryptography]>=3.3
pdfplumber>=0.11
langchain-text-splitters>=0.3
httpx==0.28.1
ruff==0.15.22
pytest==9.1.1
pytest-asyncio==1.4.0
```

(`-e ../shared` is vestigial today — rag imports zero `shared` symbols — but keeps the workspace install uniform; remove only if `pip install -r requirements.txt` is verified green without it. Do NOT add `ai-saas-shared` to pyproject `dependencies` — the graph must not gain a phantom edge.)

`services/rag/main.py` — copy the shape of `services/api/main.py:137-181` (JSONFormatter + lifespan + middleware ordering CORS-outermost). Lifespan validates NOTHING hard (all RAG backends optional → 503 at request time, per `docs/features/retrieval.md` Configuration section); it only warns when `metrics_token` is empty. Mount `runtime.search.router` and `runtime.health.router`. CORS origins from `get_rag_settings().cors_origins_list` (add as property next to the api's `cors_origins` pattern in `services/api/app/config/settings.py:181-184`).

`src/rag/runtime/auth.py` — verbatim move of `services/api/app/repo/rag_auth.py` (all 117 lines, including the `TODO(auth-package)` header and the "do not diverge" notice). ONLY change: `from app.config import settings` → `from rag.config import get_rag_settings` via a module-level `settings = get_rag_settings()` alias. Append ONE new function (browser auth, per locked decision 3):

```python
def require_supabase_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AccessFilter:
    """Browser-facing auth: verify Supabase JWT, map to a default access filter.

    Enterprise machine callers keep using require_rag_rate_limit (enterprise JWT).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing sub",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AccessFilter(departments=["general", "public", subject], max_access_level=1)
```

`src/rag/runtime/search.py` — verbatim move of `services/api/app/runtime/retrieval.py` (26 lines). ONLY changes: `from app.repo.rag_auth import ...` → `from rag.runtime.auth import ...`; `from app.service.retrieval import RetrievalUnavailable, search` → local thin wrapper calling `rag.retrieval.search.search_rag` after the configured-guard (`if not settings.qdrant_url or not settings.rag_database_url: raise RetrievalUnavailable(...)`, copied from `services/api/app/service/retrieval.py:19-21`). Add a second route on the same router for browsers:

```python
@router.post("/assistant/search", response_model=SearchResponse)
def assistant_search_endpoint(
    request: SearchRequest,
    access_filter: AccessFilter = Depends(require_supabase_user),
) -> SearchResponse:
    try:
        return search_rag(
            question=request.question,
            top_k=request.top_k,
            search_mode=request.search_mode,
            access_filter=access_filter,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
```

Note: NO `RetrievalUnavailable` catch here is wrong — keep it: wrap exactly like the enterprise route (503 when unconfigured). The snippet above is abbreviated; the real file catches both, mirroring `retrieval_search_endpoint`.

`src/rag/runtime/health.py` (new, 12 lines):

```python
"""Health probe: no dependencies, no auth (Railway healthcheck target)."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "rag"}
```

`services/rag/railway.json` — copy of `services/api/railway.json` with `startCommand: "uvicorn main:app --host 0.0.0.0 --port $PORT"`, `healthcheckPath: "/health"`, working directory `services/rag`.

- [ ] **Step 4: Move `test_retrieval.py` coverage** — port `services/api/tests/test_retrieval.py` cases to `services/rag/tests/test_search_api.py`: 401 on missing/bad enterprise token, 503 when `qdrant_url`/`rag_database_url` empty, plus new 401 cases for `/assistant/search` with missing/bad Supabase token (set `supabase_jwt_secret=test-secret`, mint via `jose.jwt.encode({"sub": "u-1"}, "test-secret", algorithm="HS256")`). Reuse the file's `_rag_token` helper pattern verbatim.

- [ ] **Step 5: Run rag tests + ruff**

Run: `cd services/rag && ../api/.venv/bin/python -m pytest -q` — Expected: all pass (42 existing + new search tests).
Run: `cd services/rag && ../api/.venv/bin/ruff check .` — Expected: clean. (`pyproject.toml` ruff section already unified 2026-09-12; `known-first-party = ["rag"]` covers new `runtime/` modules.)

- [ ] **Step 6: Boot the service and hit both routes**

Run: `cd services/rag && ../api/.venv/bin/uvicorn main:app --port 8001 & sleep 3 && curl -s localhost:8001/health && curl -s -X POST localhost:8001/retrieval/search -H 'Content-Type: application/json' -d '{"question":"hi"}' ; kill %1`
Expected: `{"status":"ok","service":"rag"}` then `503` (unconfigured backends) — proves wiring without needing Qdrant/Neon.

- [ ] **Step 7: Commit**

```bash
git add services/rag/
git commit -m "feat(rag): standalone service shell with search + health + browser auth"
```

---

### Task 2: Ingestion endpoints on rag-service (index + purge)

**Files:**
- Create: `services/rag/src/rag/runtime/ingest.py`
- Modify: `services/rag/main.py` (mount router)
- Create: `services/rag/tests/test_ingest_api.py`
- Modify: `services/rag/src/rag/config.py` (nothing new — `rag_service_token` already added in Task 1)

**Interfaces:**
- Consumes: `rag.ingestion.index.index_document` + `delete_indexed_source` (signatures from `services/rag/src/rag/__init__.py:3` — `index_document(content, filename, source=..., department=..., access_level=...)`, `delete_indexed_source(source)`), `get_rag_settings().rag_service_token`.
- Produces (used by Task 3):
  - `POST /ingest` — multipart `file` + form fields `source`, `department=""`, `access_level=""`; header `Authorization: Bearer <RAG_SERVICE_TOKEN>`. Returns `IngestionResult` (`rag/types.py:46-50`). Failures inside `index_document` → `422` with `detail` (never 500 for bad content — mirrors today's `except ValueError: return False` mapping to `rag_indexed=false`).
  - `DELETE /sources?source=<key>` — same auth. Returns `{"purged": true}`. Never 500s on backend failure → `202` with `{"purged": false}` (mirrors today's swallow-and-log purge).

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from main import app

TOKEN = "svc-test-token"


def test_ingest_rejects_bad_service_token(monkeypatch):
    monkeypatch.setattr("rag.runtime.ingest.settings", _settings_with(token="svc-test-token"))
    client = TestClient(app)
    resp = client.post(
        "/ingest",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"source": "uploads/u-1/doc.pdf"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401
```

(Helper `_settings_with` builds a `SimpleNamespace`-style override — in the real file, monkeypatch `rag.runtime.ingest.settings` attributes directly, following the `monkeypatch.setattr(settings, ...)` pattern in `services/api/tests/test_retrieval.py:29-45`. Show the real code, not the sketch: `monkeypatch.setattr(ingest.settings, "rag_service_token", "svc-test-token")` after `from rag.runtime import ingest`.)

- [ ] **Step 2: Run it to verify it fails**

Run: `cd services/rag && ../api/.venv/bin/python -m pytest tests/test_ingest_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rag.runtime.ingest'` (or 404 no-route if only the module is missing — either proves absence).

- [ ] **Step 3: Write `src/rag/runtime/ingest.py`** (under 60 lines):

```python
"""Ingestion routes: service-to-service only (RAG_SERVICE_TOKEN bearer)."""

import logging
import secrets

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rag.ingestion.index import delete_indexed_source, index_document
from rag.runtime.auth import settings
from rag.types import IngestionResult

logger = logging.getLogger(__name__)

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


def require_service_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if not settings.rag_service_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG service token not configured",
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings.rag_service_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/ingest", response_model=IngestionResult)
async def ingest_endpoint(
    file: UploadFile = File(...),
    source: str = Form(...),
    department: str | None = Form(None),
    access_level: str | None = Form(None),
    _authed: None = Depends(require_service_token),
) -> IngestionResult:
    content = await file.read()
    try:
        return index_document(
            content,
            file.filename or source,
            source=source,
            department=department,
            access_level=access_level,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


@router.delete("/sources")
def delete_source_endpoint(
    source: str,
    _authed: None = Depends(require_service_token),
) -> dict[str, bool]:
    try:
        delete_indexed_source(source)
    except Exception:
        logger.exception("RAG purge failed: source=%s", source)
        return {"purged": False}
    return {"purged": True}
```

Mount in `main.py`: `app.include_router(ingest.router, tags=["ingest"])`.

- [ ] **Step 4: Tests for 200/422/202 paths** — 200 with monkeypatched `index_document` returning `IngestionResult(documents_loaded=1, chunks_created=3, chunks_indexed=3, sources=["s"])` (assert passthrough); 422 when it raises `ValueError`; `DELETE /sources` returns `{"purged": true}` and `{"purged": false}` when `delete_indexed_source` raises. Follow the `test_rag_ingestion.py` fake pattern (`mon
...[truncated 10916 chars]