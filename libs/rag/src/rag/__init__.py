"""Shared RAG package: retrieval now, direct ingestion later."""

from rag.ingestion.index import delete_indexed_source, index_document
from rag.retrieval.search import search_rag, search_rag_async

__all__ = ["delete_indexed_source", "index_document", "search_rag", "search_rag_async"]
