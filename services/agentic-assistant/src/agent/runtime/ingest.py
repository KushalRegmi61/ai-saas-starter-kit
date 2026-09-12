"""Ingestion routes: index-on-finalize + purge-on-delete for service callers.

Manual ingestion/deletion only — no agent tool wraps these (per product
decision: retrieval is the tool; ingest/delete are explicit operations).
Auth is dual: the shared service token (machine forwarders) or an admin
assistant JWT (browser callers after frontend login). Best-effort contract
mirrors the old in-API behavior: bad content → 422, backend failure on
purge → `{"purged": false}` (never 500 the caller).
"""

from __future__ import annotations

import logging

from auth.types import AssistantClaims
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from rag.ingestion.index import delete_indexed_source, index_document
from rag.types import IngestionResult

from agent.authz import require_service_or_admin

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ingest", response_model=IngestionResult)
async def ingest_endpoint(
    file: UploadFile = File(...),
    source: str = Form(...),
    department: str | None = Form(None),
    access_level: str | None = Form(None),
    tenant: str | None = Form(None),
    _authed: AssistantClaims | None = Depends(require_service_or_admin),
) -> IngestionResult:
    content = await file.read()
    try:
        return index_document(
            content,
            file.filename or source,
            source=source,
            department=department,
            access_level=access_level,
            tenant=tenant,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


@router.delete("/sources")
def delete_source_endpoint(
    source: str,
    tenant: str | None = None,
    _authed: AssistantClaims | None = Depends(require_service_or_admin),
) -> dict[str, bool]:
    try:
        delete_indexed_source(source, tenant=tenant)
    except Exception:
        logger.exception("RAG purge failed: source=%s", source)
        return {"purged": False}
    return {"purged": True}
