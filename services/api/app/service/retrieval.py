"""Retrieval business logic: thin wrapper over the shared rag single tool."""

import logging

from rag.types import AccessFilter

from app.config import settings
from app.types.retrieval import SearchRequest, SearchResponse

logger = logging.getLogger(__name__)


class RetrievalUnavailable(Exception):
    def __init__(self, detail: str = "Retrieval is not configured"):
        self.detail = detail
        super().__init__(detail)


def _require_configured() -> None:
    if not settings.qdrant_url or not settings.rag_database_url:
        raise RetrievalUnavailable("QDRANT_URL / RAG_DATABASE_URL must be set")


def search(request: SearchRequest, access_filter: AccessFilter) -> SearchResponse:
    _require_configured()
    from rag.retrieval.search import search_rag

    return search_rag(
        question=request.question,
        top_k=request.top_k,
        search_mode=request.search_mode,
        access_filter=access_filter,
    )
