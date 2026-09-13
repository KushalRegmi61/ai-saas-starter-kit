"""In-process ingest job store + background runner.

Jobs live in memory: a restart loses them. That is acceptable because
re-ingest is idempotent — the registry content-hash dedup turns a retry
into a no-op or a clean replace. No business rules here, only state moves.
"""

from __future__ import annotations

import logging
import threading
import uuid

from rag.ingestion.index import index_document

from agent.config import get_agent_settings

logger = logging.getLogger(__name__)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def create_job(source: str) -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {"job_id": job_id, "status": "queued", "source": source}
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None


def _set(job_id: str, **fields: object) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def run_index_job(
    job_id: str,
    content: bytes,
    filename: str,
    source: str,
    department: str | None,
    access_level: str | None,
    tenant: str | None,
) -> None:
    """Background entry: index one document, record done/failed on the job.

    Callers with no tenant of their own (browser admin uploads) inherit the
    host corpus identity — otherwise the doc lands in "default" where chat
    (which reads default_tenant) can never see it.
    """
    resolved_tenant = tenant or get_agent_settings().default_tenant
    _set(job_id, status="running")
    logger.info(
        "ingest: job %s running source=%s size=%d tenant=%s",
        job_id,
        source,
        len(content),
        resolved_tenant,
    )
    try:
        result = index_document(
            content,
            filename,
            source=source,
            department=department,
            access_level=access_level,
            tenant=resolved_tenant,
        )
    except Exception as exc:
        logger.exception("ingest: job %s failed source=%s", job_id, source)
        _set(job_id, status="failed", error=str(exc))
        return
    logger.info("ingest: job %s done source=%s", job_id, source)
    _set(job_id, status="done", result=result.model_dump())
