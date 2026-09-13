"""Safe response contracts for natural-language project MCP operations."""

from __future__ import annotations

from pydantic import BaseModel, Field

from models.project_state import DailyProjectUpdate, ProjectBlocker, ProjectFeature


class ReferenceCandidate(BaseModel):
    id: str
    label: str
    description: str | None = None
    status: str


class ProjectToolResult(BaseModel):
    status: str
    message: str | None = None
    feature: ProjectFeature | None = None
    blocker: ProjectBlocker | None = None
    update: DailyProjectUpdate | None = None
    candidates: list[ReferenceCandidate] = Field(default_factory=list)


class ProjectUpdatesResult(BaseModel):
    updates: list[DailyProjectUpdate]
    since: str | None = None
    limit: int
