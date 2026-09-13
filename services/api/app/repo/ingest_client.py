"""HTTP client for the agentic-assistant ingestion surface.

The RAG engine moved out of this process: finalized uploads are forwarded to
``POST /ingest`` and deletions purged via ``DELETE /sources`` on the agent
service (service-token auth). Both helpers are best-effort and never raise —
callers treat ``False`` as "indexed/purged elsewhere or not at all".
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 60.0


def _auth() -> tuple[str, str] | None:
    url = settings.agent_service_url.strip().rstrip("/")
    token = settings.agent_service_token
    if not url or not token:
        return None
    return url, token


def index_document_remote(
    content: bytes,
    filename: str,
    source: str,
    department: str | None = None,
    access_level: str | None = None,
    tenant: str | None = None,
) -> bool:
    """Forward one document to the agent ingest endpoint. Never raises.

    The agent queues indexing as a background job: both 200 (legacy sync)
    and 202 (queued) count as accepted.
    """
    auth = _auth()
    if auth is None:
        return False
    url, token = auth
    data = {"source": source}
    if department is not None:
        data["department"] = department
    if access_level is not None:
        data["access_level"] = access_level
    if tenant is not None:
        data["tenant"] = tenant
    try:
        resp = httpx.post(
            f"{url}/ingest",
            files={"file": (filename, content)},
            data=data,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT_SECONDS,
        )
        return resp.status_code in (200, 202)
    except Exception:
        logger.exception("Agent ingest forward failed: source=%s", source)
        return False


def delete_indexed_source_remote(source: str, tenant: str | None = None) -> bool:
    """Ask the agent service to purge a source. Never raises."""
    auth = _auth()
    if auth is None:
        return False
    url, token = auth
    params = {"source": source}
    if tenant is not None:
        params["tenant"] = tenant
    try:
        resp = httpx.delete(
            f"{url}/sources",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            return False
        return bool(resp.json().get("purged", False))
    except Exception:
        logger.exception("Agent purge forward failed: source=%s", source)
        return False
