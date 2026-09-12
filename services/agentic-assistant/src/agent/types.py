"""Assistant boundary types. Reuses rag contract types; no logic, no layer imports."""

from pydantic import BaseModel, Field
from rag.types import SearchMode, Source


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=10)
    search_mode: SearchMode = "auto"
    conversation_history: list[dict] = Field(default_factory=list)


class AskResponse(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    rewritten_question: str | None = None
    grounded: bool = False
    workflow_steps: list[str] = Field(default_factory=list)
