"""Shared RAG boundary types. No logic, no imports from other layers."""

from typing import Literal

from pydantic import BaseModel, Field

SearchMode = Literal["semantic", "hybrid", "auto"]


class AccessFilter(BaseModel):
    """Resolved access policy passed into retrieval. Never constructed by rag itself."""

    departments: list[str]
    max_access_level: int


class Source(BaseModel):
    source: str
    page: int | None = None
    chunk_index: int | None = None
    score: float | None = None


class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=10)
    search_mode: SearchMode = "auto"


class SearchResult(BaseModel):
    text: str
    source: Source


class SearchResponse(BaseModel):
    question: str
    results: list[SearchResult]
    search_mode: SearchMode = "auto"


class TextChunk(BaseModel):
    text: str
    metadata: dict = Field(default_factory=dict)


class IngestionResult(BaseModel):
    documents_loaded: int
    chunks_created: int
    chunks_indexed: int = 0
    sources: list[str]
