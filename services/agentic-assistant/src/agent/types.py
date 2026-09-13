"""Assistant boundary types. Reuses rag contract types; no logic."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from rag.types import IngestionResult, SearchMode, SearchResult, Source


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=10)
    search_mode: SearchMode = "auto"
    conversation_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    rewritten_question: str | None = None
    grounded: bool = False
    workflow_steps: list[str] = Field(default_factory=list)
    conversation_id: str | None = None


class IndexedDocument(BaseModel):
    """One row of the documents registry for the admin sources view."""

    tenant: str | None = None
    source: str
    department: str | None = None
    access_level: str | None = None
    chunks_count: int = 0
    indexed_at: str | None = None
    status: str | None = None


class IngestJobAccepted(BaseModel):
    """202 receipt for a queued background ingest."""

    job_id: str
    status: str = "queued"


class IngestJobStatus(BaseModel):
    """Pollable ingest state: queued | running | done | failed."""

    job_id: str
    status: str
    result: IngestionResult | None = None
    error: str | None = None


class ConversationTurn(BaseModel):
    """One rendered Q/A turn for history reloads. Mirrors the web ConversationTurn."""

    turn_index: int
    question: str
    answer: str
    sources: list[dict] = Field(default_factory=list)
    created_at: str | None = None


ProjectResolutionStatus = Literal[
    "resolved", "unresolved", "not_found", "ambiguous", "forbidden", "validation_error"
]


class ProjectCandidate(BaseModel):
    """Safe project identity exposed to a project-agent tool."""

    project_id: str
    name: str
    description: str | None = None


class ProjectResolution(BaseModel):
    """Resolution envelope shared by all project-agent tool results."""

    status: ProjectResolutionStatus
    project: ProjectCandidate | None = None
    candidates: list[ProjectCandidate] = Field(default_factory=list, max_length=10)
    message: str


class ProjectStatusResult(BaseModel):
    resolution: ProjectResolution
    status: str | None = None
    completion_percentage: int | None = Field(default=None, ge=0, le=100)
    feature_counts: dict[str, int] = Field(default_factory=dict)
    open_blocker_count: int | None = Field(default=None, ge=0)


class ProjectHistoryItem(BaseModel):
    feature_id: str
    feature_name: str
    old_status: str
    new_status: str
    changed_by: str
    changed_at: datetime


class ProjectHistoryResult(BaseModel):
    resolution: ProjectResolution
    items: list[ProjectHistoryItem] = Field(default_factory=list, max_length=100)


class ProjectMetricsResult(BaseModel):
    resolution: ProjectResolution
    completion_percentage: int | None = Field(default=None, ge=0, le=100)
    feature_counts: dict[str, int] = Field(default_factory=dict)
    open_blocker_count: int | None = Field(default=None, ge=0)


class ProjectKnowledgeResult(BaseModel):
    resolution: ProjectResolution
    results: list[SearchResult] = Field(default_factory=list, max_length=10)
    query: str
