"""Ingestion routes: index-on-finalize + purge-on-delete for service callers.

Manual ingestion/deletion only — no agent tool wraps these (per product
decision: retrieval is the tool; ingest/delete are explicit operations).
Best-effort contract mirrors the old in-API behavior: bad content → 422,
backend failure on purge → `{"purged": false}` (never 500 the caller).
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from rag.ingestion.index import delete_indexed_source, index_document
from rag.types import IngestionResult

from agent.config import get_agent_settings

logger = logging.getLogger(__name__)

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


def require_service_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    settings = get_agent_settings()
    if not settings.agent_service_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion not configured",
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings.agent_service_token
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
    tenant: str | None = Form(None),
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
            tenant=tenant,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


@router.delete("/sources")
def delete_source_endpoint(
    source: str,
    tenant: str | None = None,
    _authed: None = Depends(require_service_token),
) -> dict[str, bool]:
    try:
        delete_indexed_source(source, tenant=tenant)
    except Exception:
        logger.exception("RAG purge failed: source=%s", source)
        return {"purged": False}
    return {"purged": True}
