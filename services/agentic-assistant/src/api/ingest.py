"""Ingestion routes: index-on-finalize + purge-on-delete for service callers.

Manual ingestion/deletion only — no agent tool wraps these (per product
decision: retrieval is the tool; ingest/delete are explicit operations).
Auth is dual: the shared service token (machine forwarders) or an admin
assistant JWT (browser callers after frontend login). Best-effort contract
mirrors the old in-API behavior: bad content → 422, backend failure on
purge → `{"purged": false}` (never 500 the caller).

Indexing runs as an in-process background job: POST returns 202 at once and
callers poll GET /ingest/{job_id}. A restart loses queued jobs; retry is
safe because registry content-hash dedup makes re-ingest idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from auth.types import AssistantClaims
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from rag.ingestion.index import delete_indexed_source
from rag.ingestion.loaders import SUPPORTED_SUFFIXES
from rag.repo.neon_repo import ensure_tables, get_conn, list_documents

from agent.authz import require_service_or_admin
from agent.types import IndexedDocument, IngestJobAccepted, IngestJobStatus
from service.ingest_jobs import create_job, get_job, run_index_job

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ingest", response_model=IngestJobAccepted, status_code=202)
async def ingest_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source: str = Form(...),
    department: str | None = Form(None),
    access_level: str | None = Form(None),
    tenant: str | None = Form(None),
    _authed: AssistantClaims | None = Depends(require_service_or_admin),
) -> IngestJobAccepted:
    content = await file.read()
    filename = file.filename or source
    if not content:
        raise HTTPException(status_code=422, detail="Empty file")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        logger.warning("ingest: rejected source=%s suffix=%s", source, suffix)
        raise HTTPException(status_code=422, detail=f"Unsupported document type: {suffix}")
    job_id = create_job(source)
    logger.info(
        "ingest: queued job=%s filename=%s source=%s size=%d tenant=%s",
        job_id,
        filename,
        source,
        len(content),
        tenant,
    )
    background_tasks.add_task(
        run_index_job, job_id, content, filename, source, department, access_level, tenant
    )
    return IngestJobAccepted(job_id=job_id)


@router.get("/ingest/{job_id}", response_model=IngestJobStatus)
def ingest_status_endpoint(
    job_id: str,
    _authed: AssistantClaims | None = Depends(require_service_or_admin),
) -> IngestJobStatus:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown ingest job")
    return IngestJobStatus(
        job_id=job["job_id"],
        status=str(job["status"]),
        result=job.get("result"),
        error=job.get("error"),
    )


@router.get("/sources", response_model=list[IndexedDocument])
def list_sources_endpoint(
    tenant: str | None = None,
    _authed: AssistantClaims | None = Depends(require_service_or_admin),
) -> list[IndexedDocument]:
    """Indexed documents for the admin console. tenant=None spans all tenants."""
    logger.info("ingest: list sources tenant=%s", tenant)
    with get_conn() as conn:
        ensure_tables(conn)
        rows = list_documents(conn, tenant=tenant)
    return [IndexedDocument(**row) for row in rows]


@router.delete("/sources")
async def delete_source_endpoint(
    source: str,
    tenant: str | None = None,
    _authed: AssistantClaims | None = Depends(require_service_or_admin),
) -> dict[str, bool]:
    logger.info("ingest: purge start source=%s tenant=%s", source, tenant)
    try:
        await asyncio.to_thread(delete_indexed_source, source, tenant=tenant)
    except Exception:
        logger.exception("RAG purge failed: source=%s", source)
        return {"purged": False}
    logger.info("ingest: purge done source=%s", source)
    return {"purged": True}
