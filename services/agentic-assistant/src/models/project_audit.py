"""Project-scoped audit event read models."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectAuditEvent(BaseModel):
    id: int
    actor_id: str | None = None
    actor_email: str | None = None
    action: str
    resource: str
    target_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


def _detail(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


async def list_project_audit_events_async(
    connection: Any, *, project_id: str, limit: int = 100
) -> list[ProjectAuditEvent]:
    bounded_limit = max(1, min(limit, 200))
    cursor = await connection.execute(
        "SELECT id, actor_id, actor_email, action, resource, target_id, detail, created_at "
        "FROM assistant_audit_events "
        "WHERE detail->>'project_id' = %s "
        "ORDER BY created_at DESC LIMIT %s",
        (project_id, bounded_limit),
    )
    return [
        ProjectAuditEvent(
            id=row[0],
            actor_id=row[1],
            actor_email=row[2],
            action=row[3],
            resource=row[4],
            target_id=row[5],
            detail=_detail(row[6]),
            created_at=row[7],
        )
        for row in await cursor.fetchall()
    ]
